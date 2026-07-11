from __future__ import annotations

import asyncio
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

import router
import tools
from django.conf import settings

from learning.exceptions import LlmConfigurationError, LlmResponseError
from learning.models import Flashcard, LlmUsage, Pool, UserProfile
from learning.services.english import InvalidEnglishTerm, validate_english_term
from learning.services.model_catalog import MODEL_IDS, TOKEN_PROVIDERS, token_provider_for
from learning.services.security import decrypt_secret

GENERATION_SYSTEM_PROMPT = '''You create precise English-learning flashcards for advanced learners.
Return exactly one JSON object and no prose or Markdown. Be concise but pedagogically useful.
Use standard British or American IPA and do not invent rare senses unless the term strongly implies them.
The input has already passed an English spelling check. Never invent a meaning for gibberish, a misspelling,
an identifier, or a non-English expression. Preserve the supplied spelling and explain its standard English sense.
For a collocation or phrase, explain it as a unit. Schema:
{
  "term": "string",
  "normalized_term": "lowercase canonical spelling",
  "part_of_speech": "string",
  "ipa": "string without surrounding slashes",
  "short_definition": "one plain-English sentence, max 180 chars",
  "definition": "clear complete English definition",
  "examples": [{"sentence": "natural sentence", "note": "brief usage note"}],
  "forms": {"key": "value"},
  "synonyms": ["string"],
  "antonyms": ["string"],
  "collocations": ["string"],
  "usage_notes": "register, grammar, pitfalls or empty string",
  "aliases": ["acceptable alternate answer"]
}
Provide 2-3 examples. Every example sentence must contain the exact term or one of the listed forms so the study UI can mask it as a blank. Keep arrays short. All fields are required.'''

JUDGE_SYSTEM_PROMPT = '''You are a strict but fair semantic judge for an English vocabulary trainer.
Evaluate whether the learner's free-form definition demonstrates understanding of the target sense.
Grade the MEANING, not the wording: a learner's answer never has to resemble the canonical definition — a casual, short, or clumsy phrasing that pins down the same meaning is a top answer.
Ignore grammar, spelling and style unless they change meaning. Accept paraphrases, examples-with-explanations, and translations of the idea into plain words. Penalize circular definitions, bare examples that carry no meaning, wrong polarity, and definitions that fit only a different sense of the word.
Return exactly one JSON object and no Markdown:
{
  "score": 1,
  "verdict": "wrong|mostly_wrong|partial|half_right|mostly_correct|correct|perfect",
  "feedback": "one or two direct sentences for the learner",
  "matched_concepts": ["string"],
  "missing_or_wrong_concepts": ["string"]
}
Score scale — you MUST use the entire scale; 4 and 7 are ordinary grades that real answers earn every day, not reserved extremes:
1 = confidently wrong or contradictory
2 = mostly wrong; only a small relevant fragment
3 = partial understanding: one real element of the meaning is present, but a major concept is missing or wrong
4 = half right: the core idea is recognizable, but an important aspect is missing, too vague, or slightly off
5 = mostly correct: the full core meaning with a minor omission or imprecision
6 = correct: an accurate paraphrase of the whole meaning; small cosmetic flaws at most
7 = fully correct and precise: the complete meaning including its nuance, with nothing missing and nothing wrong
Calibration rules:
- If an answer captures the complete meaning exactly, give 7 even when it is short, informal, or worded nothing like the canonical definition.
- If you find yourself deciding between 3 and 5, the answer is a 4 — use it; do not round away from the middle.
- Reserve 6 for answers with a genuine (if tiny) cosmetic gap; do not use 6 as a ceiling for great answers.
Do not use probabilities or decimal scores.'''

