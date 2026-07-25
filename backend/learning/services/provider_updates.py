from __future__ import annotations

import asyncio
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import aiohttp
import requests
import router
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from learning.exceptions import LlmConfigurationError, LlmResponseError
from learning.models import LlmUsage, UserProfile
from learning.services.llm import _deadline, _parse_object, _post, log_usage
from learning.services.model_catalog import (
    MODEL_ID_RE,
    TOKEN_PROVIDERS,
    api_model_name,
    canonical_model_id,
    model_catalog,
    provider_override_models,
    request_config_for,
    token_provider_for,
)
from learning.services.security import decrypt_secret


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    models_url: str
    auth_style: str
    key_url: str | None
    token_label: str


# This is the security boundary: discovery may update model-level data only.
# Network destinations and auth protocols are reviewed application code.
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    'deepseek': ProviderSpec(
        name='DeepSeek',
        models_url='https://api.deepseek.com/models',
        auth_style='bearer',
        key_url='https://platform.deepseek.com/api_keys',
        token_label='DeepSeek API key',
    ),
    'openai': ProviderSpec(
        name='OpenAI',
        models_url='https://api.openai.com/v1/models',
        auth_style='bearer',
        key_url='https://platform.openai.com/api-keys',
        token_label='OpenAI API key',
    ),
    'anthropic': ProviderSpec(
        name='Anthropic',
        models_url='https://api.anthropic.com/v1/models',
        auth_style='anthropic',
        key_url='https://console.anthropic.com/settings/keys',
        token_label='Anthropic API key',
    ),
    'openrouter': ProviderSpec(
        name='OpenRouter',
        models_url='https://openrouter.ai/api/v1/models',
        auth_style='bearer',
        key_url='https://openrouter.ai/settings/keys',
        token_label='OpenRouter API key',
    ),
    'xiaomi': ProviderSpec(
        name='Xiaomi',
        models_url='https://api.xiaomimimo.com/v1/models',
        auth_style='bearer',
        key_url=None,
        token_label='Xiaomi MiMo API key',
    ),
}

_NON_CHAT_MARKERS = (
    'embedding', 'moderation', 'transcribe', 'transcription', 'tts', 'realtime',
    'audio', 'image', 'dall-e', 'whisper', 'search', 'computer-use',
)
_OPENROUTER_FAMILIES = ('openai/', 'anthropic/', 'google/', 'deepseek/', 'moonshotai/', 'xiaomi/')
_DISCOVERY_MODEL_LIMIT = 500
_CANARY_MODEL_LIMIT = 12

CATALOG_ANALYST_PROMPT = '''You maintain the model picker for an AI vocabulary-flashcard application.
The user message contains model IDs returned moments ago by the target provider's authenticated /models API. Those IDs are the only source of truth: never invent, alter, or normalize an ID.
Describe at most 12 especially useful text chat models for (a) structured JSON flashcard generation and/or (b) short semantic judging. LexiLoop deterministically keeps every usable ID in the live list, so your selection only enriches labels and recommendations; omitting an ID never removes it. Prefer current general-purpose models and a useful spread of fast/value/capable choices. Exclude embeddings, audio, image, moderation, realtime, and other non-chat models.
Return exactly one JSON object and no Markdown:
{"models":[{"id":"exact live API id","label":"concise human label","description":"one factual sentence; do not claim unprovided prices or benchmarks","recommended_for":["generation","judge"],"badge":"short badge"}]}
recommended_for must contain generation, judge, or both. Keep every string concise.'''

CATALOG_REVIEW_PROMPT = '''Act as the final reviewer of a provider model catalog.
Use only IDs in live_model_ids. Correct fabricated IDs, non-chat entries, misleading labels, and unsuitable role recommendations in the proposed metadata. LexiLoop independently keeps all usable live IDs, so omissions are acceptable. Keep at most 12 useful text chat model descriptions. Return exactly the same JSON schema and no Markdown:
{"models":[{"id":"exact live API id","label":"concise human label","description":"one factual sentence","recommended_for":["generation","judge"],"badge":"short badge"}]}'''


