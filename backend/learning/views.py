from __future__ import annotations

import random
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import FileResponse
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from learning.models import BulkGenerationItem, BulkGenerationJob, CardSchedule, Flashcard, LlmUsage, Pool, ReviewLog, UserProfile
from learning.serializers import BulkGenerationJobSerializer, FlashcardSerializer, PoolSerializer, ProfileSerializer, RegisterSerializer
from learning.services.english import InvalidEnglishTerm, normalize_bulk_terms, validate_english_term
from learning.services import images as image_service
from learning.services.images import ImageError
from learning.exceptions import LlmResponseError
from learning.services.llm import craft_image_query, generate_flashcard, judge_definition, resolve_image_url
from learning.services.pronunciation import PronunciationError, generate_pronunciation
from learning.services.model_catalog import model_catalog
from learning.services.scheduler import apply_rating, automatic_rating, priority
from learning.services.queues import due_breakdown, due_cards, remaining_new_slots
from learning.services.pools import next_pool_accent, pool_has_active_job, transfer_pool
from learning.services.bulk import refresh_job_counts


def profile_for(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token = Token.objects.create(user=user)
        return Response({'token': token.key, 'username': user.username}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user = authenticate(username=request.data.get('username', ''), password=request.data.get('password', ''))
        if not user:
            return Response({'detail': 'Invalid username or password.'}, status=400)
        token, _ = Token.objects.get_or_create(user=user)
        profile_for(user)
        return Response({'token': token.key, 'username': user.username})


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=204)


class MeView(APIView):
    def get(self, request):
        return Response({'username': request.user.username, 'settings': ProfileSerializer(profile_for(request.user)).data})


class SettingsView(APIView):
    def get(self, request):
        return Response(ProfileSerializer(profile_for(request.user)).data)

    def patch(self, request):
        serializer = ProfileSerializer(profile_for(request.user), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ModelsView(APIView):
    def get(self, request):
        return Response({'models': model_catalog()})


class PoolViewSet(viewsets.ModelViewSet):
    serializer_class = PoolSerializer

    def get_queryset(self):
        now = timezone.now()
        return Pool.objects.filter(user=self.request.user).annotate(
            card_count=Count('cards', distinct=True),
            due_non_new_count=Count(
                'cards',
                filter=Q(
                    cards__schedule__due_at__lte=now,
                    cards__suspended=False,
                ) & ~Q(cards__schedule__state=CardSchedule.State.NEW),
                distinct=True,
            ),
            due_new_count=Count(
                'cards',
                filter=Q(
                    cards__schedule__due_at__lte=now,
                    cards__suspended=False,
                    cards__schedule__state=CardSchedule.State.NEW,
                ),
                distinct=True,
            ),
        ).order_by('-updated_at')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context['remaining_new_slots'] = remaining_new_slots(
                user=self.request.user,
                profile=profile_for(self.request.user),
            )
        return context

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, accent=next_pool_accent(self.request.user))

    def destroy(self, request, *args, **kwargs):
        pool = self.get_object()
        if pool_has_active_job(pool):
            return Response({'detail': 'Wait for the active bulk-generation job to finish before deleting this pool.'}, status=409)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        source = self.get_object()
        target = Pool.objects.filter(pk=request.data.get('target_pool'), user=request.user).first()
        if not target:
            return Response({'target_pool': ['Target pool not found.']}, status=404)
        try:
            result = transfer_pool(source=source, target=target, mode=str(request.data.get('mode') or 'copy'))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response(result)


class FlashcardPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100


class FlashcardViewSet(viewsets.ModelViewSet):
    serializer_class = FlashcardSerializer
    pagination_class = FlashcardPagination

    def get_queryset(self):
        qs = Flashcard.objects.filter(pool__user=self.request.user).select_related('pool', 'schedule')
        pool_id = self.request.query_params.get('pool')
        search = self.request.query_params.get('search', '').strip()
        if pool_id:
            qs = qs.filter(pool_id=pool_id)
        if search:
            qs = qs.filter(Q(term__icontains=search) | Q(definition__icontains=search))
        return qs

    def perform_destroy(self, instance):
        instance.delete()

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        card = self.get_object()
        card.suspended = True
        card.save(update_fields=['suspended', 'updated_at'])
        return Response(FlashcardSerializer(card, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def unsuspend(self, request, pk=None):
        card = self.get_object()
        card.suspended = False
        card.save(update_fields=['suspended', 'updated_at'])
        return Response(FlashcardSerializer(card, context={'request': request}).data)

    @action(detail=True, methods=['get', 'post', 'delete'])
    def image(self, request, pk=None):
        card = self.get_object()
        if request.method == 'GET':
            field = card.image_thumb if request.query_params.get('size') == 'thumb' else card.image
            if not field:
                return Response({'detail': 'This card has no image.'}, status=404)
            response = FileResponse(field.open('rb'), content_type='image/jpeg')
            response['Cache-Control'] = 'private, max-age=31536000, immutable'
            return response
        if request.method == 'DELETE':
            image_service.remove_card_image(card)
            return Response(FlashcardSerializer(card, context={'request': request}).data)
        upload = request.FILES.get('file')
        url = str(request.data.get('url') or '').strip()
        source = 'upload'
        try:
            if upload:
                if upload.size > image_service.MAX_UPLOAD_BYTES:
                    raise ImageError('The file is larger than 12 MB.')
                data = upload.read()
            elif url:
                data, source = self._image_from_url(request, card, url)
            else:
                return Response({'detail': 'Send an image file or an image link.'}, status=400)
            image_service.store_card_image(card, data)
        except ImageError as exc:
            return Response({'detail': str(exc), 'code': 'image_failure'}, status=400)
        payload = FlashcardSerializer(card, context={'request': request}).data
        payload['image_source'] = source
        return Response(payload)

    @staticmethod
    def _image_from_url(request, card, url):
        try:
            return image_service.download_image(url), 'link'
        except ImageError as direct_error:
            # The link is a page, not a picture. Image-search pages (Google,
            # Yandex, …) render only through JavaScript, so for them the same
            # query is run against open image APIs; any other page is read for
            # its own image candidates. The image-assistant model picks.
            search_query = image_service.search_query_from_url(url)
            try:
                if search_query:
                    # The raw search text often carries meta words ("can noun")
                    # that ruin retrieval; the model rewrites it using the
                    # card's sense before the open image APIs are queried.
                    profile = profile_for(request.user)
                    try:
                        query = craft_image_query(user=request.user, profile=profile, card=card, search_text=search_query)
                    except LlmResponseError:
                        query = search_query
                    title = f'Image search for “{query}”'
                    candidates = image_service.search_image_candidates(query)
                else:
                    title, candidates = image_service.page_image_candidates(url)
            except ImageError:
                raise direct_error
            if not candidates:
                raise direct_error
            found = resolve_image_url(
                user=request.user, profile=profile_for(request.user), card=card,
                page_url=url, title=title, candidates=candidates,
            )
            return image_service.download_image(found), 'ai'


class GenerateView(APIView):
    def post(self, request):
        pool = Pool.objects.filter(id=request.data.get('pool'), user=request.user).first()
        if not pool:
            return Response({'detail': 'Pool not found.'}, status=404)
        term = str(request.data.get('term') or '').strip()
        if not term:
            return Response({'term': ['This field is required.']}, status=400)
        try:
            term = validate_english_term(term).normalized
        except InvalidEnglishTerm as exc:
            return Response({'term': [str(exc)]}, status=400)
        data = generate_flashcard(user=request.user, profile=profile_for(request.user), pool=pool, term=term)
        serializer = FlashcardSerializer(data={**data, 'pool': pool.id}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            card = serializer.save()
        except IntegrityError:
            return Response({'detail': 'This term already exists in the selected pool.'}, status=409)
        return Response(FlashcardSerializer(card, context={'request': request}).data, status=201)


class NormalizeTermsView(APIView):
    def post(self, request):
        result = normalize_bulk_terms(request.data.get('terms', []))
        if result.input_count > 1000:
            return Response({'terms': ['Provide at most 1000 source items.']}, status=400)
        return Response({
            'normalized': list(result.normalized),
            'changes': list(result.changes),
            'errors': list(result.errors),
            'input_count': result.input_count,
        })


class BulkGenerateView(APIView):
    def get(self, request):
        qs = BulkGenerationJob.objects.filter(user=request.user)
        pool_id = request.query_params.get('pool')
        if pool_id:
            qs = qs.filter(pool_id=pool_id)
        if request.query_params.get('active') in {'1', 'true', 'yes'}:
            qs = qs.filter(status__in=[BulkGenerationJob.Status.QUEUED, BulkGenerationJob.Status.RUNNING])
        return Response(BulkGenerationJobSerializer(qs[:10], many=True).data)

    @transaction.atomic
    def post(self, request):
        pool = Pool.objects.filter(id=request.data.get('pool'), user=request.user).first()
        if not pool:
            return Response({'detail': 'Pool not found.'}, status=404)
        if pool_has_active_job(pool):
            active = pool.bulk_generation_jobs.filter(status__in=[BulkGenerationJob.Status.QUEUED, BulkGenerationJob.Status.RUNNING]).first()
            return Response(BulkGenerationJobSerializer(active).data, status=409)
        normalization = normalize_bulk_terms(request.data.get('terms', []))
        if normalization.input_count > 1000:
            return Response({'terms': ['Provide at most 1000 source items.']}, status=400)
        terms = list(normalization.normalized)
        if not terms:
            return Response({'terms': ['No valid English terms were found.'], 'errors': list(normalization.errors)}, status=422)
        try:
            batch_size = max(1, min(200, int(request.data.get('batch_size', 20))))
        except (TypeError, ValueError):
            batch_size = 20
        job = BulkGenerationJob.objects.create(
            user=request.user, pool=pool, pool_name=pool.name,
            batch_size=batch_size, max_rounds=settings.BULK_MAX_ROUNDS,
            total_count=len(terms),
        )
        existing = set(pool.cards.filter(normalized_term__in=[term.casefold() for term in terms]).values_list('normalized_term', flat=True))
        items = []
        skipped = 0
        for position, term in enumerate(terms):
            status_value = BulkGenerationItem.Status.SKIPPED if term.casefold() in existing else BulkGenerationItem.Status.PENDING
            skipped += int(status_value == BulkGenerationItem.Status.SKIPPED)
            items.append(BulkGenerationItem(job=job, position=position, term=term, status=status_value, error='The term already exists in this pool.' if status_value == BulkGenerationItem.Status.SKIPPED else ''))
        BulkGenerationItem.objects.bulk_create(items)
        job.skipped_count = skipped
        if skipped == len(terms):
            job.status = BulkGenerationJob.Status.COMPLETED
            job.finished_at = timezone.now()
        job.save(update_fields=['skipped_count', 'status', 'finished_at', 'updated_at'])
        return Response(BulkGenerationJobSerializer(job).data, status=202)


class BulkJobDetailView(APIView):
    def get(self, request, job_id):
        job = BulkGenerationJob.objects.filter(pk=job_id, user=request.user).first()
        if not job:
            return Response({'detail': 'Bulk job not found.'}, status=404)
        return Response(BulkGenerationJobSerializer(job).data)


class BulkJobCancelView(APIView):
    @transaction.atomic
    def post(self, request, job_id):
        job = BulkGenerationJob.objects.select_for_update().filter(pk=job_id, user=request.user).first()
        if not job:
            return Response({'detail': 'Bulk job not found.'}, status=404)
        if job.status in {BulkGenerationJob.Status.QUEUED, BulkGenerationJob.Status.RUNNING}:
            message = 'Cancelled by the user.'
            job.items.filter(status__in=[
                BulkGenerationItem.Status.PENDING,
                BulkGenerationItem.Status.RUNNING,
                BulkGenerationItem.Status.FAILED,
            ]).update(status=BulkGenerationItem.Status.FAILED, error=message)
            job.status = BulkGenerationJob.Status.CANCELLED
            job.finished_at = timezone.now()
            job.active_item_ids = []
            job.save(update_fields=['status', 'finished_at', 'active_item_ids', 'updated_at'])
            job = refresh_job_counts(job.id)
        return Response(BulkGenerationJobSerializer(job).data)


def _direction(profile, card):
    if profile.study_direction != UserProfile.Direction.MIXED:
        return profile.study_direction
    return (ReviewLog.Direction.TERM_TO_DEFINITION if (card.id + card.schedule.repetitions) % 2 else ReviewLog.Direction.DEFINITION_TO_TERM)


def _upcoming_images(cards, limit=2):
    """The next queue cards that have images, so the client can prefetch them."""
    return [{'id': c.id, 'image_key': c.image.name} for c in cards if c.image][:limit]


def _images_enabled(profile, direction):
    """The global switch plus the per-direction preference for this task."""
    if not profile.show_card_images:
        return False
    if direction == ReviewLog.Direction.TERM_TO_DEFINITION:
        return profile.show_images_term_to_definition
    return profile.show_images_definition_to_term


class NextCardView(APIView):
    def get(self, request):
        profile = profile_for(request.user)
        pool_id = request.query_params.get('pool')
        mode = request.query_params.get('mode', 'due')
        if mode not in {'due', 'practice'}:
            return Response({'mode': ['Use due or practice.']}, status=400)
        pools = Pool.objects.filter(user=request.user, archived=False)
        if pool_id:
            pools = pools.filter(id=pool_id)
        now = timezone.now()
        base_cards = Flashcard.objects.filter(pool__in=pools, suspended=False).select_related('pool', 'schedule')
        if mode == 'practice':
            excluded = []
            for value in request.query_params.get('exclude', '').split(','):
                try:
                    excluded.append(int(value))
                except (TypeError, ValueError):
                    continue
            excluded = list(dict.fromkeys(excluded[:1000]))
            total_count = base_cards.count()
            completed_count = base_cards.filter(id__in=excluded).count()
            cards = list(base_cards.exclude(id__in=excluded))
            if not cards:
                has_cards = total_count > 0
                return Response({
                    'card': None,
                    'mode': mode,
                    'message': 'Practice round complete.' if has_cards else 'This pool has no cards yet.',
                    'practice_complete': has_cards,
                    'queue_count': 0,
                    'round_total': total_count,
                    'round_completed': completed_count,
                })
            ordered = sorted(cards, key=lambda c: (c.schedule.last_reviewed_at or c.created_at, c.id))
            card = ordered[0]
            direction = _direction(profile, card)
            payload = FlashcardSerializer(card, context={'request': request}).data
            prompt = card.term if direction == ReviewLog.Direction.TERM_TO_DEFINITION else card.short_definition
            return Response({
                'card': payload, 'direction': direction, 'prompt': prompt, 'mode': mode,
                'queue_count': len(cards), 'round_total': total_count,
                'round_completed': completed_count,
                'show_images': _images_enabled(profile, direction),
                'image_animations': list(profile.image_animations or []),
                'upcoming_images': _upcoming_images(ordered[1:]),
            })

        cards = due_cards(base_cards, user=request.user, profile=profile, now=now)
        if not cards:
            return Response({
                'card': None, 'mode': mode, 'message': 'Nothing is due. You are caught up.',
                'queue_count': 0, 'round_total': 0, 'round_completed': 0,
                'queue_breakdown': {'new': 0, 'learning': 0, 'review': 0},
            })
        # What the remaining queue consists of, so the Study page can explain
        # why the round grows when a failed card re-enters a learning step.
        breakdown = {'new': 0, 'learning': 0, 'review': 0}
        for candidate in cards:
            state = candidate.schedule.state
            if state == CardSchedule.State.NEW:
                breakdown['new'] += 1
            elif state == CardSchedule.State.REVIEW:
                breakdown['review'] += 1
            else:
                breakdown['learning'] += 1
        rank = {CardSchedule.State.RELEARNING: 4, CardSchedule.State.LEARNING: 3, CardSchedule.State.REVIEW: 2, CardSchedule.State.NEW: 1}
        ordered = sorted(cards, key=lambda c: (rank.get(c.schedule.state, 0), priority(c.schedule, now)), reverse=True)
        card = ordered[0]
        direction = _direction(profile, card)
        payload = FlashcardSerializer(card, context={'request': request}).data
        prompt = card.term if direction == ReviewLog.Direction.TERM_TO_DEFINITION else card.short_definition
        return Response({
            'card': payload, 'direction': direction, 'prompt': prompt, 'mode': mode,
            'queue_count': len(cards),
            'queue_breakdown': breakdown,
            'show_images': _images_enabled(profile, direction),
            'image_animations': list(profile.image_animations or []),
            'upcoming_images': _upcoming_images(ordered[1:]),
        })


def _normalize_answer(value):
    value = str(value).casefold().replace('’', "'")
    value = re.sub(r"[^a-z0-9'\s-]", ' ', value)
    return ' '.join(value.split())


def _is_verb_card(card: Flashcard) -> bool:
    part = card.part_of_speech.casefold()
    return card.term.casefold().startswith('to ') or 'verb' in part or bool(re.search(r'(^|[ /])v([ /]|$)', part))


def _recall_key(value, *, strip_infinitive: bool) -> str:
    normalized = _normalize_answer(value)
    if strip_infinitive and normalized.startswith('to '):
        normalized = normalized[3:].strip()
    return normalized


def _parse_response_ms(value):
    try:
        return max(0, min(int(value or 0), 60 * 60 * 1000))
    except (TypeError, ValueError):
        return 0


def _parse_bool(value):
    return value if isinstance(value, bool) else str(value or '').lower() in {'1', 'true', 'yes'}


def _parse_hints(data):
    try:
        return max(0, int(data.get('hint_revealed_letters') or 0)), max(0, int(data.get('hint_total_letters') or 0))
    except (TypeError, ValueError):
        return 0, 0


def _record_review(user, card_id, *, direction, answer, accepted, judge_score=None,
                   judge_verdict='', feedback='', response_ms=0, practice=False,
                   hint_revealed_letters=0, hint_total_letters=0):
    """Persist one review atomically and reschedule the card. Raises DatabaseError
    on lock contention so callers decide between 409 and a soft fallback."""
    with transaction.atomic():
        # Never let a duplicate browser shortcut or a stuck transaction make
        # the Study page wait indefinitely. PostgreSQL raises quickly, the
        # frontend can retry, and the user sees a real error instead of a hang.
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = %s", ["2500ms"])
                cursor.execute("SET LOCAL statement_timeout = %s", ["15000ms"])

        # Lock the card and schedule in separate queries. The reverse
        # one-to-one relation is represented by a nullable outer join in
        # select_related(). PostgreSQL rejects FOR UPDATE there.
        card = Flashcard.objects.select_for_update().filter(id=card_id, pool__user=user).first()
        if not card:
            return None
        schedule, _ = CardSchedule.objects.select_for_update().get_or_create(card=card)

        profile = profile_for(user)
        rating = automatic_rating(
            accepted=accepted,
            response_ms=response_ms,
            direction=direction,
            judge_score=judge_score,
            profile=profile,
            hint_revealed_letters=hint_revealed_letters,
            hint_total_letters=hint_total_letters,
        )
        previous_state, previous_interval = schedule.state, schedule.interval_days
        if not practice:
            apply_rating(schedule, rating, profile)
        ReviewLog.objects.create(
            user=user, card=card,
            direction=direction,
            answer=answer,
            judge_score=judge_score,
            judge_verdict=judge_verdict,
            feedback=feedback,
            accepted=accepted,
            rating=rating, previous_state=previous_state, new_state=schedule.state,
            previous_interval_days=previous_interval, new_interval_days=schedule.interval_days,
            response_ms=response_ms,
            hint_revealed_letters=hint_revealed_letters,
            hint_total_letters=hint_total_letters,
        )
        return {
            'schedule': {
                'state': schedule.state, 'due_at': schedule.due_at,
                'interval_days': schedule.interval_days,
                'ease_factor': schedule.ease_factor, 'repetitions': schedule.repetitions,
                'lapses': schedule.lapses,
            },
            'practice': practice,
            'automatic_rating': rating,
            'automatic_rating_label': ReviewLog.Rating(rating).label,
        }


class JudgeView(APIView):
    def post(self, request, card_id):
        card = Flashcard.objects.filter(id=card_id, pool__user=request.user).select_related('pool').first()
        if not card:
            return Response({'detail': 'Card not found.'}, status=404)
        answer = str(request.data.get('answer') or '').strip()
        direction = request.data.get('direction', ReviewLog.Direction.TERM_TO_DEFINITION)
        if not answer:
            return Response({'answer': ['This field is required.']}, status=400)
        if direction == ReviewLog.Direction.DEFINITION_TO_TERM:
            strip_infinitive = _is_verb_card(card)
            answer_norm = _recall_key(answer, strip_infinitive=strip_infinitive)
            candidates = {
                _recall_key(value, strip_infinitive=strip_infinitive)
                for value in [card.term, *card.aliases]
            }
            candidates.discard('')
            accepted = answer_norm in candidates
            score = 7 if accepted else 1
            judged = {
                'grading': 'binary',
                'score': score, 'verdict': 'correct' if accepted else 'wrong',
                'feedback': 'Correct.' if accepted else f'The expected answer is “{card.term}”.',
                'matched_concepts': [card.term] if accepted else [],
                'missing_or_wrong_concepts': [] if accepted else [card.term],
                'accepted': accepted, 'should_reveal': not accepted,
            }
        else:
            judged = judge_definition(user=request.user, profile=profile_for(request.user), card=card, answer=answer)
            judged['grading'] = 'ordinal'

        # The backend already has the answer and the verdict, so persist the
        # review in the same request. The frontend keeps a fallback save path
        # in case this soft attempt loses a lock race.
        hint_revealed_letters, hint_total_letters = _parse_hints(request.data)
        try:
            review = _record_review(
                request.user, card.id,
                direction=direction, answer=answer,
                accepted=judged['accepted'], judge_score=judged['score'],
                judge_verdict=judged['verdict'], feedback=judged['feedback'],
                response_ms=_parse_response_ms(request.data.get('response_ms')),
                practice=_parse_bool(request.data.get('practice')),
                hint_revealed_letters=hint_revealed_letters,
                hint_total_letters=hint_total_letters,
            )
        except DatabaseError:
            review = None
        judged['review_recorded'] = review is not None
        judged['review'] = review
        return Response(judged)


class ReviewView(APIView):
    def post(self, request, card_id):
        direction = request.data.get('direction', ReviewLog.Direction.TERM_TO_DEFINITION)
        if direction not in {
            ReviewLog.Direction.TERM_TO_DEFINITION,
            ReviewLog.Direction.DEFINITION_TO_TERM,
        }:
            return Response({'direction': ['Invalid study direction.']}, status=400)
        accepted_value = request.data.get('accepted', False)
        raw_judge_score = request.data.get('judge_score')
        try:
            judge_score = int(raw_judge_score) if raw_judge_score not in (None, '') else None
        except (TypeError, ValueError):
            return Response({'judge_score': ['Use an integer from 1 to 7.']}, status=400)
        if judge_score is not None and not 1 <= judge_score <= 7:
            return Response({'judge_score': ['Use an integer from 1 to 7.']}, status=400)
        hint_revealed_letters, hint_total_letters = _parse_hints(request.data)
        try:
            result = _record_review(
                request.user, card_id,
                direction=direction,
                answer=str(request.data.get('answer') or ''),
                accepted=_parse_bool(accepted_value),
                judge_score=judge_score,
                judge_verdict=str(request.data.get('judge_verdict') or ''),
                feedback=str(request.data.get('feedback') or ''),
                response_ms=_parse_response_ms(request.data.get('response_ms')),
                practice=_parse_bool(request.data.get('practice')),
                hint_revealed_letters=hint_revealed_letters,
                hint_total_letters=hint_total_letters,
            )
        except DatabaseError:
            return Response({
                'detail': 'This card is already being updated by another request. Try again in a moment.',
                'code': 'review_locked',
            }, status=409)
        if result is None:
            return Response({'detail': 'Card not found.'}, status=404)
        return Response(result)


class PronunciationView(APIView):
    def get(self, request):
        text = str(request.query_params.get('text') or '').strip()
        if not text:
            return Response({'text': ['This query parameter is required.']}, status=400)
        try:
            path = generate_pronunciation(text)
        except InvalidEnglishTerm as exc:
            return Response({'text': [str(exc)]}, status=400)
        except PronunciationError as exc:
            return Response({'detail': str(exc), 'code': 'tts_unavailable'}, status=503)
        response = FileResponse(path.open('rb'), content_type='audio/mpeg')
        response['Cache-Control'] = 'private, max-age=31536000, immutable'
        response['Content-Length'] = path.stat().st_size
        return response


class OverviewView(APIView):
    def get(self, request):
        now = timezone.now()
        profile = profile_for(request.user)
        cards = Flashcard.objects.filter(pool__user=request.user, suspended=False)
        schedules = CardSchedule.objects.filter(card__in=cards)
        reviews = ReviewLog.objects.filter(user=request.user)
        current_due = due_breakdown(cards, user=request.user, profile=profile, now=now)
        # Days with at least one review over the last year, for the activity
        # heatmap. Days without reviews are omitted; the frontend fills the grid.
        activity_start = timezone.localdate() - timedelta(days=370)
        activity = [
            {'day': row['day'].isoformat(), 'reviews': row['total']}
            for row in reviews.filter(created_at__date__gte=activity_start)
            .annotate(day=TruncDate('created_at')).values('day')
            .annotate(total=Count('id')).order_by('day')
            if row['day']
        ]
        return Response({
            'total_cards': cards.count(),
            'due_now': current_due.available,
            'new_cards': schedules.filter(state=CardSchedule.State.NEW).count(),
            'reviews_today': reviews.filter(created_at__date=timezone.localdate()).count(),
            'retention': round(100 * reviews.filter(accepted=True).count() / max(1, reviews.count()), 1),
            'streak': _streak(reviews),
            'activity': activity,
        })


def _streak(qs):
    dates = set(qs.values_list('created_at__date', flat=True))
    if not dates:
        return 0
    today = timezone.localdate()
    # A streak remains alive throughout the day after the latest study session.
    # Studying today then immediately extends yesterday's streak by one.
    day = today if today in dates else today - timedelta(days=1)
    if day not in dates:
        return 0
    count = 0
    while day in dates:
        count += 1
        day -= timedelta(days=1)
    return count


class AnalyticsView(APIView):
    def get(self, request):
        qs = LlmUsage.objects.filter(user=request.user)
        pools = Pool.objects.filter(user=request.user, archived=False).order_by('-updated_at')
        pool_id = request.query_params.get('pool')
        if pool_id:
            qs = qs.filter(pool_id=pool_id)
            pools = pools.filter(id=pool_id)
        daily = list(qs.annotate(day=TruncDate('created_at')).values('day').annotate(
            cost=Sum('total_price'), tokens=Sum('total_tokens'), calls=Count('id')
        ).order_by('day'))
        by_pool = []
        for pool in pools:
            aggregate = qs.filter(pool=pool).aggregate(
                cost=Sum('total_price'), tokens=Sum('total_tokens'), calls=Count('id')
            )
            by_pool.append({
                'pool_id': pool.id,
                'pool__name': pool.name,
                'accent': pool.accent,
                'cost': float(aggregate['cost'] or 0),
                'tokens': aggregate['tokens'] or 0,
                'calls': aggregate['calls'] or 0,
            })
        deleted = qs.filter(pool__isnull=True).aggregate(cost=Sum('total_price'), tokens=Sum('total_tokens'), calls=Count('id'))
        if deleted['calls']:
            by_pool.append({
                'pool_id': None, 'pool__name': 'Deleted pools', 'accent': 'muted',
                'cost': float(deleted['cost'] or 0), 'tokens': deleted['tokens'] or 0,
                'calls': deleted['calls'] or 0,
            })
        totals = qs.aggregate(cost=Sum('total_price'), tokens=Sum('total_tokens'), calls=Count('id'))
        failures = list(qs.filter(success=False).values('id', 'operation', 'model', 'error', 'created_at')[:8])
        recent = list(qs[:500])
        avg_latency = sum(x.elapsed_time for x in recent) / max(1, len(recent))

        for row in daily:
            row['cost'] = float(row['cost'] or 0)
            if row.get('day'):
                row['day'] = row['day'].isoformat()
        return Response({
            'daily': daily,
            'by_pool': by_pool,
            'totals': {
                'cost': float(totals['cost'] or 0),
                'tokens': totals['tokens'] or 0,
                'calls': totals['calls'] or 0,
                'average_latency': round(avg_latency, 3),
            },
            'failures': failures,
        })

