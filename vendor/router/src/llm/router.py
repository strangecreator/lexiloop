import os
import re
import time
import json
import pathlib
import typing as tp
from functools import lru_cache
from dataclasses import dataclass

BASE_DIR = pathlib.Path(__file__).parents[2]

# aiohttp & related imports
import asyncio
import aiohttp
import requests

# local imports
import tools
from .. import auth, exceptions, utils
from . import zeliboba
from . import xiaomi_mimo
from . import deepseek_chat
from . import alice_32b_latest
from . import internal_gpt_5_2
from . import deepseek_reasoner
from . import internal_deepseek_ai_r1
from . import internal_gpt_5_openrouter
from . import internal_yandex_gpt_5_pro
from . import internal_claude_sonnet_4_5
from . import internal_yandex_gpt_5_lite
from . import internal_alice_ai_llm_235b
from . import internal_deepseek_reasoner
from . import internal_gpt_5_2_openrouter
from . import internal_deepseek_reasoner_openrouter
from . import internal_deepseek_v3_1_terminus_batch


Json = dict[str, tp.Any]
PostFunc = tp.Callable[
    [aiohttp.ClientSession, Json, int, str | None, str | None],
    tp.Awaitable[Json],
]


@dataclass(frozen=True)
class Resolver:
    pattern: re.Pattern[str]
    provider_factory: tp.Callable[[re.Match[str]], PostFunc]


class ModelRegistry:
    def __init__(self) -> None:
        self._exact: dict[str, PostFunc] = {}
        self._resolvers: list[Resolver] = []

    def register(self, model_id: str, handler: PostFunc) -> None:
        self._exact[model_id] = handler
    
    def register_multiple(self, mapping: dict[str, PostFunc]) -> None:
        tools.extend_dict(self._exact, mapping, inplace=True, override=True)

    def register_regex(
        self,
        pattern: str,
        provider_factory: tp.Callable[[re.Match[str]], PostFunc],
    ) -> None:
        self._resolvers.append(Resolver(re.compile(pattern), provider_factory))

    def get(self, model_name: str) -> PostFunc:
        post_func = self._exact.get(model_name)

        if post_func is not None:
            return post_func

        for resolver in self._resolvers:
            match = resolver.pattern.fullmatch(model_name)
            if match:
                return resolver.provider_factory(match)()

        raise KeyError(f"Unknown model_name: `{model_name}`.")


def _apply_model_config(
    payload: dict[str, tp.Any],
    model_config: dict[str, tp.Any] | None,
) -> dict[str, tp.Any]:
    """Apply only the declarative request controls supported by the router.

    The application derives this config from an allowlisted provider adapter.
    Keeping a second allowlist here prevents a malformed database row from
    becoming an arbitrary provider payload.
    """
    configured = dict(payload)
    if not isinstance(model_config, dict):
        return configured
    removable = {"temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty"}
    remove = model_config.get("remove_parameters")
    if isinstance(remove, list):
        for key in remove:
            if key in removable:
                configured.pop(key, None)
    extra = model_config.get("extra_parameters")
    if isinstance(extra, dict):
        thinking = extra.get("thinking")
        if (
            isinstance(thinking, dict)
            and thinking.get("type") in {"enabled", "disabled"}
        ):
            configured["thinking"] = {"type": thinking["type"]}
        effort = extra.get("reasoning_effort")
        if effort in {"high", "max"}:
            configured["reasoning_effort"] = effort
    return configured


def _safe_response_stats(
    response_data: dict[str, tp.Any],
    summarizer: tp.Callable[..., dict[str, tp.Any]],
) -> dict[str, tp.Any]:
    """Keep a successful completion successful when usage telemetry changes."""
    try:
        return summarizer(response_data, decimals=False)
    except Exception:
        usage = response_data.get("usage")
        usage = dict(usage) if isinstance(usage, dict) else {}
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if isinstance(prompt, (int, float)):
            usage.setdefault("input_tokens", prompt)
        if isinstance(completion, (int, float)):
            usage.setdefault("output_tokens", completion)
        if "total_tokens" not in usage and isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
            usage["total_tokens"] = prompt + completion
        usage.setdefault("total_price", 0)
        return usage