def provider_update_summaries(profile: UserProfile) -> list[dict[str, Any]]:
    overrides = profile.provider_catalog_overrides if isinstance(profile.provider_catalog_overrides, dict) else {}
    saved = profile.provider_tokens_encrypted if isinstance(profile.provider_tokens_encrypted, dict) else {}
    counts: dict[str, int] = {}
    for item in model_catalog(profile):
        provider = item['token_provider']
        counts[provider] = counts.get(provider, 0) + 1
    summaries: list[dict[str, Any]] = []
    for provider, spec in PROVIDER_SPECS.items():
        update = overrides.get(provider, {})
        update = update if isinstance(update, dict) else {}
        warnings = update.get('canary_warnings')
        warnings = warnings if isinstance(warnings, dict) else {}
        summaries.append({
            'id': provider,
            'name': spec.name,
            'can_update': True,
            'has_key': bool(saved.get(provider)),
            'last_updated_at': update.get('updated_at') if isinstance(update.get('updated_at'), str) else None,
            'source_model': update.get('source_model') if isinstance(update.get('source_model'), str) else None,
            'model_count': counts.get(provider, 0),
            'warning_count': len(warnings),
        })
    return summaries


def _auth_headers(spec: ProviderSpec, token: str) -> dict[str, str]:
    if spec.auth_style == 'anthropic':
        return {
            'x-api-key': token,
            'anthropic-version': '2023-06-01',
            'accept': 'application/json',
        }
    return {'Authorization': f'Bearer {token}', 'accept': 'application/json'}


