from __future__ import annotations

import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import aiohttp
import requests
import router
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from learning.exceptions import LlmConfigurationError, LlmResponseError
from learning.models import LlmUsage, RouterAdapter, UserProfile
from learning.services.adapters import (
    ADAPTER_CONTRACT,
    ALLOWED_IMPORTS,
    MAX_SOURCE_CHARS,
    MAX_SOURCE_LINES,
    AdapterError,
    activate_revision,
    active_adapter,
    compile_adapter,
    refresh_active_adapters,
    run_adapter,
    screen_source,
)
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
    # What the built-in adapter does today. Handed to the authoring model as the
    # starting point so a new revision is an edit of working code, not a guess.
    reference: str


# This is the security boundary: discovery may update model-level data only.
# Network destinations and auth protocols are reviewed application code.
PROVIDER_SPECS: dict[str, ProviderSpec] = {
    'deepseek': ProviderSpec(
        name='DeepSeek',
        models_url='https://api.deepseek.com/models',
        auth_style='bearer',
        key_url='https://platform.deepseek.com/api_keys',
        token_label='DeepSeek API key',
        reference=(
            'POST https://api.deepseek.com/chat/completions with Authorization: Bearer <token>. '
            'OpenAI-compatible body {"model", "messages", "stream": false}. Reasoning-capable models '
            'take {"thinking": {"type": "enabled"|"disabled"}} and reject temperature/top_p/presence_penalty/'
            'frequency_penalty while thinking is enabled. The reply is choices[0].message.content, with '
            'choices[0].message.reasoning_content when the model thinks, and a usage object.'
        ),
    ),
    'openai': ProviderSpec(
        name='OpenAI',
        models_url='https://api.openai.com/v1/models',
        auth_style='bearer',
        key_url='https://platform.openai.com/api-keys',
        token_label='OpenAI API key',
        reference=(
            'POST https://api.openai.com/v1/chat/completions with Authorization: Bearer <token>. '
            'gpt-5 and o-series models reject "temperature" and require "max_completion_tokens" instead of '
            '"max_tokens"; some of them are only served by POST https://api.openai.com/v1/responses, which '
            'takes {"model", "input": messages, "max_output_tokens", "reasoning": {"effort"}} and answers with '
            'output_text or output[].content[].text. Chat replies are choices[0].message.content plus usage.'
        ),
    ),
    'anthropic': ProviderSpec(
        name='Anthropic',
        models_url='https://api.anthropic.com/v1/models',
        auth_style='anthropic',
        key_url='https://console.anthropic.com/settings/keys',
        token_label='Anthropic API key',
        reference=(
            'POST https://api.anthropic.com/v1/messages with headers x-api-key: <token> and '
            'anthropic-version: 2023-06-01. System messages move out of "messages" into a top-level "system" '
            'string; "max_tokens" is required. Models above Haiku reject temperature/top_p/top_k. The reply is '
            'content[] blocks where type == "text" carries .text, plus usage.input_tokens/output_tokens and '
            'cache_read_input_tokens/cache_creation_input_tokens.'
        ),
    ),
    'openrouter': ProviderSpec(
        name='OpenRouter',
        models_url='https://openrouter.ai/api/v1/models',
        auth_style='bearer',
        key_url='https://openrouter.ai/settings/keys',
        token_label='OpenRouter API key',
        reference=(
            'POST https://openrouter.ai/api/v1/chat/completions with Authorization: Bearer <token>, '
            'HTTP-Referer and X-OpenRouter-Title headers. OpenAI-compatible body and reply; model IDs carry a '
            'vendor prefix such as "openai/gpt-5.2". usage.cost reports the charge in US dollars.'
        ),
    ),
    'xiaomi': ProviderSpec(
        name='Xiaomi',
        models_url='https://api.xiaomimimo.com/v1/models',
        auth_style='bearer',
        key_url=None,
        token_label='Xiaomi MiMo API key',
        reference=(
            'POST https://api.xiaomimimo.com/v1/chat/completions with Authorization: Bearer <token>. '
            'OpenAI-compatible body and reply; reasoning text arrives as choices[0].message.reasoning_content '
            'or choices[0].message.reasoning.'
        ),
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


ADAPTER_AUTHOR_PROMPT = '''You write the Python module that connects a vocabulary-flashcard backend to one LLM provider's chat API. Your module replaces the hand-written adapter, so it must work against the provider's API exactly as it behaves today.

Return exactly one JSON object and no Markdown:
{"module":"the complete Python source","summary":"one sentence on what changed and why","model_notes":{"model-id":"any per-model quirk you handled"}}

THE MODULE MUST DEFINE THIS ENTRY POINT:

    async def post(ctx, *, model, token, messages, options):
        """Return {"content": str, "reasoning_content": str|None, "stats": dict}."""

- `model` is the provider's own model ID (no "provider:" prefix), `token` is the API key.
- `messages` is a list of {"role": "system"|"user"|"assistant", "content": str}. Reshape it however this provider requires (for example moving a system message to a top-level field).
- `options` may contain "temperature" (float), "max_tokens" (int) and "reasoning" ("auto", "off" or "high"). Apply an option only where the target model accepts it; silently drop what the model would reject. Never fail a request because of an optional sampling field.
- Return "content" as the assistant's plain text. Put chain-of-thought in "reasoning_content" when the provider exposes it separately, else None. Put token counts and any reported cost into "stats" as flat scalars (input_tokens, output_tokens, total_tokens, total_price).
- Also return the provider's decoded JSON body unchanged as "response". LexiLoop prices the call from it using its own tables, so omitting it silently loses cost tracking.
- Raise ValueError with a short explanatory message when the provider's reply cannot be parsed.

THE ONLY WAY TO REACH THE NETWORK is the context object:

    body = await ctx.fetch(url, headers={...}, json={...}, method="POST", timeout=30)

It returns the decoded JSON object and raises on a non-2xx status, on a non-JSON body, and on any host outside this provider. At most 4 fetch calls may be made per completion.

HARD SANDBOX RULES — code that breaks one of these is rejected before it runs:
- Imports are limited to: __ALLOWED_IMPORTS__. Write the module so it needs none of them if you can.
- No eval, exec, compile, open, __import__, getattr, setattr, globals, locals, or any other dynamic-attribute or introspection builtin. No os, sys, subprocess, socket, asyncio, aiohttp, requests, urllib.
- No name or attribute that starts with an underscore, anywhere.
- Endpoint URLs must be written as complete literal https:// strings on this provider's own domain. Do not build a URL out of pieces or an f-string.
- No loops at module level. At most __MAX_LINES__ lines and __MAX_CHARS__ characters.
- Only these builtins exist: abs all any bool bytes dict divmod enumerate filter float format frozenset int isinstance issubclass iter len list map max min next range repr reversed round set slice sorted str sum tuple zip, plus the common exception types.

WRITING GUIDANCE:
- Start from the reference behaviour you are given and change only what the evidence shows is wrong. A working adapter that handles one more model beats a clever rewrite.
- The failing_calls evidence contains the provider's own error messages from live requests made moments ago. Read them literally: they name the parameter, endpoint or field that must change.
- live_model_ids is the complete list of models this adapter must serve. Branch on the model ID where families genuinely differ (reasoning vs. chat, a family that needs a different endpoint), but keep one common path.
- Keep helper functions small and total, and never assume an optional field is present.
- Do not write comments that restate the code; a short docstring per function is enough.'''


def provider_update_summaries(profile: UserProfile, *, can_update: bool = False) -> list[dict[str, Any]]:
    """Per-provider status for the Settings page.

    ``can_update`` mirrors the server-side permission: running a check is a
    platform-maintenance action, so ordinary accounts see the state of their keys
    without the controls that rewrite shared connection code.
    """
    overrides = profile.provider_catalog_overrides if isinstance(profile.provider_catalog_overrides, dict) else {}
    saved = profile.provider_tokens_encrypted if isinstance(profile.provider_tokens_encrypted, dict) else {}
    counts: dict[str, int] = {}
    for item in model_catalog(profile):
        provider = item['token_provider']
        counts[provider] = counts.get(provider, 0) + 1
    adapters = {
        record.provider: record
        for record in RouterAdapter.objects.filter(status=RouterAdapter.Status.ACTIVE)
    }
    summaries: list[dict[str, Any]] = []
    for provider, spec in PROVIDER_SPECS.items():
        update = overrides.get(provider, {})
        update = update if isinstance(update, dict) else {}
        warnings = update.get('canary_warnings')
        warnings = warnings if isinstance(warnings, dict) else {}
        adapter = adapters.get(provider)
        summaries.append({
            'id': provider,
            'name': spec.name,
            'can_update': can_update,
            'has_key': bool(saved.get(provider)),
            'last_updated_at': update.get('updated_at') if isinstance(update.get('updated_at'), str) else None,
            'source_model': update.get('source_model') if isinstance(update.get('source_model'), str) else None,
            'model_count': counts.get(provider, 0),
            'warning_count': len(warnings),
            'adapter_revision': adapter.revision if adapter else None,
            'adapter_author_model': adapter.author_model if adapter else None,
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


# Capability tiers used to pick the model that writes adapter code. Writing one
# connection module is a demanding but bounded task: it wants a strong general
# model, not a flagship. The top tier is skipped whenever a capable-tier model is
# available, and only used as a last resort.
_FLAGSHIP_MARKERS = ('fable', 'opus', 'ultra', '-max', 'max-', 'gpt-5-pro', 'gpt-5.2-pro', 'gpt-5.4-pro', 'o3-pro', 'o4-pro')
_CAPABLE_MARKERS = ('sonnet', 'gpt-5.4', 'gpt-5.3', 'gpt-5.2', 'v4-pro', 'reasoner', 'kimi', 'gemini-3.1-pro', 'gemini-3-pro', 'terminus', 'v3.2')
_FAST_MARKERS = ('mini', 'haiku', 'flash', 'turbo')
_SMALL_MARKERS = ('nano', 'lite', 'tiny', 'small', 'micro')

FLAGSHIP_RANK = 90
CAPABLE_RANK = 70
MIN_AUTHOR_RANK = 50


def capability_rank(model_id: str) -> int:
    """Roughly how capable a catalog model is, from its published ID.

    Provider IDs are marketing names, so this is a heuristic — but the size
    words providers use ("nano", "mini", "pro") are stable enough to order
    candidates sensibly, and a wrong pick only costs one failed attempt.
    """
    name = api_model_name(canonical_model_id(model_id)).casefold()
    if any(marker in name for marker in _SMALL_MARKERS):
        return 20
    if any(marker in name for marker in _FLAGSHIP_MARKERS):
        return FLAGSHIP_RANK
    if any(marker in name for marker in _FAST_MARKERS):
        return 40
    if any(marker in name for marker in _CAPABLE_MARKERS):
        return CAPABLE_RANK
    return MIN_AUTHOR_RANK


def author_candidates(profile: UserProfile) -> list[tuple[str, str]]:
    """Catalog models with a usable key, most capable first.

    Flagship-tier models sort last: they can write the adapter but are wasted on
    it, so they are only reached when nothing else is configured.
    """
    saved = profile.provider_tokens_encrypted if isinstance(profile.provider_tokens_encrypted, dict) else {}
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in model_catalog(profile):
        model_id = item['id']
        if model_id in seen:
            continue
        token = decrypt_secret(saved.get(item['token_provider'], ''))
        if not token:
            continue
        seen.add(model_id)
        candidates.append((model_id, token))

    def order(entry: tuple[str, str]):
        rank = capability_rank(entry[0])
        # Sorted descending, so the non-flagship bucket (1) is served first and
        # a newer version string wins inside one tier.
        return (0 if rank >= FLAGSHIP_RANK else 1, 0 if rank >= FLAGSHIP_RANK else rank, _natural_key(entry[0]))

    candidates.sort(key=order, reverse=True)
    return candidates


def select_author_model(profile: UserProfile) -> tuple[str, str] | None:
    candidates = author_candidates(profile)
    return candidates[0] if candidates else None


def _run_catalog_llm(
    *,
    user,
    model: str,
    token: str,
    messages: list[dict[str, str]],
    timeout: int | None = None,
) -> dict[str, Any]:
    timeout = timeout or settings.PROVIDER_UPDATE_LLM_TIMEOUT_SECONDS
    # The catalog and authoring calls go through the same connection modules as
    # everything else, so the cache is primed here too, outside the event loop.
    refresh_active_adapters()
    try:
        result = asyncio.run(_deadline(
            _post(
                model,
                token,
                messages,
                attempts=1,
                timeout=timeout,
            ),
            timeout + 5,
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
                    'max_tokens': 128,
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


CANARY_MESSAGES = [
    {'role': 'system', 'content': 'Reply with exactly LEXILOOP_API_OK.'},
    {'role': 'user', 'content': 'Connection test.'},
]
CANARY_OPTIONS = {'temperature': 0, 'max_tokens': 128, 'reasoning': 'off'}


def probe_with_adapter(
    namespace: dict[str, Any],
    *,
    provider: str,
    api_models: list[str],
    token: str,
) -> tuple[list[str], dict[str, str]]:
    """Run the canary conversation through a compiled adapter."""

    async def one(api_model: str) -> tuple[str, str | None]:
        try:
            result = await run_adapter(
                namespace,
                provider=provider,
                model=api_model,
                token=token,
                messages=CANARY_MESSAGES,
                options=CANARY_OPTIONS,
                timeout=settings.PROVIDER_CANARY_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return api_model, f'{type(exc).__name__}: {str(exc)[:240]}'
        content = result.get('content')
        if not isinstance(content, str) or not content.strip():
            return api_model, 'empty response'
        return api_model, None

    async def run() -> list[tuple[str, str | None]]:
        semaphore = asyncio.Semaphore(4)

        async def limited(api_model: str):
            async with semaphore:
                return await one(api_model)

        return await asyncio.gather(*(limited(api_model) for api_model in api_models))

    results = asyncio.run(run())
    failures = {api_model: error for api_model, error in results if error}
    passed = [api_model for api_model, error in results if not error]
    return passed, failures


def _current_adapter_summary(provider: str) -> dict[str, Any]:
    record = RouterAdapter.objects.filter(provider=provider, status=RouterAdapter.Status.ACTIVE).first()
    if record is None:
        return {'revision': None, 'source': None, 'reference': PROVIDER_SPECS[provider].reference}
    return {'revision': record.revision, 'source': record.source_code, 'reference': PROVIDER_SPECS[provider].reference}


def _extract_module(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    module = payload.get('module')
    if not isinstance(module, str) or not module.strip():
        raise LlmResponseError('The adapter author returned no module source.')
    # Models often wrap code in a fence despite the instruction not to.
    cleaned = module.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```[a-zA-Z]*\n', '', cleaned)
        cleaned = re.sub(r'\n```$', '', cleaned).strip()
    summary = str(payload.get('summary') or '').strip()[:400]
    notes = payload.get('model_notes')
    return cleaned, summary, notes if isinstance(notes, dict) else {}


def _authoring_request(
    *,
    provider: str,
    live_ids: list[str],
    failures: dict[str, str],
    current: dict[str, Any],
) -> dict[str, Any]:
    spec = PROVIDER_SPECS[provider]
    return {
        'provider': spec.name,
        'provider_id': provider,
        'live_model_ids': live_ids[:60],
        'reference_behaviour': current['reference'],
        'current_module': current['source'],
        'current_revision': current['revision'],
        # The provider's own words about what is broken right now.
        'failing_calls': [
            {'model': model_id, 'error': error[:400]}
            for model_id, error in list(failures.items())[:12]
        ],
    }


def author_adapter(
    *,
    user,
    profile: UserProfile,
    provider: str,
    token: str,
    live_ids: list[str],
    baseline_failures: dict[str, str],
    probe_models: list[str],
    seconds_left: float,
    on_stage=None,
) -> dict[str, Any]:
    """Have a capable model write the connection module, then prove it works.

    A revision is activated only when it answers live provider calls at least as
    often as the path in use today. Anything else is stored for inspection with
    status ``rejected`` and changes nothing.
    """
    skipped = {'status': 'skipped', 'author_model': None, 'revision': None,
               'activated': False, 'verified_models': [], 'failures': {}, 'summary': '', 'problems': []}
    if not getattr(settings, 'PROVIDER_ADAPTER_AUTHORING', True):
        return {**skipped, 'reason': 'Adapter authoring is disabled on this server.'}
    if seconds_left < settings.PROVIDER_ADAPTER_LLM_TIMEOUT_SECONDS + 20:
        return {**skipped, 'reason': 'Not enough time left in this request to rewrite the connection module.'}
    selected = select_author_model(profile)
    if selected is None:
        return {**skipped, 'reason': 'No saved API key can reach a model capable of writing the connection module.'}
    author_model, author_token = selected

    current = _current_adapter_summary(provider)
    baseline_passed = [model_id for model_id in probe_models if model_id not in baseline_failures]
    # Plain substitution, not str.format: the prompt is full of literal JSON braces.
    system_prompt = (
        ADAPTER_AUTHOR_PROMPT
        .replace('__ALLOWED_IMPORTS__', ', '.join(sorted(ALLOWED_IMPORTS)))
        .replace('__MAX_LINES__', str(MAX_SOURCE_LINES))
        .replace('__MAX_CHARS__', str(MAX_SOURCE_CHARS))
    )
    request = _authoring_request(provider=provider, live_ids=live_ids, failures=baseline_failures, current=current)
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)},
    ]

    source = summary = ''
    notes: dict[str, Any] = {}
    report = None
    attempts = 0
    deadline = time.monotonic() + seconds_left
    # One repair round: screening problems are precise, and a model that broke a
    # sandbox rule usually fixes it when told exactly which line broke it.
    while attempts < 2:
        attempts += 1
        try:
            payload = _run_catalog_llm(
                user=user, model=author_model, token=author_token, messages=messages,
                timeout=settings.PROVIDER_ADAPTER_LLM_TIMEOUT_SECONDS,
            )
            source, summary, notes = _extract_module(payload)
        except Exception as exc:
            return {**skipped, 'status': 'failed', 'author_model': author_model,
                    'reason': f'The adapter author failed: {str(exc)[:240]}'}
        report = screen_source(source, provider)
        if report.ok:
            break
        if time.monotonic() + settings.PROVIDER_ADAPTER_LLM_TIMEOUT_SECONDS + 15 > deadline:
            break
        messages = messages + [
            {'role': 'assistant', 'content': json.dumps({'module': source, 'summary': summary}, ensure_ascii=False)},
            {'role': 'user', 'content': 'The module was rejected by the sandbox screener. Fix exactly these problems '
                                        'and return the whole corrected module in the same JSON shape:\n'
                                        + '\n'.join(f'- {problem}' for problem in report.problems[:12])},
        ]

    latest = RouterAdapter.objects.filter(provider=provider).aggregate(top=Max('revision'))['top'] or 0
    record = RouterAdapter.objects.create(
        provider=provider,
        revision=latest + 1,
        status=RouterAdapter.Status.REJECTED,
        source_code=source,
        author_model=author_model,
        screening=report.as_dict() if report else {},
        notes=summary,
        created_by=user if getattr(user, 'pk', None) else None,
    )
    if report is None or not report.ok:
        return {**skipped, 'status': 'rejected', 'author_model': author_model, 'revision': record.revision,
                'summary': summary, 'problems': report.problems[:8] if report else [],
                'reason': 'The generated module did not pass sandbox screening.'}

    try:
        namespace = compile_adapter(source, provider, revision=record.revision)
    except AdapterError as exc:
        record.screening = {**record.screening, 'load_error': str(exc)[:400]}
        record.save(update_fields=['screening', 'updated_at'])
        return {**skipped, 'status': 'rejected', 'author_model': author_model, 'revision': record.revision,
                'summary': summary, 'reason': str(exc)[:240]}

    if on_stage is not None:
        on_stage('verifying')
    passed, failures = probe_with_adapter(namespace, provider=provider, api_models=probe_models, token=token)
    record.canary = {'passed': passed, 'failed': failures, 'baseline_passed': baseline_passed,
                     'model_notes': {str(key)[:120]: str(value)[:300] for key, value in list(notes.items())[:20]}}
    activated = bool(passed) and len(passed) >= len(baseline_passed)
    if activated:
        record.save(update_fields=['canary', 'updated_at'])
        activate_revision(record)
    else:
        record.save(update_fields=['canary', 'updated_at'])
    return {
        'status': 'activated' if activated else 'rejected',
        'author_model': author_model,
        'author_rank': capability_rank(author_model),
        'revision': record.revision,
        'activated': activated,
        'verified_models': passed,
        'failures': failures,
        'baseline_verified_models': baseline_passed,
        'summary': summary,
        'problems': [],
        'attempts': attempts,
        'reason': '' if activated else
                  f'The new module answered {len(passed)} of {len(probe_models)} probes; the module in use answered '
                  f'{len(baseline_passed)}. It was kept for inspection but not activated.',
    }


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


def update_provider_catalog(
    *,
    user,
    profile: UserProfile,
    provider: str,
    on_stage=None,
) -> dict[str, Any]:
    """Run one full provider check.

    ``on_stage`` receives a ProviderCheckJob.Stage value as each phase begins so
    a queued check can report progress while the client polls.
    """
    def stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    if provider not in PROVIDER_SPECS:
        raise KeyError(provider)
    encrypted = (profile.provider_tokens_encrypted or {}).get(provider, '')
    token = decrypt_secret(encrypted)
    if not token:
        raise LlmConfigurationError(
            f'No {PROVIDER_SPECS[provider].token_label} is saved. Save the provider key before checking for updates.'
        )

    started = time.monotonic()
    budget = float(settings.PROVIDER_UPDATE_BUDGET_SECONDS)
    stage('discovering')
    live_ids = discover_provider_models(provider, token)
    current = [item for item in model_catalog(profile) if item['token_provider'] == provider]

    # The catalog pass and the compatibility probe are independent network work,
    # so they run side by side.
    stage('probing')
    baseline_candidates = _catalog_entries(provider, live_ids[:_CANARY_MODEL_LIMIT], [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        catalog_future = pool.submit(
            enrich_catalog_with_ai,
            user=user, profile=profile, provider=provider, live_ids=live_ids, current=current,
        )
        canary_future = pool.submit(canary_models, baseline_candidates, token)
        enriched, source_model, ai_runs = catalog_future.result()
        verified, canary_errors = canary_future.result()

    proposed = _catalog_entries(provider, live_ids, enriched)
    verified_ids = [item['id'] for item in verified]
    canary_candidates = baseline_candidates

    # Rewriting the connection module is the point of a check: a renamed or
    # reshaped API shows up here as concrete provider errors to fix.
    probe_models = [api_model_name(item['id']) for item in baseline_candidates]
    stage('authoring')
    adapter = author_adapter(
        user=user,
        profile=profile,
        provider=provider,
        token=token,
        live_ids=live_ids,
        baseline_failures={api_model_name(model_id): error for model_id, error in canary_errors.items()},
        probe_models=probe_models,
        seconds_left=budget - (time.monotonic() - started),
        on_stage=on_stage,
    )
    stage('saving')
    if adapter.get('activated'):
        # The freshly activated module is the connection in use now, so the
        # models it proved are the ones worth reporting as verified.
        verified_ids = [f'{provider}:{api_model}' for api_model in adapter['verified_models']]
        canary_errors = {f'{provider}:{api_model}': error for api_model, error in adapter['failures'].items()}
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
        'adapter': adapter,
        'elapsed_seconds': round(time.monotonic() - started, 1),
        'migrated_settings': migrated,
        'profile': activated,
    }


def run_provider_check(job_id) -> None:
    """Execute one queued check. Called by the durable worker, never by a view.

    Every outcome is written back to the job row, including failures, so the
    polling client always gets a definite answer instead of a stuck spinner.
    """
    from learning.models import ProviderCheckJob

    job = ProviderCheckJob.objects.select_related('user').filter(pk=job_id).first()
    if job is None:
        return

    def set_stage(name: str) -> None:
        ProviderCheckJob.objects.filter(pk=job.pk).update(
            stage=name, heartbeat_at=timezone.now(), updated_at=timezone.now(),
        )

    try:
        profile, _ = UserProfile.objects.get_or_create(user=job.user)
        result = update_provider_catalog(
            user=job.user, profile=profile, provider=job.provider, on_stage=set_stage,
        )
        result.pop('profile', None)
        ProviderCheckJob.objects.filter(pk=job.pk).update(
            status=ProviderCheckJob.Status.COMPLETED,
            stage=ProviderCheckJob.Stage.SAVING,
            result=result,
            error='',
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            updated_at=timezone.now(),
        )
    except Exception as exc:
        ProviderCheckJob.objects.filter(pk=job.pk).update(
            status=ProviderCheckJob.Status.FAILED,
            error=str(exc)[:2000],
            finished_at=timezone.now(),
            heartbeat_at=timezone.now(),
            updated_at=timezone.now(),
        )