SENTENCE_JUDGE_SYSTEM_PROMPT = '''You are a strict but fair usage judge for an English vocabulary trainer.
The learner was shown a word or phrase and asked to write ONE original sentence using it. Decide whether the sentence proves the learner understands the target word's meaning and can use it correctly.
Judge these aspects, in order of importance:
1. Meaning: the target word must be used in its actual sense. A sentence that would only make sense if the word meant something else is wrong.
2. Demonstration: the context should show the meaning. "It was ubiquitous." proves nothing; "Smartphones are so ubiquitous that even remote villages have them." demonstrates understanding.
3. Grammar of the target word: correct part of speech, correct form (any inflection of the word counts as using it), and its typical patterns and collocations (e.g. "interested IN", "make a decision").
4. General grammar and naturalness matter only where they obscure or distort the meaning. Ignore typos, capitalization, and punctuation slips that leave the meaning intact.
Never penalize: simple vocabulary elsewhere in the sentence, short sentences that still demonstrate the meaning, regional spelling, or a missing final period. Never reward length or fancy words by themselves.
If the sentence does not contain the target word or an inflected form of it, the score is 1.
Return exactly one JSON object and no Markdown:
{
  "score": 1,
  "verdict": "wrong|mostly_wrong|partial|half_right|mostly_correct|correct|perfect",
  "feedback": "one or two direct sentences for the learner; when the usage is flawed, include a corrected version of their sentence",
  "matched_concepts": ["string"],
  "missing_or_wrong_concepts": ["string"]
}
Score scale — you MUST use the entire scale; 4 and 7 are ordinary grades, not reserved extremes:
1 = the target word is absent, or used with a completely wrong meaning
2 = mostly wrong: the usage clearly points at a different meaning, with only a faint connection to the real sense
3 = partially right: the sense is related but noticeably off, or the sentence is too broken to demonstrate it
4 = half right: the meaning could fit, but the sentence is so generic it does not demonstrate understanding, or one significant usage error remains (wrong part of speech, broken collocation)
5 = mostly correct: the right meaning with slightly unnatural phrasing or a small grammatical slip around the target word
6 = correct: the word is used accurately and naturally; at most cosmetic imperfections elsewhere in the sentence
7 = flawless: accurate, natural, and the context clearly demonstrates the meaning — a sentence a careful native speaker could write. Award 7 whenever these hold; it does not require rare words or complex structure.
Do not use probabilities or decimal scores.'''


def image_model_for(profile: UserProfile) -> str:
    return profile.image_model or profile.generation_model


IMAGE_SYSTEM_PROMPT = '''You help a vocabulary app attach an illustrative image to a flashcard.
You receive the flashcard (term, part of speech, definition), the link the user pasted, a short context line, and candidate images (URL plus a title when known).
Pick the single candidate that best illustrates the term in the given sense. When the candidates come from one web page, prefer that page's main, full-size image; when they come from an image search, prefer the most relevant, highest-quality photograph. Avoid logos, icons, avatars, UI sprites, tracking pixels, and small thumbnails when a larger variant of the same image exists.
If no candidate fits but the pasted link itself embeds a recognizable direct image URL (for example in a query parameter), return that.
A wrong or irrelevant picture is worse than none: when nothing genuinely fits, return null.
Return exactly one JSON object and no Markdown: {"image_url": "https://direct-image-url" or null, "reason": "one short sentence"}'''

IMAGE_QUERY_SYSTEM_PROMPT = '''You write image-search queries for an English vocabulary flashcard app.
Given a flashcard (term, part of speech, definition) and the user's original search text, produce one concise English query (2–5 words) that will find a clear illustrative photograph of the term in that sense. Prefer concrete, photographable subjects; for an abstract term, describe a simple scene that evokes its meaning. Never include meta words like "noun", "image", or "photo".
Return exactly one JSON object and no Markdown: {"query": "..."}'''