def _natural_key(value: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', value))


def _filter_live_ids(provider: str, raw_ids: list[str]) -> list[str]:
    clean = sorted({
        value for value in raw_ids
        if MODEL_ID_RE.fullmatch(value) and not any(marker in value.casefold() for marker in _NON_CHAT_MARKERS)
    }, key=_natural_key, reverse=True)
    if provider == 'anthropic':
        clean = [value for value in clean if value.startswith('claude-')]
    elif provider == 'openai':
        clean = [value for value in clean if value.startswith(('gpt-', 'o1', 'o3', 'o4', 'o5', 'chatgpt-'))]
    elif provider == 'openrouter':
        clean = [value for value in clean if value.startswith(_OPENROUTER_FAMILIES)]
    elif provider == 'xiaomi':
        clean = [value for value in clean if 'mimo' in value.casefold()]
    elif provider == 'deepseek':
        clean = [value for value in clean if value.startswith('deepseek-')]
    return clean[:_DISCOVERY_MODEL_LIMIT]


def discover_provider_models(provider: str, token: str) -> list[str]:
    spec = PROVIDER_SPECS[provider]
    try:
        response = requests.get(
            spec.models_url,
            headers=_auth_headers(spec, token),
            timeout=settings.PROVIDER_DISCOVERY_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise LlmResponseError(f'{spec.name} model discovery could not connect: {type(exc).__name__}.') from exc
    if not 200 <= response.status_code < 300:
        detail = ''
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get('error')
                if isinstance(error, dict):
                    detail = str(error.get('message') or '')
                elif isinstance(body.get('detail'), str):
                    detail = body['detail']
        except ValueError:
            detail = ''
        suffix = f' {detail[:300]}' if detail else ''
        raise LlmResponseError(f'{spec.name} /models returned HTTP {response.status_code}.{suffix}')
    try:
        body = response.json()
    except ValueError as exc:
        raise LlmResponseError(f'{spec.name} /models did not return JSON.') from exc
    data = body.get('data') if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise LlmResponseError(f'{spec.name} /models returned an unexpected response shape.')
    raw_ids = [
        str(item.get('id'))
        for item in data
        if isinstance(item, dict) and isinstance(item.get('id'), str)
    ]
    ids = _filter_live_ids(provider, raw_ids)
    if not ids:
        raise LlmResponseError(f'{spec.name} /models returned no usable text-chat model IDs.')
    return ids


def _human_label(model_id: str) -> str:
    words = re.split(r'[-_/]+', model_id)
    special = {'gpt': 'GPT', 'v4': 'V4', 'v3': 'V3', 'ai': 'AI', 'mimo': 'MiMo'}
    return ' '.join(special.get(word.casefold(), word.upper() if len(word) <= 2 else word.title()) for word in words)[:120]


def _fallback_metadata(model_id: str) -> dict[str, Any]:
    lowered = model_id.casefold()
    capable = any(marker in lowered for marker in ('pro', 'opus', 'reason', 'large', 'max'))
    fast = any(marker in lowered for marker in ('flash', 'mini', 'nano', 'haiku', 'fast', 'lite', 'small'))
    roles = ['generation'] if capable and not fast else ['generation', 'judge']
    return {
        'id': model_id,
        'label': _human_label(model_id),
        'description': 'Text model discovered from the provider’s authenticated live API catalog.',
        'recommended_for': roles,
        'badge': 'Reasoning' if capable else 'Fast' if fast else 'Live API',
    }


def _validate_ai_models(payload: dict[str, Any], live_ids: list[str]) -> list[dict[str, Any]]:
    allowed = set(live_ids)
    raw = payload.get('models')
    if not isinstance(raw, list):
        raise LlmResponseError('The catalog analyst did not return a models list.')
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id') or '')
        if model_id not in allowed or model_id in seen:
            continue
        roles = item.get('recommended_for')
        roles = [role for role in ('generation', 'judge') if isinstance(roles, list) and role in roles]
        if not roles:
            continue
        seen.add(model_id)
        output.append({
            'id': model_id,
            'label': str(item.get('label') or _human_label(model_id)).strip()[:120],
            'description': str(item.get('description') or _fallback_metadata(model_id)['description']).strip()[:500],
            'recommended_for': roles,
            'badge': str(item.get('badge') or 'API verified').strip()[:40],
        })
    if not output:
        raise LlmResponseError('The catalog analyst returned no valid live chat models.')
    return output


def _source_candidates(
    profile: UserProfile,
    target_provider: str,
    live_ids: list[str],
) -> list[tuple[str, str]]:
    saved = profile.provider_tokens_encrypted if isinstance(profile.provider_tokens_encrypted, dict) else {}
    candidates: list[tuple[str, str]] = []
    target_token = decrypt_secret(saved.get(target_provider, ''))
    # A newly discovered target model is usually the freshest and most useful
    # analyst. Fast/value-looking IDs sort ahead of heavyweight ones.
    target_order = sorted(
        live_ids,
        key=lambda value: (
            not any(marker in value.casefold() for marker in ('flash', 'mini', 'nano', 'haiku', 'fast', 'lite')),
            _natural_key(value),
        ),
    )
    if target_token:
        candidates.append((f'{target_provider}:{target_order[0]}', target_token))
    selected = [
        profile.generation_model,
        profile.judge_model,
        profile.sentence_judge_model,
        profile.image_model,
    ]
    selected.extend(item['id'] for item in model_catalog(profile))
    for model_id in selected:
        if not model_id:
            continue
        provider = token_provider_for(model_id)
        token = decrypt_secret(saved.get(provider, ''))
        if provider and token:
            candidates.append((canonical_model_id(model_id), token))
    if target_token:
        candidates.extend((f'{target_provider}:{model_id}', target_token) for model_id in target_order[1:3])
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for model_id, token in candidates:
        if model_id not in seen:
            seen.add(model_id)
            unique.append((model_id, token))
    return unique[:8]


def _run_catalog_llm(
    *,
    user,
    model: str,
    token: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    try:
        result = asyncio.run(_deadline(
            _post(
                model,
                token,
                messages,
                attempts=1,
                timeout=settings.PROVIDER_UPDATE_LLM_TIMEOUT_SECONDS,
            ),
            settings.PROVIDER_UPDATE_LLM_TIMEOUT_SECONDS + 5,
            'provider update',
        ))
        content = result.get('content')
        if not isinstance(content, str):
            raise LlmResponseError('The catalog analyst returned no textual content.')
        log_usage(
            user=user,
            pool=None,
            card=None,
            operation=LlmUsage.Operation.PROVIDER_UPDATE,
            model=model,
            result=result,
        )
        return _parse_object(content)
    except Exception as exc:
        log_usage(
            user=user,
            pool=None,
            card=None,
            operation=LlmUsage.Operation.PROVIDER_UPDATE,
            model=model,
            error=str(exc),
        )
        raise


def enrich_catalog_with_ai(
    *,
    user,
    profile: UserProfile,
    provider: str,
    live_ids: list[str],
    current: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None, int]:
    source_model: str | None = None
    proposal: list[dict[str, Any]] | None = None
    # Two bounded attempts plus one review and concurrent canaries remain below
    # Gunicorn's 180-second worker ceiling even when every network call times out.
    for candidate, token in _source_candidates(profile, provider, live_ids)[:2]:
        request = {
            'target_provider': PROVIDER_SPECS[provider].name,
            'live_model_ids': live_ids,
            'current_catalog': [
                {
                    'id': api_model_name(item['id']),
                    'label': item['label'],
                    'recommended_for': item['recommended_for'],
                }
                for item in current
            ],
        }
        try:
            payload = _run_catalog_llm(
                user=user,
                model=candidate,
                token=token,
                messages=[
                    {'role': 'system', 'content': CATALOG_ANALYST_PROMPT},
                    {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)},
                ],
            )
            proposal = _validate_ai_models(payload, live_ids)
            source_model = candidate
            break
        except Exception:
            continue
    if proposal is None or source_model is None:
        return [], None, 0

    # A second independent pass critiques the first pass. Failure is harmless:
    # the first pass is still schema-checked and every ID came from /models.
    token = next(token for model, token in _source_candidates(profile, provider, live_ids) if model == source_model)
    review_request = {
        'target_provider': PROVIDER_SPECS[provider].name,
        'live_model_ids': live_ids,
        'proposed_catalog': proposal,
    }
    try:
        reviewed = _run_catalog_llm(
            user=user,
            model=source_model,
            token=token,
            messages=[
                {'role': 'system', 'content': CATALOG_REVIEW_PROMPT},
                {'role': 'user', 'content': json.dumps(review_request, ensure_ascii=False)},
            ],
        )
        return _validate_ai_models(reviewed, live_ids), source_model, 2
    except Exception:
        return proposal, source_model, 1


def _catalog_entries(
    provider: str,
    live_ids: list[str],
    enriched: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spec = PROVIDER_SPECS[provider]
    by_id = {item['id']: item for item in enriched}
    entries: list[dict[str, Any]] = []
    # Membership comes from authenticated discovery, never from an LLM. The
    # analyst may enrich a subset, while deterministic metadata covers every
    # other usable ID.
    for api_id in live_ids:
        metadata = by_id.get(api_id) or _fallback_metadata(api_id)
        entries.append({
            'id': f'{provider}:{api_id}',
            'label': metadata['label'],
            'provider': spec.name,
            'description': metadata['description'],
            'token_label': spec.token_label,
            'token_provider': provider,
            'recommended_for': metadata['recommended_for'],
            'badge': metadata['badge'],
            'key_url': spec.key_url,
        })
    return entries


async def _canary_one(entry: dict[str, Any], token: str) -> tuple[str, str | None]:
    model_id = entry['id']
    model_config = request_config_for(model_id)
    # A canary checks the model name and chat wire format, not reasoning
    # quality. Disabling thinking avoids false DeepSeek Pro timeouts.
    if token_provider_for(model_id) == 'deepseek':
        model_config = {
            **model_config,
            'extra_parameters': {'thinking': {'type': 'disabled'}},
        }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=settings.PROVIDER_CANARY_TIMEOUT_SECONDS + 5)
        ) as session:
            result = await router.llm.post(
                session=session,
                model=model_id,
                token=token,
                timeout=settings.PROVIDER_CANARY_TIMEOUT_SECONDS,
                payload={
                    'messages': [
                        {'role': 'system', 'content': 'Reply with exactly LEXILOOP_API_OK.'},
                        {'role': 'user', 'content': 'Connection test.'},
                    ],
                    'temperature': 0,
                    'max_tokens': 32,
                },
                model_config=model_config,
                attempts=1,
                verbose=False,
            )
        content = result.get('content')
        if not isinstance(content, str) or not content.strip():
            return model_id, 'empty response'
        return model_id, None
    except Exception as exc:
        return model_id, f'{type(exc).__name__}: {str(exc)[:240]}'


def canary_models(entries: list[dict[str, Any]], token: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    async def run() -> list[tuple[str, str | None]]:
        semaphore = asyncio.Semaphore(4)

        async def limited(entry):
            async with semaphore:
                return await _canary_one(entry, token)

        return await asyncio.gather(*(limited(entry) for entry in entries))

    results = asyncio.run(run())
    errors = {model_id: error for model_id, error in results if error}
    verified = [entry for entry in entries if entry['id'] not in errors]
    return verified, errors


def _activate(
    *,
    profile: UserProfile,
    provider: str,
    entries: list[dict[str, Any]],
    live_count: int,
    source_model: str | None,
    ai_runs: int,
    verified_models: list[str],
    canary_warnings: dict[str, str],
) -> tuple[UserProfile, list[str], bool, int, int, int]:
    with transaction.atomic():
        locked = UserProfile.objects.select_for_update().get(pk=profile.pk)
        previous_ids = {
            item['id'] for item in model_catalog(locked)
            if item['token_provider'] == provider
        }
        previous_overrides = provider_override_models(locked, provider)
        merged_by_id = {item['id']: item for item in previous_overrides}
        merged_by_id.update({item['id']: item for item in entries})
        merged_entries = list(merged_by_id.values())
        overrides = deepcopy(locked.provider_catalog_overrides) if isinstance(locked.provider_catalog_overrides, dict) else {}
        overrides[provider] = {
            'models': merged_entries,
            'updated_at': timezone.now().isoformat(),
            'source_model': source_model,
            'ai_runs': ai_runs,
            'discovered_count': live_count,
            'canary_verified_models': verified_models,
            'canary_warnings': canary_warnings,
        }
        locked.provider_catalog_overrides = overrides
        migrated: list[str] = []
        for field in ('generation_model', 'judge_model', 'image_model', 'sentence_judge_model'):
            current = getattr(locked, field)
            if not current or token_provider_for(current) != provider:
                continue
            canonical = canonical_model_id(current)
            # Only canonicalize explicit legacy aliases. A temporarily absent
            # /models entry must never silently change a user's selection.
            if current != canonical:
                setattr(locked, field, canonical)
                migrated.append(field)
        locked.save(update_fields=['provider_catalog_overrides', *migrated, 'updated_at'])
        new_ids = {
            item['id'] for item in model_catalog(locked)
            if item['token_provider'] == provider
        }
        changed = previous_ids != new_ids
        proposed_ids = {item['id'] for item in entries}
        added_count = len(new_ids - previous_ids)
        preserved_count = len(new_ids - proposed_ids)
    return locked, migrated, changed, len(new_ids), added_count, preserved_count


def update_provider_catalog(*, user, profile: UserProfile, provider: str) -> dict[str, Any]:
    if provider not in PROVIDER_SPECS:
        raise KeyError(provider)
    encrypted = (profile.provider_tokens_encrypted or {}).get(provider, '')
    token = decrypt_secret(encrypted)
    if not token:
        raise LlmConfigurationError(
            f'No {PROVIDER_SPECS[provider].token_label} is saved. Save the provider key before checking for updates.'
        )

    live_ids = discover_provider_models(provider, token)
    current = [item for item in model_catalog(profile) if item['token_provider'] == provider]
    enriched, source_model, ai_runs = enrich_catalog_with_ai(
        user=user,
        profile=profile,
        provider=provider,
        live_ids=live_ids,
        current=current,
    )
    proposed = _catalog_entries(provider, live_ids, enriched)
    enriched_ids = {f'{provider}:{item["id"]}' for item in enriched}
    canary_candidates = sorted(
        proposed,
        key=lambda item: item['id'] not in enriched_ids,
    )[:_CANARY_MODEL_LIMIT]
    verified, canary_errors = canary_models(canary_candidates, token)
    verified_ids = [item['id'] for item in verified]
    activated, migrated, changed, available_count, added_count, preserved_count = _activate(
        profile=profile,
        provider=provider,
        entries=proposed,
        live_count=len(live_ids),
        source_model=source_model,
        ai_runs=ai_runs,
        verified_models=verified_ids,
        canary_warnings=canary_errors,
    )
    return {
        'provider': provider,
        'provider_name': PROVIDER_SPECS[provider].name,
        'status': 'updated',
        'changed': changed,
        'discovered_count': len(live_ids),
        'activated_count': available_count,
        'added_count': added_count,
        'preserved_count': preserved_count,
        'canary_tested_count': len(canary_candidates),
        'verified_models': verified_ids,
        'canary_warnings': canary_errors,
        # Kept for older clients. Canary warnings are intentionally not
        # rejections and no discovered model is removed because of one probe.
        'rejected_models': {},
        'source_model': source_model,
        'ai_runs': ai_runs,
        'migrated_settings': migrated,
        'profile': activated,
    }
