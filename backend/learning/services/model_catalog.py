from __future__ import annotations

import re
from typing import Any

# Curated public models only. Internal Yandex/VPN-only endpoints are intentionally
# excluded because the production server cannot reach them.
MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        'id': 'deepseek:deepseek-v4-flash',
        'label': 'DeepSeek V4 Flash',
        'provider': 'DeepSeek',
        'description': 'Fast, economical V4 model in non-thinking mode. The best DeepSeek default for flashcard generation and judging.',
        'token_label': 'DeepSeek API key',
        'token_provider': 'deepseek',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Recommended',
        'key_url': 'https://platform.deepseek.com/api_keys',
    },
    {
        'id': 'openai:gpt-5.4-mini',
        'label': 'GPT-5.4 mini',
        'provider': 'OpenAI',
        'description': 'Strong low-latency OpenAI mini model for high-volume card generation and semantic judging.',
        'token_label': 'OpenAI API key',
        'token_provider': 'openai',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Fast',
        'key_url': 'https://platform.openai.com/api-keys',
    },
    {
        'id': 'openai:gpt-5.4-nano',
        'label': 'GPT-5.4 nano',
        'provider': 'OpenAI',
        'description': 'Cheapest GPT-5.4-class model for very fast simple checks and lightweight generation.',
        'token_label': 'OpenAI API key',
        'token_provider': 'openai',
        'recommended_for': ['judge', 'generation'],
        'badge': 'Fastest',
        'key_url': 'https://platform.openai.com/api-keys',
    },
    {
        'id': 'openai:gpt-5-mini',
        'label': 'GPT-5 mini',
        'provider': 'OpenAI',
        'description': 'Cost-efficient OpenAI model for precise, well-defined tasks.',
        'token_label': 'OpenAI API key',
        'token_provider': 'openai',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Low latency',
        'key_url': 'https://platform.openai.com/api-keys',
    },
    {
        'id': 'openai:gpt-5-nano',
        'label': 'GPT-5 nano',
        'provider': 'OpenAI',
        'description': 'Smallest GPT-5-class model for very low-latency semantic checks.',
        'token_label': 'OpenAI API key',
        'token_provider': 'openai',
        'recommended_for': ['judge'],
        'badge': 'Tiny',
        'key_url': 'https://platform.openai.com/api-keys',
    },
    {
        'id': 'deepseek:deepseek-v4-pro',
        'label': 'DeepSeek V4 Pro',
        'provider': 'DeepSeek',
        'description': 'DeepSeek’s most capable V4 model with thinking enabled. Slower and more expensive than V4 Flash.',
        'token_label': 'DeepSeek API key',
        'token_provider': 'deepseek',
        'recommended_for': ['generation'],
        'badge': 'Reasoning',
        'key_url': 'https://platform.deepseek.com/api_keys',
    },
    {
        'id': 'anthropic:claude-haiku-4-5',
        'label': 'Claude Haiku 4.5',
        'provider': 'Anthropic',
        'description': 'Anthropic\u2019s fastest and most cost-effective model \u2014 excellent for judging and quick generation.',
        'token_label': 'Anthropic API key',
        'token_provider': 'anthropic',
        'recommended_for': ['judge', 'generation'],
        'badge': 'Fast & cheap',
        'key_url': 'https://console.anthropic.com/settings/keys',
    },
    {
        'id': 'anthropic:claude-sonnet-5',
        'label': 'Claude Sonnet 5',
        'provider': 'Anthropic',
        'description': 'Near-flagship quality at mid-tier cost. A strong all-round choice for generation and judging.',
        'token_label': 'Anthropic API key',
        'token_provider': 'anthropic',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Balanced',
        'key_url': 'https://console.anthropic.com/settings/keys',
    },
    {
        'id': 'anthropic:claude-opus-4-8',
        'label': 'Claude Opus 4.8',
        'provider': 'Anthropic',
        'description': 'Anthropic\u2019s most capable Opus-tier model for the richest card generation.',
        'token_label': 'Anthropic API key',
        'token_provider': 'anthropic',
        'recommended_for': ['generation'],
        'badge': 'Most capable',
        'key_url': 'https://console.anthropic.com/settings/keys',
    },
    {
        'id': 'xiaomi:mimo-v2-flash',
        'label': 'MiMo-V2-Flash',
        'provider': 'Xiaomi',
        'description': 'Fast public Xiaomi model with reasoning support.',
        'token_label': 'Xiaomi MiMo API key',
        'token_provider': 'xiaomi',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Fast',
        'key_url': None,
    },
    {
        'id': 'openrouter:openai/gpt-5.2',
        'label': 'GPT-5.2 [OpenRouter]',
        'provider': 'OpenRouter · OpenAI',
        'description': 'Frontier general-purpose OpenAI model routed through OpenRouter.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Frontier',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:openai/gpt-5-mini',
        'label': 'GPT-5 mini [OpenRouter]',
        'provider': 'OpenRouter · OpenAI',
        'description': 'OpenAI GPT-5 mini through OpenRouter when a unified OpenRouter key is preferred.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Low latency',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:anthropic/claude-sonnet-4.6',
        'label': 'Claude Sonnet 4.6 [OpenRouter]',
        'provider': 'OpenRouter · Anthropic',
        'description': 'High-quality language understanding and careful instruction following.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Frontier',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:google/gemini-3.1-pro-preview',
        'label': 'Gemini 3.1 Pro Preview [OpenRouter]',
        'provider': 'OpenRouter · Google',
        'description': 'Large-context reasoning model routed through OpenRouter.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation'],
        'badge': 'Reasoning',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:google/gemini-3-flash-preview',
        'label': 'Gemini 3 Flash Preview [OpenRouter]',
        'provider': 'OpenRouter · Google',
        'description': 'Lower-latency Gemini model suitable for semantic judging.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['judge'],
        'badge': 'Fast',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:moonshotai/kimi-k2.6',
        'label': 'Kimi K2.6 [OpenRouter]',
        'provider': 'OpenRouter · MoonshotAI',
        'description': 'Long-context Kimi model with strong instruction following.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Long context',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:deepseek/deepseek-v3.2',
        'label': 'DeepSeek V3.2 [OpenRouter]',
        'provider': 'OpenRouter · DeepSeek',
        'description': 'DeepSeek V3.2 through OpenRouter with provider failover.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Value',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
    {
        'id': 'openrouter:xiaomi/mimo-v2-flash',
        'label': 'MiMo-V2-Flash [OpenRouter]',
        'provider': 'OpenRouter · Xiaomi',
        'description': 'MiMo through OpenRouter, useful when a unified OpenRouter key is preferred.',
        'token_label': 'OpenRouter API key',
        'token_provider': 'openrouter',
        'recommended_for': ['generation', 'judge'],
        'badge': 'Value',
        'key_url': 'https://openrouter.ai/settings/keys',
    },
)

