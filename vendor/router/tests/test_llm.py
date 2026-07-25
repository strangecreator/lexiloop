import pathlib
from dotenv import load_dotenv

BASE_DIR = pathlib.Path(__file__).parents[1]
load_dotenv(dotenv_path=str(BASE_DIR / ".env"))

# aiohttp & related imports
import aiohttp

# pytest & related imports
import pytest

# router & related imports
import router


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_external_deepseek_reasoner():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Hello, what time is it?"),
            "temperature": 0,
        }

        result = await router.llm.post(
            session,
            "external:deepseek-reasoner",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_external_xiaomi_mimo():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Hello, what time is it?"),
            "temperature": 0,
        }

        result = await router.llm.post(
            session,
            "external:xiaomi-mimo",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_internal_deepseek_reasoner():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Hello, what time is it?"),
            "temperature": 0,
        }

        result = await router.llm.post(
            session,
            "internal:deepseek-reasoner",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_internal_yandex_gpt_5_pro():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Solve a simple task: calculate the integral of f(x)=1/(1 + x^4) from -infty to infty."),
        }

        result = await router.llm.post(
            session,
            "internal:yandex-gpt-5-pro",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_internal_yandex_gpt_5_lite():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Solve a simple task: calculate the integral of f(x)=1/(1 + x^4) from -infty to infty."),
        }

        result = await router.llm.post(
            session,
            "internal:yandex-gpt-5-lite",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_internal_zeliboba_32b_aligned_quantized_202506():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Solve a simple task: calculate the integral of f(x)=1/(1 + x^4) from -infty to infty."),
        }

        result = await router.llm.post(
            session,
            "internal:zeliboba-32b_aligned_quantized_202506",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())


@pytest.mark.skip()
@pytest.mark.asyncio
async def test_internal_zeliboba_32b_aligned_quantized_202506_reasoner():
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": router.utils.make_full_dialog(None, "Create a weekly study plan for: probability, linear algebra, algorithms (10 hours/week)."),
            "Params": {
                "SamplerParams": {
                    "Temperature": 0.3,
                },
            },
        }

        result = await router.llm.post(
            session,
            "internal:zeliboba-32b_aligned_quantized_202506_reasoner",
            payload,
        )

        assert {"response", "content", "reasoning_content", "stats", "elapsed_time"} <= set(result.keys())

        assert "[COT_START]" not in result["content"] and "[COT_END]" not in result["content"]
        assert isinstance(result["reasoning_content"], str) and len(result["reasoning_content"]) > 10
@pytest.mark.asyncio
async def test_openrouter_provider_parses_chat_completion(monkeypatch):
    async def fake_post(session, url, headers, payload, timeout=300, **kwargs):
        assert url == 'https://openrouter.ai/api/v1/chat/completions'
        assert headers['Authorization'] == 'Bearer token'
        assert payload['model'] == 'openai/gpt-5.2'
        return {
            'choices': [{'message': {'content': '{"ok": true}', 'reasoning_content': 'brief'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14, 'cost': 0.0002},
        }

    monkeypatch.setattr(router.utils, 'post_strict_safe_fixed_utf_8', fake_post)
    async with aiohttp.ClientSession() as session:
        result = await router.llm.post(
            session,
            'openrouter:openai/gpt-5.2',
            {'messages': [{'role': 'user', 'content': 'Hello'}]},
            token='token',
            verbose=False,
        )
    assert result['content'] == '{"ok": true}'
    assert result['reasoning_content'] == 'brief'
    assert result['stats']['total_tokens'] == 14
    assert result['stats']['total_price'] == 0.0002


@pytest.mark.asyncio
async def test_openai_gpt5_uses_max_completion_tokens(monkeypatch):
    async def fake_post(session, url, headers, payload, timeout=300, **kwargs):
        assert url == 'https://api.openai.com/v1/chat/completions'
        assert payload['model'] == 'gpt-5.4-nano'
        assert payload['max_completion_tokens'] == 128
        assert 'max_tokens' not in payload
        assert 'temperature' not in payload
        return {
            'choices': [{'message': {'content': 'LEXILOOP_API_OK'}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 3, 'total_tokens': 11},
        }

    monkeypatch.setattr(router.utils, 'post_strict_safe_fixed_utf_8', fake_post)
    async with aiohttp.ClientSession() as session:
        result = await router.llm.post(
            session,
            'openai:gpt-5.4-nano',
            {
                'messages': [{'role': 'user', 'content': 'Connection test.'}],
                'temperature': 0,
                'max_tokens': 128,
            },
            token='token',
            verbose=False,
        )
    assert result['content'] == 'LEXILOOP_API_OK'
    assert result['stats']['total_tokens'] == 11


@pytest.mark.asyncio
async def test_openai_endpoint_mismatch_falls_back_to_responses(monkeypatch):
    calls = []

    async def fake_post(session, url, headers, payload, timeout=300, **kwargs):
        calls.append((url, payload))
        if url.endswith('/chat/completions'):
            raise router.exceptions.HTTPStatusError(404, {
                'error': {'message': 'This model is only supported in v1/responses.'},
            })
        assert url == 'https://api.openai.com/v1/responses'
        assert payload == {
            'model': 'o1-pro',
            'input': [{'role': 'user', 'content': 'Hello'}],
            'stream': False,
            'max_output_tokens': 128,
        }
        return {
            'output': [{
                'type': 'message',
                'content': [{'type': 'output_text', 'text': '{"ok": true}'}],
            }],
            'usage': {'input_tokens': 9, 'output_tokens': 4, 'total_tokens': 13},
        }

    monkeypatch.setattr(router.utils, 'post_strict_safe_fixed_utf_8', fake_post)
    async with aiohttp.ClientSession() as session:
        result = await router.llm.post(
            session,
            'openai:o1-pro',
            {
                'messages': [{'role': 'user', 'content': 'Hello'}],
                'max_tokens': 128,
            },
            token='token',
            verbose=False,
        )
    assert len(calls) == 2
    assert result['content'] == '{"ok": true}'
    assert result['stats']['total_tokens'] == 13
