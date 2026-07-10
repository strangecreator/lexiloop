from __future__ import annotations

from typing import Any

# Curated public models only. Internal Yandex/VPN-only endpoints are intentionally
# excluded because the production server cannot reach them.
MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        'id': 'external:deepseek-chat',
        'label': 'DeepSeek Chat',
        'provider': 'DeepSeek',
        'description': 'Fast and cost-efficient general model. A strong default for flashcard generation and judging.',
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
        'id': 'external:deepseek-reasoner',
        'label': 'DeepSeek Reasoner',
        'provider': 'DeepSeek',
        'description': 'More deliberate reasoning. Usually slower and more expensive than DeepSeek Chat.',
        'token_label': 'DeepSeek API key',
        'token_provider': 'deepseek',
        'recommended_for': ['generation'],
        'badge': 'Reasoning',
        'key_url': 'https://platform.deepseek.com/api_keys',
    },
    {
        'id': 'external:xiaomi-mimo',
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

# One API key per provider account. Every catalog model maps to one of these,
# so switching models never requires re-entering a key that is already saved.
TOKEN_PROVIDERS: dict[str, str] = {
    'deepseek': 'DeepSeek',
    'openai': 'OpenAI',
    'openrouter': 'OpenRouter',
    'xiaomi': 'Xiaomi',
}


def model_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in MODEL_CATALOG]


def token_provider_for(model_id: str) -> str | None:
    for item in MODEL_CATALOG:
        if item['id'] == model_id:
            return item['token_provider']
    return None


def is_supported_model(model_id: str) -> bool:
    return model_id in MODEL_IDS


def model_entry(model_id: str) -> dict[str, Any] | None:
    for item in MODEL_CATALOG:
        if item['id'] == model_id:
            return dict(item)
    return None
