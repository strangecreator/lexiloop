from __future__ import annotations

from collections import Counter

from django.db import transaction

from learning.models import BulkGenerationJob, CardSchedule, Flashcard, LlmUsage, Pool, ReviewLog


POOL_ACCENTS = [
    Pool.Accent.EMERALD,
    Pool.Accent.BLUE,
    Pool.Accent.VIOLET,
    Pool.Accent.ROSE,
    Pool.Accent.ORANGE,
    Pool.Accent.TEAL,
    Pool.Accent.INDIGO,
]


def next_pool_accent(user) -> str:
    counts = Counter(Pool.objects.filter(user=user, archived=False).values_list('accent', flat=True))
    return str(min(POOL_ACCENTS, key=lambda color: (counts[str(color)], POOL_ACCENTS.index(color))))


def _copy_schedule(source: CardSchedule, target: CardSchedule) -> None:
    for field in (
        'state', 'due_at', 'interval_days', 'ease_factor', 'step_index',
        'repetitions', 'lapses', 'last_reviewed_at',
    ):
        setattr(target, field, getattr(source, field))
    target.save()


def _merge_schedule(source: CardSchedule, target: CardSchedule) -> None:
    """Keep the more mature progress while retaining the earlier next review."""
    source_score = (source.repetitions, source.interval_days, source.last_reviewed_at or source.created_at)
    target_score = (target.repetitions, target.interval_days, target.last_reviewed_at or target.created_at)
    mature = source if source_score > target_score else target
    for field in ('state', 'interval_days', 'ease_factor', 'step_index', 'repetitions'):
        setattr(target, field, getattr(mature, field))
    target.due_at = min(source.due_at, target.due_at)
    target.lapses = max(source.lapses, target.lapses)
    target.last_reviewed_at = max(filter(None, [source.last_reviewed_at, target.last_reviewed_at]), default=None)
    target.save()


def pool_has_active_job(pool: Pool) -> bool:
    return pool.bulk_generation_jobs.filter(
        status__in=[BulkGenerationJob.Status.QUEUED, BulkGenerationJob.Status.RUNNING]
    ).exists()


@transaction.atomic
def transfer_pool(*, source: Pool, target: Pool, mode: str) -> dict[str, int | str]:
    if source.pk == target.pk:
        raise ValueError('Choose a different target pool.')
    if source.user_id != target.user_id:
        raise ValueError('Pools must belong to the same user.')
    if mode not in {'copy', 'move'}:
        raise ValueError('Mode must be copy or move.')
    if pool_has_active_job(source) or pool_has_active_job(target):
        raise ValueError('Wait for active bulk generation jobs to finish before combining these pools.')

    source = Pool.objects.select_for_update().get(pk=source.pk)
    target = Pool.objects.select_for_update().get(pk=target.pk)
    copied = moved = merged_duplicates = skipped_duplicates = 0

    source_cards = list(source.cards.select_related('schedule').order_by('id'))
    for card in source_cards:
        existing = target.cards.filter(normalized_term=card.normalized_term).select_related('schedule').first()
        if mode == 'copy':
            if existing:
                skipped_duplicates += 1
                continue
            clone = Flashcard.objects.create(
                pool=target,
                term=card.term,
                normalized_term=card.normalized_term,
                part_of_speech=card.part_of_speech,
                ipa=card.ipa,
                short_definition=card.short_definition,
                definition=card.definition,
                examples=card.examples,
                forms=card.forms,
                synonyms=card.synonyms,
                antonyms=card.antonyms,
                collocations=card.collocations,
                usage_notes=card.usage_notes,
                aliases=card.aliases,
                source_payload=card.source_payload,
                suspended=card.suspended,
            )
            _copy_schedule(card.schedule, clone.schedule)
            copied += 1
            continue

        if existing:
            _merge_schedule(card.schedule, existing.schedule)
            ReviewLog.objects.filter(card=card).update(card=existing)
            LlmUsage.objects.filter(card=card).update(card=existing)
            card.delete()
            merged_duplicates += 1
        else:
            card.pool = target
            card.save(update_fields=['pool', 'updated_at'])
            moved += 1

    if mode == 'move':
        # Full merge means historical AI spend follows the destination pool. The
        # destination keeps its name; the source pool is removed.
        LlmUsage.objects.filter(pool=source).update(pool=target)
        source.delete()

    return {
        'mode': mode,
        'target_pool_id': target.id,
        'target_pool_name': target.name,
        'copied': copied,
        'moved': moved,
        'merged_duplicates': merged_duplicates,
        'skipped_duplicates': skipped_duplicates,
    }