async def deepseek_chat_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,  # ignored
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        auth._ensure_env_loaded()
        token = os.getenv("EXTERNAL_DEEPSEEK_AUTH_TOKEN")

    URL = "https://api.deepseek.com/chat/completions"
    HEADERS = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = tools.extend_dict({
        "model": "deepseek-chat",
        "stream": False,
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await deepseek_chat.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = deepseek_chat.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["choices"][0]["message"]["content"],
            "reasoning_content": None,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def deepseek_reasoner_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,  # ignored
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        auth._ensure_env_loaded()
        token = os.getenv("EXTERNAL_DEEPSEEK_AUTH_TOKEN")

    URL = "https://api.deepseek.com/chat/completions"
    HEADERS = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = tools.extend_dict({
        "model": "deepseek-reasoner",
        "stream": False,
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await deepseek_reasoner.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = deepseek_reasoner.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["choices"][0]["message"]["content"],
            "reasoning_content": response_data["choices"][0]["message"]["reasoning_content"],
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


@lru_cache(maxsize=64)
def deepseek_post_provider(model_name: str) -> PostFunc:
    async def deepseek_post(
        session: aiohttp.ClientSession,
        payload: dict[str, tp.Any],
        timeout: int = 300,
        pool: str | None = None,  # ignored
        token: str | None = None,
        model_config: dict[str, tp.Any] | None = None,
        **kwargs,
    ) -> dict[str, tp.Any]:
        if token is None:
            auth._ensure_env_loaded()
            token = os.getenv("EXTERNAL_DEEPSEEK_AUTH_TOKEN")
        if not token:
            raise ValueError("A DeepSeek API key is required for this model.")

        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload_extended = tools.extend_dict({
            "model": model_name,
            "stream": False,
        }, _apply_model_config(payload, model_config), inplace=False, override=False)

        start_time = time.perf_counter()
        response_data = await utils.post_strict_safe_fixed_utf_8(
            session, url, headers, payload_extended, timeout=timeout, **kwargs
        )
        elapsed_time = time.perf_counter() - start_time

        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"DeepSeek returned no choices: {response_data}")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise RuntimeError(f"DeepSeek returned no textual content: {response_data}")
        stats_module = deepseek_reasoner if "pro" in model_name.lower() else deepseek_chat
        stats = _safe_response_stats(response_data, stats_module.summarize_response_stats)
        return {
            "response": response_data,
            "content": message["content"],
            "reasoning_content": message.get("reasoning_content"),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }

    return deepseek_post


async def xiaomi_mimo_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,  # ignored
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        auth._ensure_env_loaded()
        token = os.getenv("EXTERNAL_XIAOMI_MIMO_AUTH_TOKEN")

    URL = "https://api.xiaomimimo.com/v1/chat/completions"
    HEADERS = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = tools.extend_dict({
        "model": "mimo-v2-flash",
        "stream": False,
        "thinking": {"type": "enabled"},
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await xiaomi_mimo.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = xiaomi_mimo.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["choices"][0]["message"]["content"],
            "reasoning_content": response_data["choices"][0]["message"]["reasoning_content"],
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


@lru_cache(maxsize=64)
def xiaomi_post_provider(model_name: str) -> PostFunc:
    async def xiaomi_post(
        session: aiohttp.ClientSession,
        payload: dict[str, tp.Any],
        timeout: int = 300,
        pool: str | None = None,  # ignored
        token: str | None = None,
        model_config: dict[str, tp.Any] | None = None,
        **kwargs,
    ) -> dict[str, tp.Any]:
        if token is None:
            auth._ensure_env_loaded()
            token = os.getenv("EXTERNAL_XIAOMI_MIMO_AUTH_TOKEN")
        if not token:
            raise ValueError("A Xiaomi MiMo API key is required for this model.")

        url = "https://api.xiaomimimo.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload_extended = tools.extend_dict({
            "model": model_name,
            "stream": False,
        }, _apply_model_config(payload, model_config), inplace=False, override=False)

        start_time = time.perf_counter()
        response_data = await utils.post_strict_safe_fixed_utf_8(
            session, url, headers, payload_extended, timeout=timeout, **kwargs
        )
        elapsed_time = time.perf_counter() - start_time
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"Xiaomi returned no choices: {response_data}")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise RuntimeError(f"Xiaomi returned no textual content: {response_data}")
        stats = _safe_response_stats(response_data, xiaomi_mimo.summarize_response_stats)
        return {
            "response": response_data,
            "content": message["content"],
            "reasoning_content": message.get("reasoning_content") or message.get("reasoning"),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }

    return xiaomi_post


@lru_cache(maxsize=256)
def openrouter_post_provider(model_name: str) -> PostFunc:
    async def openrouter_post(
        session: aiohttp.ClientSession,
        payload: dict[str, tp.Any],
        timeout: int = 300,
        pool: str | None = None,  # ignored
        token: str | None = None,
        model_config: dict[str, tp.Any] | None = None,
        **kwargs,
    ) -> dict[str, tp.Any]:
        if token is None:
            auth._ensure_env_loaded()
            token = os.getenv("OPENROUTER_API_KEY")
        if not token:
            raise ValueError("An OpenRouter API key is required for this model.")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "https://lexiloop.ru"),
            "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_TITLE", "LexiLoop"),
        }
        payload_extended = tools.extend_dict({
            "model": model_name,
            "stream": False,
        }, _apply_model_config(payload, model_config), inplace=False, override=False)

        start_time = time.perf_counter()
        response_data = await utils.post_strict_safe_fixed_utf_8(
            session, url, headers, payload_extended, timeout=timeout, **kwargs
        )
        elapsed_time = time.perf_counter() - start_time

        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"OpenRouter returned no choices: {response_data}")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise RuntimeError(f"OpenRouter returned no message: {response_data}")
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"OpenRouter returned no textual content: {response_data}")

        usage = response_data.get("usage") if isinstance(response_data.get("usage"), dict) else {}
        stats = dict(usage)
        if isinstance(usage.get("cost"), (int, float, str)):
            stats["total_price"] = usage["cost"]
        return {
            "response": response_data,
            "content": content,
            "reasoning_content": message.get("reasoning_content") or message.get("reasoning"),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }

    return openrouter_post


