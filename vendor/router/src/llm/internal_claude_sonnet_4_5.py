from decimal import Decimal

# local imports
from .. import utils


# Claude Sonnet 4.5 prices from your config
PRICE_INPUT_CACHE_READ     = Decimal("0.000000300")    # $0.300 / 1M cache read
PRICE_INPUT_CACHE_WRITE_1H = Decimal("0.000006000")    # $6.000 / 1M cache write 1h
PRICE_INPUT_CACHE_WRITE_5M = Decimal("0.000003750")    # $3.750 / 1M cache write 5m
PRICE_INPUT                = Decimal("0.000003000")    # $3.000 / 1M regular input
PRICE_OUTPUT               = Decimal("0.000015000")    # $15.000 / 1M output


def to_antropic_payload(payload: dict) -> dict:
    payload = dict(payload)

    messages = payload.pop("messages", [])
    if not isinstance(messages, list):
        raise ValueError(f"payload['messages'] must be a list, got {type(messages).__name__}")

    system_parts: list[str] = []
    anthropic_messages: list[dict] = []

    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError(f"Each message must be a dict, got {type(msg).__name__}")

        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            if content:
                system_parts.append(content if isinstance(content, str) else str(content))

        elif role in {"user", "assistant"}:
            anthropic_messages.append({
                "role": role,
                "content": content,
            })

        else:
            raise ValueError(f"Unsupported role for Anthropic Messages API: {role!r}")

    payload["messages"] = anthropic_messages

    if system_parts:
        existing_system = payload.get("system")
        if existing_system:
            payload["system"] = str(existing_system) + "\n\n" + "\n\n".join(system_parts)
        else:
            payload["system"] = "\n\n".join(system_parts)

    return payload


def _to_decimal_int(value) -> Decimal:
    return Decimal(int(value or 0))


def summarize_response_stats(response_json: dict, decimals: bool = True) -> dict:
    try:
        usage = response_json["response"]["usage"]

        input_tokens = _to_decimal_int(usage.get("input_tokens", 0))
        output_tokens = _to_decimal_int(usage.get("output_tokens", 0))

        cache_read_tokens = _to_decimal_int(usage.get("cache_read_input_tokens", 0))

        cache_creation = usage.get("cache_creation") or {}
        cache_write_5m_tokens = _to_decimal_int(cache_creation.get("ephemeral_5m_input_tokens", 0))
        cache_write_1h_tokens = _to_decimal_int(cache_creation.get("ephemeral_1h_input_tokens", 0))

        # Some Anthropic-compatible routers may only return this aggregate field.
        # Use it only if the detailed cache_creation fields are absent/zero.
        aggregate_cache_write_tokens = _to_decimal_int(usage.get("cache_creation_input_tokens", 0))
        detailed_cache_write_tokens = cache_write_5m_tokens + cache_write_1h_tokens

        if detailed_cache_write_tokens == 0 and aggregate_cache_write_tokens > 0:
            # Conservative fallback: assume 5m cache write if TTL is unknown.
            cache_write_5m_tokens = aggregate_cache_write_tokens

    except Exception:
        print(response_json)
        raise

    input_price = input_tokens * PRICE_INPUT
    cache_read_price = cache_read_tokens * PRICE_INPUT_CACHE_READ
    cache_write_5m_price = cache_write_5m_tokens * PRICE_INPUT_CACHE_WRITE_5M
    cache_write_1h_price = cache_write_1h_tokens * PRICE_INPUT_CACHE_WRITE_1H
    output_price = output_tokens * PRICE_OUTPUT

    total_price = (
        input_price
        + cache_read_price
        + cache_write_5m_price
        + cache_write_1h_price
        + output_price
    )

    result = {
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_5m_tokens": cache_write_5m_tokens,
        "cache_write_1h_tokens": cache_write_1h_tokens,
        "output_tokens": output_tokens,

        "input_price": input_price,
        "cache_read_price": cache_read_price,
        "cache_write_5m_price": cache_write_5m_price,
        "cache_write_1h_price": cache_write_1h_price,
        "output_price": output_price,

        "total_price": total_price,
    }

    if decimals:
        return result

    return {
        key: float(value)
        for key, value in result.items()
    }


def summarize_response_stats_string(response_json: dict) -> str:
    stats = summarize_response_stats(response_json, decimals=True)

    return (
        f"Input tokens: {stats['input_tokens']} ({stats['input_price']} $), "
        f"Input cache read tokens: {stats['cache_read_tokens']} ({stats['cache_read_price']} $), "
        f"Input cache write 5m tokens: {stats['cache_write_5m_tokens']} ({stats['cache_write_5m_price']} $), "
        f"Input cache write 1h tokens: {stats['cache_write_1h_tokens']} ({stats['cache_write_1h_price']} $), "
        f"Output tokens: {stats['output_tokens']} ({stats['output_price']} $), "
        f"Total price: {stats['total_price']} $"
    )


def parse_response(response_data: dict) -> dict:
    response = response_data["response"]
    content_blocks = response.get("content", [])

    text_parts: list[str] = []
    reasoning_parts: list[str] = []

    for block in content_blocks:
        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text")
            if text:
                text_parts.append(text)

        elif block_type == "thinking":
            thinking = block.get("thinking")
            if thinking:
                reasoning_parts.append(thinking)

        elif block_type == "redacted_thinking":
            # Anthropic may return this when part of thinking is safety-redacted.
            # There is usually no useful text to expose here.
            continue

    return {
        "response": response_data,
        "content": "\n".join(text_parts) if text_parts else None,
        "reasoning_content": "\n".join(reasoning_parts) if reasoning_parts else None,
    }


post_strict_safe_fixed_utf_8 = utils.post_strict_safe_fixed_utf_8