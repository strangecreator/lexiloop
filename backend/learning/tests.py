import asyncio
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from learning.models import BulkGenerationItem, BulkGenerationJob, CardSchedule, Flashcard, LlmUsage, Pool, ReviewLog, UserProfile
from learning.services.bulk import process_bulk_job
from learning.services.llm import _post_hedged
from learning.services.scheduler import apply_rating, automatic_rating
from learning.services.security import decrypt_secret


class ApiBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='solomon', password='strong-pass-123')
        self.profile = UserProfile.objects.create(user=self.user)
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        self.pool = Pool.objects.create(user=self.user, name='English')

    def card(self, term='meticulous'):
        return Flashcard.objects.create(pool=self.pool, term=term, short_definition='Very careful.', definition='Showing great care and precision.')


class ApiTransactionBase(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(username='solomon', password='strong-pass-123')
        self.profile = UserProfile.objects.create(user=self.user)
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        self.pool = Pool.objects.create(user=self.user, name='English')

    def card(self, term='meticulous'):
        return Flashcard.objects.create(pool=self.pool, term=term, short_definition='Very careful.', definition='Showing great care and precision.')


class AuthTests(TestCase):
    def test_register_needs_no_email(self):
        response = self.client.post('/api/auth/register/', {'username': 'newuser', 'password': 'strong-pass-123'}, format='json')
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='newuser')
        self.assertEqual(user.email, '')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(user.profile.theme, UserProfile.Theme.SYSTEM)
        self.assertEqual(user.profile.accent_color, UserProfile.AccentColor.EMERALD)