@lru_cache(maxsize=256)
def openai_post_provider(model_name: str) -> PostFunc:
    def error_message(exc: exceptions.HTTPStatusError) -> str:
        error = exc.body.get("error") if isinstance(exc.body, dict) else None
        return str(error.get("message") or "").casefold() if isinstance(error, dict) else ""

    def requires_responses_api(exc: exceptions.HTTPStatusError) -> bool:
        message = error_message(exc)
        return exc.status in {400, 404} and (
            "v1/responses" in message
            or "not supported in v1/chat/completions" in message
            or "not a chat model" in message
        )

    def responses_payload(chat_payload: dict[str, tp.Any]) -> dict[str, tp.Any]:
        converted: dict[str, tp.Any] = {
            "model": chat_payload["model"],
            "input": chat_payload.get("messages", []),
            "stream": False,
        }
        max_output = chat_payload.get("max_completion_tokens", chat_payload.get("max_tokens"))
        if isinstance(max_output, int) and max_output > 0:
            converted["max_output_tokens"] = max_output
        effort = chat_payload.get("reasoning_effort")
        if isinstance(effort, str):
            converted["reasoning"] = {"effort": effort}
        # This adapter intentionally converts only the fields LexiLoop owns.
        # Arbitrary provider payload keys cannot cross endpoint boundaries.
        return converted

    def responses_content(response_data: dict[str, tp.Any]) -> str:
        direct = response_data.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        parts: list[str] = []
        output = response_data.get("output")
        if isinstance(output, list):
            for item in output:
                content = item.get("content") if isinstance(item, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if block.get("type") == "output_text" and isinstance(text, str):
                        parts.append(text)
        return "".join(parts)

    async def openai_post(
        session: aiohttp.ClientSession,
        payload: dict[str, tp.Any],
        timeout: int = 300,
        pool: str | None = None,  # ignored
        token: str | None = None,
        model_config: dict[str, tp.Any] | None = None,
        **kwargs,
    ) -> dict[str, tp.Any]:
        if token is None:
            auth._ensure_env_loaded()
            token = os.getenv("OPENAI_API_KEY")
        if not token:
            raise ValueError("An OpenAI API key is required for this model.")

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload_extended = tools.extend_dict({
            "model": model_name,
            "stream": False,
        }, _apply_model_config(payload, model_config), inplace=False, override=False)

        # Some lightweight OpenAI models are strict about supported sampling
        # parameters. Keep user prompts identical, but avoid failing because of
        # an optional temperature field added by LexiLoop.
        if str(model_name).startswith(("gpt-5", "o")):
            payload_extended.pop("temperature", None)
            max_tokens = payload_extended.pop("max_tokens", None)
            if isinstance(max_tokens, int) and "max_completion_tokens" not in payload_extended:
                payload_extended["max_completion_tokens"] = max_tokens

        start_time = time.perf_counter()
        used_responses_api = False
        try:
            response_data = await utils.post_strict_safe_fixed_utf_8(
                session, url, headers, payload_extended, timeout=timeout, **kwargs
            )
        except exceptions.HTTPStatusError as exc:
            if not requires_responses_api(exc):
                raise
            used_responses_api = True
            response_data = await utils.post_strict_safe_fixed_utf_8(
                session,
                "https://api.openai.com/v1/responses",
                headers,
                responses_payload(payload_extended),
                timeout=timeout,
                **kwargs,
            )
        elapsed_time = time.perf_counter() - start_time

        message: dict[str, tp.Any] = {}
        if used_responses_api:
            content = responses_content(response_data)
        else:
            choices = response_data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise RuntimeError(f"OpenAI returned no choices: {response_data}")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if not isinstance(message, dict):
                raise RuntimeError(f"OpenAI returned no message: {response_data}")
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"OpenAI returned no textual content: {response_data}")

        usage = response_data.get("usage") if isinstance(response_data.get("usage"), dict) else {}
        stats = dict(usage)
        return {
            "response": response_data,
            "content": content,
            "reasoning_content": message.get("reasoning_content") or message.get("reasoning"),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }

    return openai_post