def craft_image_query(*, user, profile: UserProfile, card: Flashcard, search_text: str) -> str:
    """Turn the card's sense plus the user's search text into a retrieval query."""
    model = image_model_for(profile)
    token = _token(profile, LlmUsage.Operation.IMAGE)
    payload = {'term': card.term, 'part_of_speech': card.part_of_speech,
               'short_definition': card.short_definition, 'user_search_text': search_text}
    messages = [
        {'role': 'system', 'content': IMAGE_QUERY_SYSTEM_PROMPT},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        result = asyncio.run(_deadline(_post(model, token, messages, attempts=1), settings.IMAGE_TOTAL_DEADLINE_SECONDS, 'image lookup'))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The model response has no textual content.')
        query = _parse_object(content).get('query')
        if not isinstance(query, str) or not query.strip():
            raise LlmResponseError('The model did not produce a search query.')
        log_usage(user=user, pool=card.pool, card=card, operation=LlmUsage.Operation.IMAGE, model=model, result=result)
        return query.strip()[:120]
    except Exception as exc:
        log_usage(user=user, pool=card.pool, card=card, operation=LlmUsage.Operation.IMAGE, model=model, error=str(exc))
        _public_error(exc)


def resolve_image_url(*, user, profile: UserProfile, card: Flashcard, page_url: str, title: str, candidates: list) -> str:
    """Ask the image-assistant model which candidate URL is the picture to use."""
    model = image_model_for(profile)
    token = _token(profile, LlmUsage.Operation.IMAGE)
    normalized = [candidate if isinstance(candidate, dict) else {'url': candidate} for candidate in candidates]
    payload = {'term': card.term, 'part_of_speech': card.part_of_speech, 'short_definition': card.short_definition,
               'pasted_link': page_url, 'context': title, 'candidates': normalized}
    messages = [
        {'role': 'system', 'content': IMAGE_SYSTEM_PROMPT},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        result = asyncio.run(_deadline(_post(model, token, messages, attempts=1), settings.IMAGE_TOTAL_DEADLINE_SECONDS, 'image lookup'))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The model response has no textual content.')
        found = _parse_object(content).get('image_url')
        if not isinstance(found, str) or not found.startswith(('http://', 'https://')):
            raise LlmResponseError('The model could not find a usable image on that page.')
        log_usage(user=user, pool=card.pool, card=card, operation=LlmUsage.Operation.IMAGE, model=model, result=result)
        return found
    except Exception as exc:
        log_usage(user=user, pool=card.pool, card=card, operation=LlmUsage.Operation.IMAGE, model=model, error=str(exc))
        _public_error(exc)


def sentence_judge_model_for(profile: UserProfile) -> str:
    return profile.sentence_judge_model or profile.judge_model


def _token(profile: UserProfile, operation: str) -> str | None:
    if operation == LlmUsage.Operation.JUDGING:
        model = profile.judge_model
    elif operation == LlmUsage.Operation.SENTENCE_JUDGING:
        model = sentence_judge_model_for(profile)
    elif operation == LlmUsage.Operation.IMAGE:
        model = image_model_for(profile)
    else:
        model = profile.generation_model
    provider = token_provider_for(model)
    encrypted = (profile.provider_tokens_encrypted or {}).get(provider, '')
    token = decrypt_secret(encrypted)
    if not token and not settings.ALLOW_SERVER_LLM_TOKENS:
        label = TOKEN_PROVIDERS.get(provider, provider or 'provider')
        raise LlmConfigurationError(f'No {label} API key is saved. Open Settings and add one.')
    return token or None


def _find_stat(stats: dict[str, Any], names: tuple[str, ...]) -> int:
    for name in names:
        value = stats.get(name)
        if isinstance(value, (int, float)):
            return max(0, int(value))
    for value in stats.values():
        if isinstance(value, dict):
            found = _find_stat(value, names)
            if found:
                return found
    return 0


def _price(stats: dict[str, Any]) -> Decimal:
    try:
        value = Decimal(str(stats.get('total_price', 0)))
        return value if value.is_finite() and value >= 0 else Decimal('0')
    except (InvalidOperation, TypeError):
        return Decimal('0')


def log_usage(*, user, pool, card, operation, model, result=None, error='') -> LlmUsage:
    result = result or {}
    stats = result.get('stats') if isinstance(result.get('stats'), dict) else {}
    input_tokens = _find_stat(stats, ('prompt_tokens', 'input_tokens', 'prompt_token_count'))
    output_tokens = _find_stat(stats, ('completion_tokens', 'output_tokens', 'completion_token_count'))
    total_tokens = _find_stat(stats, ('total_tokens', 'tokens')) or input_tokens + output_tokens
    elapsed = result.get('elapsed_time', 0)
    elapsed = float(elapsed) if isinstance(elapsed, (int, float)) and math.isfinite(float(elapsed)) else 0
    return LlmUsage.objects.create(
        user=user, pool=pool, card=card, operation=operation, model=model,
        input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
        total_price=_price(stats), elapsed_time=elapsed, success=not bool(error),
        error=str(error)[:4000], stats=stats,
    )


def _parse_object(content: str) -> dict[str, Any]:
    parsed = tools.parse_json_from_string(content)
    if not isinstance(parsed, dict):
        raise LlmResponseError('The model did not return a JSON object.')
    return parsed


def _public_error(exc: Exception):
    if isinstance(exc, (LlmConfigurationError, LlmResponseError)):
        raise exc
    detail = str(exc).strip()
    detail = f': {detail[:500]}' if detail else ''
    raise LlmResponseError(f'The model request failed ({type(exc).__name__}){detail}') from exc


def _validate_generation(data: dict[str, Any], requested_term: str) -> dict[str, Any]:
    try:
        validated_requested = validate_english_term(requested_term)
    except InvalidEnglishTerm as exc:
        raise LlmResponseError(str(exc)) from exc
    for key in ('definition', 'short_definition'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise LlmResponseError(f"Generated flashcard is missing a valid '{key}' field.")
    out = {
        # The user's prevalidated spelling is authoritative. This prevents a model
        # from silently replacing it or manufacturing a card for an unknown token.
        'term': validated_requested.normalized,
        'normalized_term': validated_requested.normalized.casefold(),
        'part_of_speech': str(data.get('part_of_speech') or '').strip(),
        'ipa': str(data.get('ipa') or '').strip().strip('/'),
        'short_definition': data['short_definition'].strip()[:500],
        'definition': data['definition'].strip(),
        'examples': data.get('examples') if isinstance(data.get('examples'), list) else [],
        'forms': data.get('forms') if isinstance(data.get('forms'), dict) else {},
        'synonyms': data.get('synonyms') if isinstance(data.get('synonyms'), list) else [],
        'antonyms': data.get('antonyms') if isinstance(data.get('antonyms'), list) else [],
        'collocations': data.get('collocations') if isinstance(data.get('collocations'), list) else [],
        'usage_notes': str(data.get('usage_notes') or '').strip(),
        'aliases': data.get('aliases') if isinstance(data.get('aliases'), list) else [],
    }
    for key in ('synonyms', 'antonyms', 'collocations', 'aliases'):
        out[key] = [str(x).strip() for x in out[key] if str(x).strip()][:12]
    out['examples'] = [
        {'sentence': str(x.get('sentence') or '').strip(), 'note': str(x.get('note') or '').strip()}
        for x in out['examples'] if isinstance(x, dict) and str(x.get('sentence') or '').strip()
    ][:5]
    out['source_payload'] = dict(out)
    return out


async def _post(model: str, token: str | None, messages: list[dict[str, str]], *, attempts: int | None = None, timeout: int | None = None):
    import aiohttp
    timeout = timeout or settings.LLM_REQUEST_TIMEOUT_SECONDS
    retrying = (attempts or settings.LLM_RETRY_ATTEMPTS) > 1
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout + 15)) as session:
        return await router.llm.post(
            session=session, model=model, token=token, timeout=timeout,
            payload={'messages': messages, 'temperature': 0.1},
            attempts=attempts or settings.LLM_RETRY_ATTEMPTS,
            backoff_seconds=settings.LLM_RETRY_BACKOFF_SECONDS,
            # With a single attempt the original timeout/connection error must
            # propagate as is; swallowing it here would surface only an opaque
            # AttemptsExceededError to the user and the usage log.
            errors_to_ignore_func=(lambda exc: isinstance(exc, (TimeoutError, aiohttp.ClientError))) if retrying else None,
            verbose=False,
        )


async def _deadline(awaitable, seconds: int, operation: str):
    """Hard end-to-end cap so a stalled provider can never hold a worker for minutes."""
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise LlmResponseError(
            f'The {operation} model did not answer within {seconds} seconds. '
            'The provider is probably overloaded right now — try again in a moment or switch models in Settings.'
        ) from exc


async def _post_hedged(model: str, token: str | None, messages: list[dict[str, str]]):
    """Start a second judge request after a short delay and return first success."""
    judge_timeout = settings.JUDGE_REQUEST_TIMEOUT_SECONDS
    primary = asyncio.create_task(_post(model, token, messages, attempts=1, timeout=judge_timeout))
    try:
        return await asyncio.wait_for(asyncio.shield(primary), timeout=settings.JUDGE_HEDGE_DELAY_SECONDS)
    except asyncio.TimeoutError:
        pass
    except Exception:
        # A fast failure should trigger the backup immediately.
        pass

    secondary = asyncio.create_task(_post(model, token, messages, attempts=1, timeout=judge_timeout))
    pending = {task for task in (primary, secondary) if not task.done()}
    errors: list[BaseException] = []
    for task in (primary, secondary):
        if task.done():
            try:
                return task.result()
            except BaseException as exc:
                errors.append(exc)
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                result = task.result()
            except BaseException as exc:
                errors.append(exc)
                continue
            for other in pending:
                other.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            return result
    if errors:
        raise errors[-1]
    raise LlmResponseError('Both judge requests ended without a response.')


def generate_flashcard(*, user, profile: UserProfile, pool: Pool, term: str) -> dict[str, Any]:
    try:
        term = validate_english_term(term).normalized
    except InvalidEnglishTerm as exc:
        raise LlmResponseError(str(exc)) from exc
    model = profile.generation_model
    token = _token(profile, LlmUsage.Operation.GENERATION)
    messages = [
        {'role': 'system', 'content': GENERATION_SYSTEM_PROMPT},
        {'role': 'user', 'content': json.dumps({'term': term}, ensure_ascii=False)},
    ]
    try:
        result = asyncio.run(_deadline(_post(model, token, messages), settings.GENERATION_TOTAL_DEADLINE_SECONDS, 'generation'))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The model response has no textual content.')
        data = _validate_generation(_parse_object(content), term)
        log_usage(user=user, pool=pool, card=None, operation=LlmUsage.Operation.GENERATION, model=model, result=result)
        return data
    except Exception as exc:
        log_usage(user=user, pool=pool, card=None, operation=LlmUsage.Operation.GENERATION, model=model, error=str(exc))
        _public_error(exc)


_VALID_VERDICTS = {
    'wrong', 'mostly_wrong', 'partial', 'half_right', 'mostly_correct', 'correct', 'perfect',
    # Legacy verdict names, still accepted from models with cached behavior.
    'uncertain', 'exact',
}
_FALLBACK_VERDICTS = {1: 'wrong', 2: 'mostly_wrong', 3: 'partial', 4: 'half_right', 5: 'mostly_correct', 6: 'correct', 7: 'perfect'}


def _run_judge(*, user, profile: UserProfile, card: Flashcard, operation: str, model: str,
               system_prompt: str, payload: dict[str, Any], acceptance_score: int) -> dict[str, Any]:
    """Shared hedged judge call: request, validate the 1-7 result, log usage."""
    token = _token(profile, operation)
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        result = asyncio.run(_deadline(_post_hedged(model, token, messages), settings.JUDGE_TOTAL_DEADLINE_SECONDS, 'judge'))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The judge returned no textual content.')
        data = _parse_object(content)
        score = data.get('score')
        if not isinstance(score, int) or not 1 <= score <= 7:
            raise LlmResponseError('The judge returned a score outside the required 1–7 scale.')
        verdict = str(data.get('verdict') or '').strip().lower()
        if verdict not in _VALID_VERDICTS:
            verdict = _FALLBACK_VERDICTS[score]
        judged = {
            'score': score, 'verdict': verdict,
            'feedback': str(data.get('feedback') or '').strip(),
            'matched_concepts': data.get('matched_concepts') if isinstance(data.get('matched_concepts'), list) else [],
            'missing_or_wrong_concepts': data.get('missing_or_wrong_concepts') if isinstance(data.get('missing_or_wrong_concepts'), list) else [],
            'accepted': score >= acceptance_score,
        }
        log_usage(user=user, pool=card.pool, card=card, operation=operation, model=model, result=result)
        return judged
    except Exception as exc:
        log_usage(user=user, pool=card.pool, card=card, operation=operation, model=model, error=str(exc))
        _public_error(exc)


def judge_definition(*, user, profile: UserProfile, card: Flashcard, answer: str) -> dict[str, Any]:
    return _run_judge(
        user=user, profile=profile, card=card,
        operation=LlmUsage.Operation.JUDGING, model=profile.judge_model,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        payload={
            'term': card.term, 'canonical_definition': card.definition,
            'short_definition': card.short_definition, 'part_of_speech': card.part_of_speech,
            'examples': card.examples[:3], 'learner_answer': answer,
        },
        acceptance_score=profile.judge_acceptance_score,
    )


def judge_sentence(*, user, profile: UserProfile, card: Flashcard, answer: str) -> dict[str, Any]:
    return _run_judge(
        user=user, profile=profile, card=card,
        operation=LlmUsage.Operation.SENTENCE_JUDGING, model=sentence_judge_model_for(profile),
        system_prompt=SENTENCE_JUDGE_SYSTEM_PROMPT,
        payload={
            'target_word': card.term, 'part_of_speech': card.part_of_speech,
            'canonical_definition': card.definition, 'short_definition': card.short_definition,
            'example_usages': card.examples[:3], 'learner_sentence': answer,
        },
        acceptance_score=profile.sentence_acceptance_score,
    )


def known_models() -> list[str]:
    return sorted(MODEL_IDS)