class PoolAndCardTests(ApiBase):
    def test_pool_isolation(self):
        other = User.objects.create_user('other', password='strong-pass-123')
        foreign = Pool.objects.create(user=other, name='Private')
        response = self.client.get('/api/pools/')
        ids = [x['id'] for x in response.data['results']]
        self.assertIn(self.pool.id, ids)
        self.assertNotIn(foreign.id, ids)

    def test_library_uses_small_server_side_pages(self):
        for index in range(65):
            self.card(f'word{index:03d}')
        first = self.client.get(f'/api/flashcards/?pool={self.pool.id}')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['count'], 65)
        self.assertEqual(len(first.data['results']), 30)
        self.assertIsNotNone(first.data['next'])
        third = self.client.get(f'/api/flashcards/?pool={self.pool.id}&page=3')
        self.assertEqual(len(third.data['results']), 5)
        self.assertIsNone(third.data['next'])

    def test_pool_due_count_respects_remaining_daily_new_limit(self):
        self.profile.daily_new_limit = 20
        self.profile.save(update_fields=['daily_new_limit'])
        for index in range(25):
            self.card(f'newword{index:03d}')
        response = self.client.get('/api/pools/')
        row = next(item for item in response.data['results'] if item['id'] == self.pool.id)
        self.assertEqual(row['due_count'], 20)

        for index in range(5):
            reviewed = self.card(f'reviewed{index:03d}')
            reviewed.schedule.state = CardSchedule.State.REVIEW
            reviewed.schedule.due_at = timezone.now() + timedelta(days=2)
            reviewed.schedule.save()
            ReviewLog.objects.create(
                user=self.user, card=reviewed,
                direction=ReviewLog.Direction.TERM_TO_DEFINITION,
                accepted=True, rating=ReviewLog.Rating.GOOD,
                previous_state=CardSchedule.State.NEW,
                new_state=CardSchedule.State.REVIEW,
            )
        response = self.client.get('/api/pools/')
        row = next(item for item in response.data['results'] if item['id'] == self.pool.id)
        self.assertEqual(row['due_count'], 15)

    def test_manual_rich_card(self):
        payload = {'pool': self.pool.id, 'term': 'break even', 'short_definition': 'Cover costs.', 'definition': 'Have income equal to costs.', 'forms': {'past': 'broke even'}, 'synonyms': ['cover costs'], 'examples': [{'sentence': 'We broke even.', 'note': ''}]}
        response = self.client.post('/api/flashcards/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['forms']['past'], 'broke even')
        self.assertEqual(response.data['schedule']['state'], 'new')

    def test_manual_card_rejects_probable_misspelling(self):
        payload = {
            'pool': self.pool.id,
            'term': 'recieve',
            'short_definition': 'Get something.',
            'definition': 'Get or be given something.',
        }
        response = self.client.post('/api/flashcards/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('receive', str(response.data).lower())

    def test_manual_card_rejects_non_english_alphabet(self):
        payload = {
            'pool': self.pool.id,
            'term': 'привет',
            'short_definition': 'Greeting.',
            'definition': 'A greeting.',
        }
        response = self.client.post('/api/flashcards/', payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_interface_accent_is_persisted(self):
        response = self.client.patch('/api/settings/', {
            'theme': 'system',
            'accent_color': 'teal',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['theme'], 'system')
        self.assertEqual(response.data['accent_color'], 'teal')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.accent_color, UserProfile.AccentColor.TEAL)

    def test_timing_thresholds_are_configurable(self):
        response = self.client.patch('/api/settings/', {
            'term_to_definition_easy_seconds': 10,
            'term_to_definition_good_seconds': 24,
            'definition_to_term_easy_seconds': 4,
            'definition_to_term_good_seconds': 11,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['term_to_definition_easy_seconds'], 10)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.definition_to_term_good_seconds, 11)

    def test_timing_thresholds_require_easy_before_good(self):
        response = self.client.patch('/api/settings/', {
            'term_to_definition_easy_seconds': 40,
            'term_to_definition_good_seconds': 20,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('term_to_definition_good_seconds', response.data)

    def test_models_endpoint_exposes_only_public_curated_models(self):
        response = self.client.get('/api/models/')
        self.assertEqual(response.status_code, 200)
        ids = [item['id'] for item in response.data['models']]
        self.assertIn('external:deepseek-chat', ids)
        self.assertIn('openrouter:openai/gpt-5.2', ids)
        self.assertFalse(any(model_id.startswith('internal:') for model_id in ids))
        self.assertTrue(all(item.get('label') and item.get('provider') for item in response.data['models']))

    def test_settings_reject_hidden_internal_model_names(self):
        response = self.client.patch('/api/settings/', {'generation_model': 'internal:gpt-5.2'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('generation_model', response.data)

    @override_settings(TOKEN_ENCRYPTION_KEY='')
    def test_tokens_are_encrypted_and_not_returned(self):
        response = self.client.patch('/api/settings/', {'provider_tokens': {'deepseek': 'secret-token'}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        stored = self.profile.provider_tokens_encrypted['deepseek']
        self.assertNotIn('secret-token', stored)
        self.assertEqual(decrypt_secret(stored), 'secret-token')
        self.assertNotIn('provider_tokens', response.data)
        # The default generation and judge models are DeepSeek, so both flags flip.
        self.assertTrue(response.data['has_generation_token'])
        self.assertTrue(response.data['has_judge_token'])
        self.assertEqual(response.data['token_status'], {'deepseek': True, 'openai': False, 'openrouter': False, 'xiaomi': False})

    def test_saved_provider_key_survives_model_switch_and_can_be_removed(self):
        self.client.patch('/api/settings/', {'provider_tokens': {'deepseek': 'ds-key', 'openai': 'oa-key'}}, format='json')
        response = self.client.patch('/api/settings/', {'judge_model': 'openai:gpt-5-nano'}, format='json')
        self.assertTrue(response.data['has_judge_token'])
        self.assertTrue(response.data['has_generation_token'])
        response = self.client.patch('/api/settings/', {'judge_model': 'external:deepseek-chat'}, format='json')
        self.assertTrue(response.data['has_judge_token'])
        # An empty value deletes the stored key; other providers stay intact.
        response = self.client.patch('/api/settings/', {'provider_tokens': {'openai': ''}}, format='json')
        self.assertEqual(response.data['token_status'], {'deepseek': True, 'openai': False, 'openrouter': False, 'xiaomi': False})
        self.profile.refresh_from_db()
        self.assertNotIn('openai', self.profile.provider_tokens_encrypted)

    def test_provider_tokens_reject_unknown_provider(self):
        response = self.client.patch('/api/settings/', {'provider_tokens': {'acme': 'key'}}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('provider_tokens', response.data)


class PoolOperationsTests(ApiBase):
    def test_creating_pool_does_not_recolor_existing_pools(self):
        self.pool.accent = Pool.Accent.ROSE
        self.pool.save(update_fields=['accent'])
        response = self.client.post('/api/pools/', {'name': 'Second'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.accent, Pool.Accent.ROSE)
        self.assertNotEqual(response.data['accent'], '')

    def test_copy_pool_copies_cards_and_progress_without_history_or_usage(self):
        target = Pool.objects.create(user=self.user, name='Whole book', accent=Pool.Accent.BLUE)
        card = self.card('aviary')
        card.schedule.state = CardSchedule.State.REVIEW
        card.schedule.interval_days = 19
        card.schedule.repetitions = 4
        card.schedule.save()
        ReviewLog.objects.create(
            user=self.user, card=card, direction=ReviewLog.Direction.TERM_TO_DEFINITION,
            accepted=True, rating=ReviewLog.Rating.GOOD,
            previous_state=CardSchedule.State.NEW, new_state=CardSchedule.State.REVIEW,
        )
        usage = LlmUsage.objects.create(
            user=self.user, pool=self.pool, card=card,
            operation=LlmUsage.Operation.GENERATION, model='test:model', total_price='0.001',
        )
        response = self.client.post(
            f'/api/pools/{self.pool.id}/transfer/',
            {'target_pool': target.id, 'mode': 'copy'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['copied'], 1)
        clone = target.cards.get(normalized_term='aviary')
        self.assertEqual(clone.schedule.state, CardSchedule.State.REVIEW)
        self.assertEqual(clone.schedule.interval_days, 19)
        self.assertTrue(Pool.objects.filter(pk=self.pool.id).exists())
        self.assertEqual(ReviewLog.objects.filter(card=clone).count(), 0)
        usage.refresh_from_db()
        self.assertEqual(usage.pool_id, self.pool.id)
        self.assertEqual(usage.card_id, card.id)

    def test_full_merge_moves_cards_history_and_ai_usage_and_keeps_target_name(self):
        target = Pool.objects.create(user=self.user, name='Whole book', accent=Pool.Accent.BLUE)
        card = self.card('coinage')
        log = ReviewLog.objects.create(
            user=self.user, card=card, direction=ReviewLog.Direction.TERM_TO_DEFINITION,
            accepted=True, rating=ReviewLog.Rating.GOOD,
            previous_state=CardSchedule.State.NEW, new_state=CardSchedule.State.REVIEW,
        )
        usage = LlmUsage.objects.create(
            user=self.user, pool=self.pool, card=card,
            operation=LlmUsage.Operation.GENERATION, model='test:model', total_price='0.001',
        )
        response = self.client.post(
            f'/api/pools/{self.pool.id}/transfer/',
            {'target_pool': target.id, 'mode': 'move'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Pool.objects.filter(pk=self.pool.id).exists())
        target.refresh_from_db()
        self.assertEqual(target.name, 'Whole book')
        card.refresh_from_db(); log.refresh_from_db(); usage.refresh_from_db()
        self.assertEqual(card.pool_id, target.id)
        self.assertEqual(log.card_id, card.id)
        self.assertEqual(usage.pool_id, target.id)
        self.assertEqual(usage.card_id, card.id)

    def test_suspend_removes_card_from_study_and_unsuspend_restores_it(self):
        card = self.card('caucus')
        response = self.client.post(f'/api/flashcards/{card.id}/suspend/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['suspended'])
        next_response = self.client.get(f'/api/study/next/?pool={self.pool.id}')
        self.assertIsNone(next_response.data['card'])
        library = self.client.get(f'/api/flashcards/?pool={self.pool.id}')
        self.assertTrue(library.data['results'][0]['suspended'])
        response = self.client.post(f'/api/flashcards/{card.id}/unsuspend/', {}, format='json')
        self.assertFalse(response.data['suspended'])
        self.assertEqual(self.client.get(f'/api/study/next/?pool={self.pool.id}').data['card']['id'], card.id)


class LlmTests(ApiBase):
    def setUp(self):
        super().setUp()
        from learning.services.security import encrypt_secret
        self.profile.provider_tokens_encrypted = {'deepseek': encrypt_secret('token')}
        self.profile.save()

    @patch('learning.services.llm._post', new_callable=AsyncMock)
    def test_generate_card_from_fenced_json_and_log_cost(self, post):
        post.return_value = {
            'content': '```json\n' + json.dumps({'term':'ubiquitous','normalized_term':'ubiquitous','part_of_speech':'adjective','ipa':'juːˈbɪkwɪtəs','short_definition':'Found everywhere.','definition':'Present everywhere.','examples':[{'sentence':'Phones are ubiquitous.','note':''}],'forms':{},'synonyms':['widespread'],'antonyms':['rare'],'collocations':['ubiquitous presence'],'usage_notes':'formal','aliases':[]}) + '\n```',
            'stats': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_price': 0.0012}, 'elapsed_time': 0.4,
        }
        response = self.client.post('/api/generate/', {'pool': self.pool.id, 'term': 'ubiquitous'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['ipa'], 'juːˈbɪkwɪtəs')
        usage = LlmUsage.objects.get()
        self.assertEqual(usage.total_tokens, 150)
        self.assertEqual(float(usage.total_price), 0.0012)

    @patch('learning.services.llm._post', new_callable=AsyncMock)
    def test_generate_rejects_gibberish_before_provider_call(self, post):
        response = self.client.post('/api/generate/', {'pool': self.pool.id, 'term': 'kakdoeowopeo'}, format='json')
        self.assertEqual(response.status_code, 400)
        post.assert_not_awaited()
        self.assertEqual(LlmUsage.objects.count(), 0)

    @patch('learning.services.llm._post', new_callable=AsyncMock)
    def test_semantic_definition_judge(self, post):
        card = self.card()
        post.return_value = {'content': json.dumps({'score':6,'verdict':'correct','feedback':'Good paraphrase.','matched_concepts':['careful'],'missing_or_wrong_concepts':[]}), 'stats': {'total_price':0}, 'elapsed_time':0.1}
        response = self.client.post(f'/api/study/{card.id}/judge/', {'answer':'being extremely careful with details','direction':'term_to_definition'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['accepted'])
        self.assertEqual(response.data['score'], 6)

    def test_definition_to_term_is_local_and_accepts_alias(self):
        card = self.card('take for granted')
        card.aliases = ['take something for granted']
        card.save()
        response = self.client.post(f'/api/study/{card.id}/judge/', {'answer':'take something for granted','direction':'definition_to_term'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['accepted'])
        self.assertEqual(response.data['grading'], 'binary')
        self.assertEqual(LlmUsage.objects.count(), 0)

    def test_definition_to_term_rejects_typo_instead_of_fuzzy_matching(self):
        card = self.card('receive')
        response = self.client.post(
            f'/api/study/{card.id}/judge/',
            {'answer':'recieve','direction':'definition_to_term'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['accepted'])
        self.assertEqual(response.data['grading'], 'binary')


    def test_definition_to_term_accepts_optional_infinitive_marker(self):
        card = self.card('abolish')
        card.part_of_speech = 'verb'
        card.save()
        response = self.client.post(
            f'/api/study/{card.id}/judge/',
            {'answer': 'to abolish', 'direction': 'definition_to_term'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['accepted'])

        card.term = 'to abolish'
        card.normalized_term = 'to abolish'
        card.save()
        response = self.client.post(
            f'/api/study/{card.id}/judge/',
            {'answer': 'abolish', 'direction': 'definition_to_term'},
            format='json',
        )
        self.assertTrue(response.data['accepted'])


    @override_settings(JUDGE_HEDGE_DELAY_SECONDS=0.01, JUDGE_TOTAL_DEADLINE_SECONDS=1)
    def test_judge_deadline_turns_stalled_provider_into_fast_clean_error(self):
        card = self.card()

        async def stalled_post(*args, **kwargs):
            await asyncio.sleep(30)

        with patch('learning.services.llm._post', side_effect=stalled_post):
            response = self.client.post(
                f'/api/study/{card.id}/judge/',
                {'answer': 'being careful', 'direction': 'term_to_definition'},
                format='json',
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn('did not answer within 1 seconds', response.data['detail'])
        usage = LlmUsage.objects.get()
        self.assertFalse(usage.success)
        self.assertIn('did not answer', usage.error)

    @override_settings(JUDGE_HEDGE_DELAY_SECONDS=0.01, JUDGE_TOTAL_DEADLINE_SECONDS=5)
    def test_judge_provider_timeouts_surface_readable_message(self):
        card = self.card()

        async def failing_post(*args, **kwargs):
            raise TimeoutError('provider read timeout')

        with patch('learning.services.llm._post', side_effect=failing_post):
            response = self.client.post(
                f'/api/study/{card.id}/judge/',
                {'answer': 'being careful', 'direction': 'term_to_definition'},
                format='json',
            )
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('AttemptsExceeded', response.data['detail'])
        self.assertIn('did not answer', response.data['detail'])

    @override_settings(JUDGE_HEDGE_DELAY_SECONDS=0.01, JUDGE_TOTAL_DEADLINE_SECONDS=5)
    def test_judge_provider_errors_keep_original_cause_not_attempts_exceeded(self):
        card = self.card()

        async def failing_post(*args, **kwargs):
            raise RuntimeError('DeepSeek returned 503')

        with patch('learning.services.llm._post', side_effect=failing_post):
            response = self.client.post(
                f'/api/study/{card.id}/judge/',
                {'answer': 'being careful', 'direction': 'term_to_definition'},
                format='json',
            )
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('AttemptsExceeded', response.data['detail'])
        self.assertIn('DeepSeek returned 503', response.data['detail'])

    @override_settings(JUDGE_HEDGE_DELAY_SECONDS=0.01)
    def test_hedged_judge_starts_backup_and_returns_first_success(self):
        calls = 0

        async def fake_post(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.sleep(0.08)
                return {'content': 'primary'}
            await asyncio.sleep(0.002)
            return {'content': 'backup'}

        with patch('learning.services.llm._post', side_effect=fake_post) as post:
            result = asyncio.run(_post_hedged('model', 'token', []))
        self.assertEqual(result['content'], 'backup')
        self.assertEqual(post.await_count, 2)


class SchedulerTests(ApiBase):
    def test_automatic_rating_combines_correctness_and_time(self):
        self.assertEqual(automatic_rating(accepted=False, response_ms=1000, direction='definition_to_term'), 1)
        self.assertEqual(automatic_rating(accepted=True, response_ms=3000, direction='definition_to_term'), 4)
        self.assertEqual(automatic_rating(accepted=True, response_ms=30000, direction='definition_to_term'), 2)
        self.assertEqual(automatic_rating(accepted=True, response_ms=5000, direction='term_to_definition', judge_score=6), 3)
        self.assertEqual(automatic_rating(accepted=True, response_ms=5000, direction='term_to_definition', judge_score=5), 2)

    def test_automatic_rating_uses_profile_thresholds_and_strict_boundaries(self):
        self.profile.term_to_definition_easy_seconds = 10
        self.profile.term_to_definition_good_seconds = 20
        self.assertEqual(automatic_rating(accepted=True, response_ms=9999, direction='term_to_definition', profile=self.profile), 4)
        self.assertEqual(automatic_rating(accepted=True, response_ms=10000, direction='term_to_definition', profile=self.profile), 3)
        self.assertEqual(automatic_rating(accepted=True, response_ms=20000, direction='term_to_definition', profile=self.profile), 2)

    def test_review_endpoint_selects_rating_automatically(self):
        card = self.card()
        response = self.client.post(
            f'/api/study/{card.id}/review/',
            {'direction':'definition_to_term','answer':'meticulous','accepted':True,'response_ms':3000},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['automatic_rating'], 4)
        self.assertEqual(ReviewLog.objects.get().rating, 4)

    def test_letter_hints_cap_or_reset_definition_to_word_rating(self):
        args = {'accepted': True, 'response_ms': 1000, 'direction': ReviewLog.Direction.DEFINITION_TO_TERM}
        self.assertEqual(automatic_rating(**args, hint_revealed_letters=0, hint_total_letters=10), ReviewLog.Rating.EASY)
        self.assertEqual(automatic_rating(**args, hint_revealed_letters=1, hint_total_letters=10), ReviewLog.Rating.GOOD)
        self.assertEqual(automatic_rating(**args, hint_revealed_letters=3, hint_total_letters=10), ReviewLog.Rating.HARD)
        self.assertEqual(automatic_rating(**args, hint_revealed_letters=5, hint_total_letters=10), ReviewLog.Rating.AGAIN)

    def test_review_endpoint_accepts_blank_judge_score_as_none(self):
        card = self.card('meticulous')
        response = self.client.post(
            f'/api/study/{card.id}/review/',
            {
                'direction': ReviewLog.Direction.TERM_TO_DEFINITION,
                'answer': 'very careful', 'accepted': False, 'response_ms': 1500,
                'judge_score': '',
            }, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(ReviewLog.objects.get().judge_score)

    def test_review_endpoint_records_hint_usage(self):
        card = self.card('meticulous')
        response = self.client.post(
            f'/api/study/{card.id}/review/',
            {
                'direction': ReviewLog.Direction.DEFINITION_TO_TERM,
                'answer': 'meticulous', 'accepted': True, 'response_ms': 1000,
                'hint_revealed_letters': 5, 'hint_total_letters': 10,
            }, format='json',
        )
        self.assertEqual(response.data['automatic_rating'], ReviewLog.Rating.AGAIN)
        log = ReviewLog.objects.get()
        self.assertEqual(log.hint_revealed_letters, 5)
        self.assertEqual(log.hint_total_letters, 10)

    def test_new_card_moves_to_learning_then_review(self):
        card = self.card()
        schedule = card.schedule
        apply_rating(schedule, 1, self.profile)
        self.assertEqual(schedule.state, CardSchedule.State.LEARNING)
        apply_rating(schedule, 4, self.profile)
        self.assertEqual(schedule.state, CardSchedule.State.REVIEW)
        self.assertGreater(schedule.interval_days, 0)

    def test_lapse_moves_review_card_to_relearning(self):
        card = self.card()
        schedule = card.schedule
        schedule.state = CardSchedule.State.REVIEW
        schedule.interval_days = 20
        schedule.save()
        apply_rating(schedule, 1, self.profile)
        self.assertEqual(schedule.state, CardSchedule.State.RELEARNING)
        self.assertEqual(schedule.lapses, 1)

    def test_review_endpoint_writes_history(self):
        card = self.card()
        response = self.client.post(f'/api/study/{card.id}/review/', {'rating':3,'direction':'term_to_definition','answer':'careful','accepted':True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ReviewLog.objects.count(), 1)
        card.schedule.refresh_from_db()
        self.assertEqual(card.schedule.repetitions, 1)

    def test_next_card_prioritizes_overdue_learning(self):
        review = self.card('review')
        learning = self.card('learning')
        review.schedule.state = CardSchedule.State.REVIEW; review.schedule.due_at = timezone.now()-timedelta(days=5); review.schedule.save()
        learning.schedule.state = CardSchedule.State.LEARNING; learning.schedule.due_at = timezone.now()-timedelta(minutes=1); learning.schedule.save()
        response = self.client.get(f'/api/study/next/?pool={self.pool.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['card']['id'], learning.id)

    def test_overview_due_count_matches_actual_global_queue(self):
        second = Pool.objects.create(user=self.user, name='Second')
        self.profile.daily_new_limit = 7
        self.profile.save(update_fields=['daily_new_limit'])
        for index in range(12):
            Flashcard.objects.create(pool=self.pool if index % 2 else second, term=f'queueword{index:03d}', short_definition='A word.', definition='A test word.')
        response = self.client.get('/api/overview/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['due_now'], 7)
        next_response = self.client.get('/api/study/next/')
        self.assertEqual(next_response.data['queue_count'], 7)

    def test_overview_activity_aggregates_reviews_per_day(self):
        card = self.card()
        now = timezone.now()
        for days_ago, count in ((0, 2), (3, 1), (500, 4)):
            for _ in range(count):
                log = ReviewLog.objects.create(
                    user=self.user, card=card, direction='term_to_definition',
                    accepted=True, rating=3, previous_state='new', new_state='learning',
                )
                ReviewLog.objects.filter(pk=log.pk).update(created_at=now - timedelta(days=days_ago))
        response = self.client.get('/api/overview/')
        self.assertEqual(response.status_code, 200)
        activity = {row['day']: row['reviews'] for row in response.data['activity']}
        today = timezone.localdate().isoformat()
        self.assertEqual(activity[today], 2)
        self.assertEqual(activity[(timezone.localdate() - timedelta(days=3)).isoformat()], 1)
        # Days beyond the one-year window and empty days are omitted.
        self.assertEqual(len(activity), 2)

    def test_daily_new_limit_hides_new_cards(self):
        card = self.card()
        self.profile.daily_new_limit = 0; self.profile.save()
        response = self.client.get(f'/api/study/next/?pool={self.pool.id}')
        self.assertIsNone(response.data['card'])

    def test_practice_mode_returns_not_due_card(self):
        card = self.card()
        card.schedule.state = CardSchedule.State.REVIEW
        card.schedule.due_at = timezone.now() + timedelta(days=30)
        card.schedule.save()
        due_response = self.client.get(f'/api/study/next/?pool={self.pool.id}&mode=due')
        self.assertIsNone(due_response.data['card'])
        practice_response = self.client.get(f'/api/study/next/?pool={self.pool.id}&mode=practice')
        self.assertEqual(practice_response.data['card']['id'], card.id)

    def test_practice_review_does_not_change_schedule(self):
        card = self.card()
        card.schedule.state = CardSchedule.State.REVIEW
        card.schedule.interval_days = 12
        card.schedule.due_at = timezone.now() + timedelta(days=12)
        card.schedule.save()
        previous_due = card.schedule.due_at
        response = self.client.post(
            f'/api/study/{card.id}/review/',
            {'rating':1,'direction':'term_to_definition','answer':'careful','accepted':True,'practice':True},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        card.schedule.refresh_from_db()
        self.assertEqual(card.schedule.state, CardSchedule.State.REVIEW)
        self.assertEqual(card.schedule.interval_days, 12)
        self.assertEqual(card.schedule.due_at, previous_due)
        self.assertEqual(card.schedule.repetitions, 0)


class PronunciationTests(ApiBase):
    @patch('learning.views.generate_pronunciation')
    def test_pronunciation_returns_mp3(self, generate):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.mp3'
            path.write_bytes(b'ID3' + b'x' * 600)
            generate.return_value = path
            response = self.client.get('/api/pronunciation/?text=meticulous')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'audio/mpeg')


class BulkNormalizationTests(ApiBase):
    SAMPLE = """to abolish (v)
abortion (n)
absence (n)
absurd (adj)
abuse (n) / to abuse (v)
academy (n)
to accelerate (v)
adolescent (n / adj)
advocate (n) / to advocate (v)
to alert (v) / alert (n / adj)
to align (v)
to allocate (v)"""

    def test_normalization_stage_strips_metadata_and_deduplicates(self):
        response = self.client.post('/api/generate/normalize/', {'terms': self.SAMPLE}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['errors'], [])
        self.assertEqual(response.data['normalized'], [
            'abolish', 'abortion', 'absence', 'absurd', 'abuse', 'academy',
            'accelerate', 'adolescent', 'advocate', 'alert', 'align', 'allocate',
        ])
        self.assertFalse(any('(' in term or term.startswith('to ') for term in response.data['normalized']))
        self.assertGreaterEqual(
            sum(change['status'] == 'duplicate' for change in response.data['changes']),
            3,
        )


class DurableBulkGenerationTests(ApiTransactionBase):
    def setUp(self):
        super().setUp()
        from learning.services.security import encrypt_secret
        self.profile.provider_tokens_encrypted = {'deepseek': encrypt_secret('token')}
        self.profile.save(update_fields=['provider_tokens_encrypted'])

    def test_bulk_api_returns_queued_job_without_waiting_for_generation(self):
        response = self.client.post('/api/generate/bulk/', {
            'pool': self.pool.id,
            'terms': ['meticulous', 'ubiquitous'],
            'batch_size': 200,
        }, format='json')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], BulkGenerationJob.Status.QUEUED)
        self.assertEqual(response.data['total_count'], 2)
        self.assertEqual(Flashcard.objects.count(), 0)

    @override_settings(BULK_TARGET_SUCCESS_RATIO=0.99)
    def test_worker_saves_success_immediately_and_logs_structured_timeout_failure(self):
        response = self.client.post('/api/generate/bulk/', {
            'pool': self.pool.id,
            'terms': ['meticulous', 'ubiquitous'],
            'batch_size': 2,
        }, format='json')
        job = BulkGenerationJob.objects.get(pk=response.data['id'])
        job.max_rounds = 1
        job.save(update_fields=['max_rounds'])
        payload = {
            'term': 'meticulous', 'normalized_term': 'meticulous',
            'part_of_speech': 'adjective', 'ipa': 'məˈtɪkjələs',
            'short_definition': 'Very careful and precise.',
            'definition': 'Showing great attention to detail.',
            'examples': [{'sentence': 'She kept meticulous notes.', 'note': ''}],
            'forms': {}, 'synonyms': ['careful'], 'antonyms': ['careless'],
            'collocations': ['meticulous planning'], 'usage_notes': '', 'aliases': [],
        }

        async def fake_batch(**kwargs):
            path = Path(kwargs['save_to_file'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({'index': 0, 'content': json.dumps(payload), 'stats': {'total_price': 0}, 'elapsed_time': 0.2}) + '\n' +
                json.dumps({'index': 1, '__error__': 'Gateway timed out', '__error_type__': 'TimeoutError', '__traceback__': 'TimeoutError: Gateway timed out'}) + '\n',
                encoding='utf-8',
            )
            return {'count': 1, 'indices': [0], 'results': [], 'elapsed_time': 0.2, 'total_price': 0}

        with patch('learning.services.bulk.router.llm.post_batch', new_callable=AsyncMock) as batch:
            batch.side_effect = fake_batch
            process_bulk_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, BulkGenerationJob.Status.COMPLETED_WITH_ERRORS, job.error)
        self.assertEqual(job.created_count, 1)
        self.assertEqual(job.failed_count, 1)
        self.assertTrue(self.pool.cards.filter(normalized_term='meticulous').exists())
        failed = job.items.get(term='ubiquitous')
        self.assertIn('TimeoutError', failed.error)
        self.assertTrue(LlmUsage.objects.filter(success=False, error__icontains='Gateway timed out').exists())
        analytics = self.client.get('/api/analytics/')
        self.assertTrue(any('Gateway timed out' in row['error'] for row in analytics.data['failures']))

    @override_settings(BULK_TARGET_SUCCESS_RATIO=0.99, BULK_MAX_ROUNDS=3)
    def test_worker_retries_only_failed_terms_until_convergence(self):
        response = self.client.post('/api/generate/bulk/', {
            'pool': self.pool.id,
            'terms': ['meticulous', 'ubiquitous'],
            'batch_size': 2,
        }, format='json')
        job = BulkGenerationJob.objects.get(pk=response.data['id'])
        payload = {
            'term': 'placeholder', 'normalized_term': 'placeholder',
            'part_of_speech': 'adjective', 'ipa': '',
            'short_definition': 'A valid concise definition.',
            'definition': 'A complete valid definition for the requested English term.',
            'examples': [{'sentence': 'This is a valid example.', 'note': ''}],
            'forms': {}, 'synonyms': [], 'antonyms': [],
            'collocations': [], 'usage_notes': '', 'aliases': [],
        }
        calls = []

        async def fake_batch(**kwargs):
            calls.append(kwargs)
            path = Path(kwargs['save_to_file'])
            path.parent.mkdir(parents=True, exist_ok=True)
            if len(calls) == 1:
                rows = [
                    {'index': 0, 'content': json.dumps(payload), 'stats': {'total_price': 0}, 'elapsed_time': 0.1},
                    {'index': 1, '__error__': 'temporary gateway failure', '__error_type__': 'TimeoutError'},
                ]
            else:
                # The second round must contain only the failed term, so its new
                # round-local index is zero.
                self.assertEqual(len(kwargs['args_list']), 1)
                rows = [{'index': 0, 'content': json.dumps(payload), 'stats': {'total_price': 0}, 'elapsed_time': 0.1}]
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            return {'count': 1, 'indices': [0], 'results': [], 'elapsed_time': 0.1, 'total_price': 0}

        with patch('learning.services.bulk.router.llm.post_batch', new_callable=AsyncMock) as batch:
            batch.side_effect = fake_batch
            process_bulk_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, BulkGenerationJob.Status.COMPLETED)
        self.assertEqual(job.created_count, 2)
        self.assertEqual(job.failed_count, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0]['save_errors_to_file'])
        self.assertTrue(calls[0]['only_new'])
        self.assertTrue(calls[0]['skip_on_error'])
        attempts = dict(job.items.values_list('term', 'attempts'))
        self.assertEqual(attempts['meticulous'], 1)
        self.assertEqual(attempts['ubiquitous'], 2)

    def test_cancel_marks_unresolved_terms_as_failed_for_final_report(self):
        response = self.client.post('/api/generate/bulk/', {
            'pool': self.pool.id, 'terms': ['meticulous', 'ubiquitous'],
        }, format='json')
        job_id = response.data['id']
        cancelled = self.client.post(f'/api/generate/bulk/jobs/{job_id}/cancel/', {}, format='json')
        self.assertEqual(cancelled.data['status'], BulkGenerationJob.Status.CANCELLED)
        self.assertEqual(cancelled.data['processed_count'], 2)
        self.assertEqual(len(cancelled.data['failed_terms']), 2)


class AnalyticsTests(ApiBase):
    def test_recent_failures_includes_timeout_and_gateway_errors(self):
        LlmUsage.objects.create(
            user=self.user, pool=self.pool, operation=LlmUsage.Operation.BULK_GENERATION,
            model='test:model', success=False, error='TimeoutError: Gateway timed out',
        )
        response = self.client.get('/api/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['failures']), 1)
        self.assertIn('Gateway timed out', response.data['failures'][0]['error'])

    def test_by_pool_includes_zero_usage_pools(self):
        second = Pool.objects.create(user=self.user, name='Second pool')
        LlmUsage.objects.create(
            user=self.user, pool=self.pool, operation=LlmUsage.Operation.GENERATION,
            model='test:model', total_price='0.001', success=True,
        )
        response = self.client.get('/api/analytics/')
        self.assertEqual(response.status_code, 200)
        rows = {row['pool_id']: row for row in response.data['by_pool']}
        self.assertEqual(set(rows), {self.pool.id, second.id})
        self.assertEqual(rows[second.id]['calls'], 0)
        self.assertEqual(rows[second.id]['cost'], 0.0)

class OverviewAndRoundProgressTests(ApiBase):
    def review_on(self, day, term):
        card = self.card(term)
        log = ReviewLog.objects.create(
            user=self.user, card=card,
            direction=ReviewLog.Direction.TERM_TO_DEFINITION,
            answer='answer', accepted=True, rating=ReviewLog.Rating.GOOD,
            previous_state=CardSchedule.State.NEW,
            new_state=CardSchedule.State.REVIEW,
        )
        dt = timezone.make_aware(datetime.combine(day, time(12, 0)))
        ReviewLog.objects.filter(pk=log.pk).update(created_at=dt)
        return log

    def test_streak_stays_alive_when_latest_review_was_yesterday(self):
        today = timezone.localdate()
        self.review_on(today - timedelta(days=1), 'yesterday')
        response = self.client.get('/api/overview/')
        self.assertEqual(response.data['streak'], 1)

    def test_studying_today_extends_yesterdays_streak_immediately(self):
        today = timezone.localdate()
        self.review_on(today - timedelta(days=1), 'yesterday')
        self.review_on(today, 'today')
        response = self.client.get('/api/overview/')
        self.assertEqual(response.data['streak'], 2)

    def test_due_queue_reports_real_round_size(self):
        self.card('first')
        self.card('second')
        response = self.client.get(f'/api/study/next/?pool={self.pool.id}&mode=due')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['queue_count'], 2)

    def test_practice_queue_reports_completed_and_total(self):
        first = self.card('first')
        self.card('second')
        response = self.client.get(f'/api/study/next/?pool={self.pool.id}&mode=practice&exclude={first.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['round_total'], 2)
        self.assertEqual(response.data['round_completed'], 1)
        self.assertEqual(response.data['queue_count'], 1)