def anthropic_post_provider(model_name: str) -> PostFunc:
    """Direct Anthropic Messages API (https://api.anthropic.com/v1/messages)."""
    from decimal import Decimal

    # $ per token: (input, output). Cache reads bill at 0.1x input,
    # cache writes (5m TTL) at 1.25x input.
    ANTHROPIC_PRICES = {
        "claude-haiku-4-5": (Decimal("0.000001"), Decimal("0.000005")),
        "claude-sonnet-5": (Decimal("0.000003"), Decimal("0.000015")),
        "claude-opus-4-8": (Decimal("0.000005"), Decimal("0.000025")),
    }

    async def anthropic_post(
        session: aiohttp.ClientSession,
        payload: dict[str, tp.Any],
        timeout: int = 300,
        pool: str | None = None,  # ignored
        token: str | None = None,
        model_config: dict[str, tp.Any] | None = None,
        **kwargs,
    ) -> dict[str, tp.Any]:
        if token is None:
            auth._ensure_env_loaded()
            token = os.getenv("ANTHROPIC_API_KEY")
        if not token:
            raise ValueError("An Anthropic API key is required for this model.")

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload_extended = tools.extend_dict({
            "model": model_name,
            "stream": False,
            "max_tokens": 4096,  # required by the Messages API
        }, _apply_model_config(payload, model_config), inplace=False, override=False)

        # Opus 4.7+ and Sonnet 5 reject sampling parameters outright (400);
        # Haiku 4.5 still accepts them. Keep user prompts identical, but do
        # not fail because of an optional temperature field added by LexiLoop.
        if not str(model_name).startswith("claude-haiku"):
            for key in ("temperature", "top_p", "top_k"):
                payload_extended.pop(key, None)

        # Reuse the Anthropic payload converter (system messages move to the
        # top-level `system` field) and the content-block response parser.
        payload_extended = internal_claude_sonnet_4_5.to_antropic_payload(payload_extended)

        start_time = time.perf_counter()
        raw = await utils.post_strict_safe_fixed_utf_8(
            session, url, headers, payload_extended, timeout=timeout, **kwargs
        )
        elapsed_time = time.perf_counter() - start_time

        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        input_price, output_price = ANTHROPIC_PRICES.get(model_name, (Decimal("0"), Decimal("0")))
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
        cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
        total_price = (
            input_tokens * input_price
            + output_tokens * output_price
            + cache_read_tokens * input_price / 10
            + cache_write_tokens * input_price * Decimal("1.25")
        )
        stats = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "total_tokens": input_tokens + output_tokens,
            "total_price": float(total_price),
        }

        parsed = internal_claude_sonnet_4_5.parse_response({"response": raw})
        return tools.extend_dict({
            "stats": stats,
            "elapsed_time": elapsed_time,
        }, parsed, inplace=True, deepcopy=False)

    return anthropic_post


