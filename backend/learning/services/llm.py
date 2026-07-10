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
from learning.services.model_catalog import MODEL_IDS
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
Ignore grammar, spelling and style unless they change meaning. Accept paraphrases. Penalize circular definitions, examples without meaning, wrong polarity, and definitions that fit only a different sense.
Return exactly one JSON object and no Markdown:
{
  "score": 1,
  "verdict": "wrong|mostly_wrong|partial|uncertain|mostly_correct|correct|exact",
  "feedback": "one or two direct sentences for the learner",
  "matched_concepts": ["string"],
  "missing_or_wrong_concepts": ["string"]
}
Score scale:
1 = confidently wrong or contradictory
2 = mostly wrong with a small relevant fragment
3 = partial understanding but a major concept is missing or wrong
4 = genuinely ambiguous or too vague to decide
5 = mostly correct, minor omission or imprecision
6 = correct paraphrase
7 = exact and complete understanding
Do not use probabilities or decimal scores.'''


def _token(profile: UserProfile, operation: str) -> str | None:
    encrypted = profile.generation_token_encrypted if operation == LlmUsage.Operation.GENERATION else profile.judge_token_encrypted
    token = decrypt_secret(encrypted)
    if not token and not settings.ALLOW_SERVER_LLM_TOKENS:
        raise LlmConfigurationError(f"No {operation.replace('_', ' ')} provider token is configured. Open Settings and add one.")
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


async def _post(model: str, token: str | None, messages: list[dict[str, str]], *, attempts: int | None = None):
    import aiohttp
    timeout = settings.LLM_REQUEST_TIMEOUT_SECONDS
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout + 15)) as session:
        return await router.llm.post(
            session=session, model=model, token=token, timeout=timeout,
            payload={'messages': messages, 'temperature': 0.1},
            attempts=attempts or settings.LLM_RETRY_ATTEMPTS,
            backoff_seconds=settings.LLM_RETRY_BACKOFF_SECONDS,
            errors_to_ignore_func=lambda exc: isinstance(exc, (TimeoutError, aiohttp.ClientError)),
            verbose=False,
        )


async def _post_hedged(model: str, token: str | None, messages: list[dict[str, str]]):
    """Start a second judge request after a short delay and return first success."""
    primary = asyncio.create_task(_post(model, token, messages, attempts=1))
    try:
        return await asyncio.wait_for(asyncio.shield(primary), timeout=settings.JUDGE_HEDGE_DELAY_SECONDS)
    except asyncio.TimeoutError:
        pass
    except Exception:
        # A fast failure should trigger the backup immediately.
        pass

    secondary = asyncio.create_task(_post(model, token, messages, attempts=1))
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
        result = asyncio.run(_post(model, token, messages))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The model response has no textual content.')
        data = _validate_generation(_parse_object(content), term)
        log_usage(user=user, pool=pool, card=None, operation=LlmUsage.Operation.GENERATION, model=model, result=result)
        return data
    except Exception as exc:
        log_usage(user=user, pool=pool, card=None, operation=LlmUsage.Operation.GENERATION, model=model, error=str(exc))
        _public_error(exc)


def judge_definition(*, user, profile: UserProfile, card: Flashcard, answer: str) -> dict[str, Any]:
    model = profile.judge_model
    token = _token(profile, LlmUsage.Operation.JUDGING)
    payload = {
        'term': card.term, 'canonical_definition': card.definition,
        'short_definition': card.short_definition, 'part_of_speech': card.part_of_speech,
        'examples': card.examples[:3], 'learner_answer': answer,
    }
    messages = [
        {'role': 'system', 'content': JUDGE_SYSTEM_PROMPT},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        result = asyncio.run(_post_hedged(model, token, messages))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The judge returned no textual content.')
        data = _parse_object(content)
        score = data.get('score')
        if not isinstance(score, int) or not 1 <= score <= 7:
            raise LlmResponseError('The judge returned a score outside the required 1–7 scale.')
        valid = {'wrong', 'mostly_wrong', 'partial', 'uncertain', 'mostly_correct', 'correct', 'exact'}
        verdict = str(data.get('verdict') or 'uncertain').strip().lower()
        if verdict not in valid:
            verdict = 'uncertain'
        judged = {
            'score': score, 'verdict': verdict,
            'feedback': str(data.get('feedback') or '').strip(),
            'matched_concepts': data.get('matched_concepts') if isinstance(data.get('matched_concepts'), list) else [],
            'missing_or_wrong_concepts': data.get('missing_or_wrong_concepts') if isinstance(data.get('missing_or_wrong_concepts'), list) else [],
            'accepted': score >= profile.judge_acceptance_score,
            'should_reveal': score <= profile.reveal_threshold,
        }
        log_usage(user=user, pool=card.pool, card=card, operation=LlmUsage.Operation.JUDGING, model=model, result=result)
        return judged
    except Exception as exc:
        log_usage(user=user, pool=card.pool, card=card, operation=LlmUsage.Operation.JUDGING, model=model, error=str(exc))
        _public_error(exc)


def known_models() -> list[str]:
    return sorted(MODEL_IDS)