MODEL_IDS = frozenset(item['id'] for item in MODEL_CATALOG)
MODEL_ID_RE = re.compile(r'^[A-Za-z0-9._:/-]{1,200}$')

# One API key per provider account. Every catalog model maps to one of these,
# so switching models never requires re-entering a key that is already saved.
TOKEN_PROVIDERS: dict[str, str] = {
    'deepseek': 'DeepSeek',
    'openai': 'OpenAI',
    'anthropic': 'Anthropic',
    'openrouter': 'OpenRouter',
    'xiaomi': 'Xiaomi',
}

# Old profile values remain routable during rolling deploys and are migrated by
# learning.0014. They are deliberately absent from the public picker.
LEGACY_MODEL_ALIASES: dict[str, str] = {
    'external:deepseek-chat': 'deepseek:deepseek-v4-flash',
    'external:deepseek-reasoner': 'deepseek:deepseek-v4-pro',
    'external:xiaomi-mimo': 'xiaomi:mimo-v2-flash',
}

PROVIDER_PREFIXES: dict[str, str] = {
    'deepseek': 'deepseek',
    'openai': 'openai',
    'anthropic': 'anthropic',
    'openrouter': 'openrouter',
    'xiaomi': 'xiaomi',
}


def canonical_model_id(model_id: str) -> str:
    return LEGACY_MODEL_ALIASES.get(model_id, model_id)