async def eliza_deepseek_reasoner_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/deepseek/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = tools.extend_dict({
        "model": "deepseek-reasoner",
        "stream": False,
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await internal_deepseek_reasoner.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_deepseek_reasoner.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": response_data["response"]["choices"][0]["message"]["reasoning_content"],
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_deepseek_reasoner_openrouter_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/openrouter/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = tools.extend_dict({
        "model": "deepseek/deepseek-v3.2",
        "stream": False,
        "reasoning": {"enabled": True},
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await internal_deepseek_reasoner.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_deepseek_reasoner_openrouter.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": response_data["response"]["choices"][0]["message"].get("reasoning", None),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_deepseek_ai_r1_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/together/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = tools.extend_dict({
        "model": "deepseek-ai/deepseek-r1",
        "stream": False,
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await internal_deepseek_ai_r1.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_deepseek_ai_r1.summarize_response_stats(response_data, decimals=False)

    def separate_content(content_raw: str) -> tuple[str, str | None]:
        if "</think>" not in content_raw:
            return content_raw, None

        content = content_raw.split("\n</think>\n", maxsplit=1)[1]
        reasoning_content = content_raw.split("\n</think>\n", maxsplit=1)[0].removeprefix("<think>\n")
        return content, reasoning_content
    
    content, reasoning_content = separate_content(response_data["response"]["choices"][0]["message"]["content"])

    try:
        return {
            "response": response_data,
            "content": content,
            "reasoning_content": reasoning_content,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_gpt_5_openrouter_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/openrouter/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = tools.extend_dict({
        "model": "openai/gpt-5",
        "stream": False,
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await internal_gpt_5_openrouter.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_gpt_5_openrouter.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": response_data["response"]["choices"][0]["message"].get("reasoning_details", [{}])[0].get("summary", None),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_gpt_5_2_openrouter_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/openrouter/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = tools.extend_dict({
        "model": "openai/gpt-5.2",
        "stream": False,
        # "reasoning": {"enabled": True, "effort": "high"},
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await internal_gpt_5_2_openrouter.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_gpt_5_2_openrouter.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": response_data["response"]["choices"][0]["message"].get("reasoning_details", [{}])[0].get("summary", None),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_gpt_5_2_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/openai/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = tools.extend_dict({
        "model": "gpt-5.2",
        "stream": False,
    }, payload, inplace=False, override=False)

    start_time = time.perf_counter()
    response_data = await internal_gpt_5_2.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_gpt_5_2.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": response_data["response"]["choices"][0]["message"].get("reasoning_details", [{}])[0].get("summary", None),
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_claude_sonnet_4_5_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/anthropic/v1/messages"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    payload = internal_claude_sonnet_4_5.to_antropic_payload(tools.extend_dict({
        "model": "claude-sonnet-4-5",
        "stream": False,
        "max_tokens": 1024,
    }, payload, inplace=False, override=False))

    start_time = time.perf_counter()
    response_data = await internal_claude_sonnet_4_5.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_claude_sonnet_4_5.summarize_response_stats(response_data, decimals=False)

    try:
        return tools.extend_dict({
            "stats": stats,
            "elapsed_time": elapsed_time,
        }, internal_claude_sonnet_4_5.parse_response(response_data), inplace=True, deepcopy=False)
    except Exception as e:
        print(response_data)
        raise


async def eliza_yandex_gpt_5_1_pro_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/internal/zeliboba/32b_aligned_quantized_202506/generative"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    start_time = time.perf_counter()
    payload_extended = zeliboba.PayloadFormatter.extend_with_default_params(payload)
    response_data = await internal_yandex_gpt_5_pro.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload_extended, timeout=timeout, payload_formater=zeliboba.PayloadFormatter.format, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_yandex_gpt_5_pro.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["Responses"][0]["Response"],
            "reasoning_content": None,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_yandex_gpt_5_lite_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/internal/zeliboba/8b_aligned_quantized_202502/generative"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    start_time = time.perf_counter()
    payload_extended = zeliboba.PayloadFormatter.extend_with_default_params(payload)
    response_data = await internal_yandex_gpt_5_lite.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload_extended, timeout=timeout, payload_formater=zeliboba.PayloadFormatter.format, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_yandex_gpt_5_lite.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["Responses"][0]["Response"],
            "reasoning_content": None,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def eliza_alice_ai_llm_235b_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/internal/zeliboba/zeliboba_lts_235b_aligned_quantized_202510/generative"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    start_time = time.perf_counter()
    payload_extended = zeliboba.PayloadFormatter.extend_with_default_params(payload)
    response_data = await internal_alice_ai_llm_235b.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload_extended, timeout=timeout, payload_formater=zeliboba.PayloadFormatter.format, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_alice_ai_llm_235b.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["Responses"][0]["Response"],
            "reasoning_content": None,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def deepseek_v3_1_terminus_batch_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/internal/deepseek-v3-1-terminus-batch/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    start_time = time.perf_counter()
    response_data = await internal_deepseek_v3_1_terminus_batch.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_deepseek_v3_1_terminus_batch.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": None,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def deepseek_v3_1_terminus_batch_reasoner_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/internal/deepseek-v3-1-terminus-batch/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    start_time = time.perf_counter()
    payload_extended = tools.extend_dict(
        payload,
        {"chat_template_kwargs": {"thinking": True}},
        override=True,
        inplace=False,
        deep=True,
    )
    response_data = await internal_deepseek_v3_1_terminus_batch.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload_extended, timeout=timeout, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = internal_deepseek_v3_1_terminus_batch.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": response_data["response"]["choices"][0]["message"]["reasoning_content"],
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


async def alice_32b_latest_post(
    session: aiohttp.ClientSession,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    **kwargs,
) -> dict[str, tp.Any]:
    if token is None:
        token = auth.guess_token_by_quota(pool)

    URL = "https://api.eliza.yandex.net/internal/alice-ai-llm-32b-latest/generative/v1/chat/completions"
    HEADERS = {
        "authorization": f"OAuth {token}",
        "content-type": "application/json"
    }

    if pool is not None:
        HEADERS["Ya-Pool"] = pool

    start_time = time.perf_counter()
    payload_extended = zeliboba.PayloadFormatter.extend_with_default_params(payload)
    response_data = await alice_32b_latest.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload_extended, timeout=timeout, payload_formater=zeliboba.PayloadFormatter.format, **kwargs)
    elapsed_time = time.perf_counter() - start_time

    stats = alice_32b_latest.summarize_response_stats(response_data, decimals=False)

    try:
        return {
            "response": response_data,
            "content": response_data["response"]["choices"][0]["message"]["content"],
            "reasoning_content": None,
            "stats": stats,
            "elapsed_time": elapsed_time,
        }
    except Exception as e:
        print(response_data)
        raise


@lru_cache(maxsize=256)
def zeliboba_post_provider(model_name: str) -> PostFunc:
    @lru_cache(maxsize=1)
    def get_models_list() -> list[str]:
        HEADERS = {
            "content-type": "application/json"
        }
        response_data = requests.get("https://zeliboba.yandex-team.ru/balance/models_info", headers=HEADERS).json()
        return response_data["models"]["cloud_dynamic"] + response_data["models"]["static"]
    
    models_list = get_models_list()
    if model_name not in models_list:
        raise RuntimeError(f"Zeliboba model with name `{model_name}` is not in the list of available models.")

    async def zeliboba_post(
        session: aiohttp.ClientSession,
        payload: dict[str, tp.Any],
        timeout: int = 300,
        pool: str | None = None,  # ignored
        token: str | None = None,

        **kwargs,
    ) -> dict[str, tp.Any]:
        if token is None:
            auth._ensure_env_loaded()
            token = os.getenv("INTERNAL_PERSONAL_ZELIBOBA_TOKEN")

        URL = f"https://zeliboba.yandex-team.ru/balance/{model_name}/generative"
        HEADERS = {
            "authorization": f"OAuth {token}",
            "content-type": "application/json"
        }

        start_time = time.perf_counter()
        payload_extended = zeliboba.PayloadFormatter.extend_with_default_params(payload)
        response_data = await zeliboba.post_strict_safe_fixed_utf_8(session, URL, HEADERS, payload_extended, timeout=timeout, payload_formater=zeliboba.PayloadFormatter.format, **kwargs)
        elapsed_time = time.perf_counter() - start_time

        stats = zeliboba.summarize_response_stats(response_data, decimals=False)

        content, reasoning_content = response_data["Responses"][0]["Response"], None

        if content.startswith("[COT_START]") and "[COT_END]" in content:
            reasoning_content = content.removeprefix("[COT_START]").lstrip().rsplit("[COT_END]", maxsplit=1)[0].rstrip()
            content = content.rsplit("[COT_END]", maxsplit=1)[1].lstrip()

        try:
            return {
                "response": response_data,
                "content": content,
                "reasoning_content": reasoning_content,
                "stats": stats,
                "elapsed_time": elapsed_time,
            }
        except Exception as e:
            print(response_data)
            raise
    
    return zeliboba_post


(MODEL_REGISTRY := ModelRegistry()).register_multiple({
    # external
    # Legacy aliases stay routable during a rolling deployment. The public
    # catalog and migration use the provider:model form below.
    "external:deepseek-chat": deepseek_post_provider("deepseek-v4-flash"),
    "external:deepseek-reasoner": deepseek_post_provider("deepseek-v4-pro"),
    "external:xiaomi-mimo": xiaomi_post_provider("mimo-v2-flash"),

    # internal
    "internal:deepseek-reasoner": eliza_deepseek_reasoner_post,
    "internal:openrouter-deepseek-reasoner": eliza_deepseek_reasoner_openrouter_post,
    "internal:deepseek_ai_r1": eliza_deepseek_ai_r1_post,
    "internal:openrouter-gpt-5": eliza_gpt_5_openrouter_post,
    "internal:openrouter-gpt-5.2": eliza_gpt_5_2_openrouter_post,
    "internal:gpt-5.2": eliza_gpt_5_2_post,
    "internal:claude-sonnet-4-5": eliza_claude_sonnet_4_5_post,

    # internal, free
    "internal:yandex-gpt-5.1-pro": eliza_yandex_gpt_5_1_pro_post,
    "internal:yandex-gpt-5-lite": eliza_yandex_gpt_5_lite_post,
    # "internal:alice-ai-llm-235b": eliza_alice_ai_llm_235b_post,  # does not work currently
    "internal:deepseek-v3.1-terminus-batch": deepseek_v3_1_terminus_batch_post,
    "internal:deepseek-v3.1-terminus-batch-reasoner": deepseek_v3_1_terminus_batch_reasoner_post,
    "internal:alice-32b-latest": alice_32b_latest_post,
})

MODEL_REGISTRY.register_regex(
    r"deepseek:(?P<name>[A-Za-z0-9._:/-]+)",
    lambda match: (lambda: deepseek_post_provider(match["name"])),
)
MODEL_REGISTRY.register_regex(
    r"xiaomi:(?P<name>[A-Za-z0-9._:/-]+)",
    lambda match: (lambda: xiaomi_post_provider(match["name"])),
)
MODEL_REGISTRY.register_regex(
    r"internal:zeliboba-(?P<name>.+)",
    lambda match: (lambda: zeliboba_post_provider(match["name"])),
)
MODEL_REGISTRY.register_regex(
    r"openrouter:(?P<name>[A-Za-z0-9._:/-]+)",
    lambda match: (lambda: openrouter_post_provider(match["name"])),
)
MODEL_REGISTRY.register_regex(
    r"openai:(?P<name>[A-Za-z0-9._:/-]+)",
    lambda match: (lambda: openai_post_provider(match["name"])),
)
MODEL_REGISTRY.register_regex(
    r"anthropic:(?P<name>[A-Za-z0-9._:/-]+)",
    lambda match: (lambda: anthropic_post_provider(match["name"])),
)


async def post(
    session: aiohttp.ClientSession,
    model: str,
    payload: dict[str, tp.Any],
    timeout: int = 300,
    pool: str | None = None,
    token: str | None = None,

    # additional
    verbose: bool = True,
    traceback_verbose: bool = True,
    verbose_prefix: str = '',
    attempts: int = 1,
    errors_to_ignore_func: tp.Callable | None = None,
    backoff_seconds: float = 0.0,

    # other
    **kwargs,
) -> dict[str, tp.Any]:
    result = None

    for attempt_index in range(1, attempts + 1):
        try:
            result = await MODEL_REGISTRY.get(model)(
                session=session,
                payload=payload,
                timeout=timeout,
                pool=pool,
                token=token,
                **kwargs,
            )
            break
        except BaseException as e:
            if not (errors_to_ignore_func is not None and errors_to_ignore_func(e)):
                raise

            sleep_seconds = backoff_seconds * attempt_index

            if verbose:
                print(verbose_prefix, (
                    f"Encountered an error:\n{tools.exception_to_string(e, traceback_verbose=traceback_verbose)}\n"
                    f"Sleeping for {round(sleep_seconds, 2)} seconds."
                ), sep='')

            if backoff_seconds > 0:
                await asyncio.sleep(sleep_seconds)
    
    if result is None:
        raise tools.exceptions.AttemptsExceededError()
    
    return result


async def post_batch(
    args_list: list[dict[str, tp.Any]],
    batch_size: int = 100,
    timeout: int = 600,
    save_to_file: str | None = None,
    override: bool = False,
    only_new: bool = True,

    # additional
    verbose: bool = True,
    traceback_verbose: bool = False,
    verbose_prefix: str = '',
    skip_on_none: bool = False,
    skip_on_error: bool = False,
    save_errors_to_file: bool = False,
    tls_dns_cache: int = 300,
    session_timeout: float = 31 * 60,

    # other
    **kwargs,
) -> dict:
    batch_result = await tools.batch_utils.run_batch_aiohttp(
        post,
        args_list,
        batch_size,
        timeout=timeout,
        save_to_file=save_to_file,
        override=override,
        only_new=only_new,
        simultaneous_connections_per_task=1,

        # additional
        verbose=verbose,
        traceback_verbose=traceback_verbose,
        verbose_prefix=verbose_prefix,
        skip_on_none=skip_on_none,
        skip_on_error=skip_on_error,
        save_errors_to_file=save_errors_to_file,
        tls_dns_cache=tls_dns_cache,
        session_timeout=session_timeout,

        # other
        **kwargs,
    )

    if batch_result["count"] == 0:
        return tools.extend_dict(batch_result, {"total_price": 0.0}, inplace=True)

    # total price aggregation
    total_price = sum([result["stats"]["total_price"] for result in batch_result["results"]])

    return tools.extend_dict(batch_result, {"total_price": total_price}, inplace=True)