def api_model_name(model_id: str) -> str:
    canonical = canonical_model_id(model_id)
    return canonical.split(':', 1)[1] if ':' in canonical else canonical


def request_config_for(model_id: str) -> dict[str, Any]:
    """Return the small, code-owned request policy for a catalog model.

    Provider updates may discover IDs and ask an LLM to describe them, but an
    LLM is never allowed to inject arbitrary URLs, headers, payloads, or code.
    These declarative policies are derived locally and handled only by the
    built-in allowlisted adapters.
    """
    canonical = canonical_model_id(model_id)
    provider = token_provider_for(canonical)
    api_model = api_model_name(canonical).lower()
    if provider == 'deepseek':
        if 'pro' in api_model or 'reason' in api_model:
            return {
                'remove_parameters': ['temperature', 'top_p', 'presence_penalty', 'frequency_penalty'],
                'extra_parameters': {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'},
            }
        return {'extra_parameters': {'thinking': {'type': 'disabled'}}}
    if provider == 'openai' and api_model.startswith(('gpt-5', 'o')):
        return {'remove_parameters': ['temperature']}
    return {}


def _safe_override_models(profile: Any | None, provider: str) -> list[dict[str, Any]]:
    raw_updates = getattr(profile, 'provider_catalog_overrides', {}) if profile is not None else {}
    raw = raw_updates.get(provider, {}) if isinstance(raw_updates, dict) else {}
    models = raw.get('models', []) if isinstance(raw, dict) else []
    if not isinstance(models, list):
        return []
    built_in = next(item for item in MODEL_CATALOG if item['token_provider'] == provider)
    safe: list[dict[str, Any]] = []
    for item in models[:24]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id') or '')
        if not MODEL_ID_RE.fullmatch(model_id) or token_provider_for(model_id) != provider:
            continue
        recommended = item.get('recommended_for')
        if not isinstance(recommended, list):
            recommended = []
        recommended = [role for role in ('generation', 'judge') if role in recommended]
        if not recommended:
            recommended = ['generation', 'judge']
        safe.append({
            'id': model_id,
            'label': str(item.get('label') or api_model_name(model_id))[:120],
            'provider': TOKEN_PROVIDERS[provider],
            'description': str(item.get('description') or 'Discovered from the provider API and verified by LexiLoop.')[:500],
            'token_label': built_in['token_label'],
            'token_provider': provider,
            'recommended_for': recommended,
            'badge': str(item.get('badge') or 'API verified')[:40],
            'key_url': built_in['key_url'],
        })
    return safe


def model_catalog(profile: Any | None = None) -> list[dict[str, Any]]:
    """Return the built-in catalog merged with this account's verified updates."""
    catalog = [dict(item) for item in MODEL_CATALOG]
    for provider in TOKEN_PROVIDERS:
        override = _safe_override_models(profile, provider)
        if override:
            catalog = [item for item in catalog if item['token_provider'] != provider]
            catalog.extend(override)
    return catalog


def token_provider_for(model_id: str) -> str | None:
    if model_id in LEGACY_MODEL_ALIASES:
        model_id = LEGACY_MODEL_ALIASES[model_id]
    prefix = model_id.split(':', 1)[0] if ':' in model_id else ''
    if prefix in PROVIDER_PREFIXES:
        return PROVIDER_PREFIXES[prefix]
    for item in MODEL_CATALOG:
        if item['id'] == model_id:
            return item['token_provider']
    return None


def is_supported_model(model_id: str, profile: Any | None = None) -> bool:
    canonical = canonical_model_id(model_id)
    return any(item['id'] == canonical for item in model_catalog(profile))


def model_entry(model_id: str, profile: Any | None = None) -> dict[str, Any] | None:
    canonical = canonical_model_id(model_id)
    for item in model_catalog(profile):
        if item['id'] == canonical:
            return dict(item)
    return None
