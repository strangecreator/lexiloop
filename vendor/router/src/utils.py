import json
import codecs
import typing as tp

# aiohttp & related imports
import asyncio
import aiohttp

# local imports
import tools
from . import exceptions
from . import redis_utils


__all__ = [
    "DEFAULT_TIMEOUT_TO_ABSORB",
    "make_full_dialog",
    "make_full_dialog_human_readable",
    "make_full_response_human_readable",
    "hash_request",
    "post_strict_safe_fixed_utf_8",
    "post_strict_safe_fixed_utf_8_extended",
]


def make_full_dialog(system_prefix: tp.Optional[str], user_suffix: str) -> list[dict]:
    dialog = []
    if system_prefix:
        dialog = [
            {
                "role": "system",
                "content": system_prefix,
            }
        ]
    
    dialog += [{
        "role": "user",
        "content": user_suffix,
    }]
    return dialog


def make_full_dialog_human_readable(system_prefix: tp.Optional[str], user_suffix: str) -> list[dict]:
    if system_prefix is None:
        return f"SYSTEM MESSAGE:\nUSER MESSAGE:\n{user_suffix}"

    return f"SYSTEM MESSAGE:\n{system_prefix}\n\nUSER MESSAGE:\n{user_suffix}"


def make_full_response_human_readable(response: dict) -> str:
    reasoning_content = response.get("reasoning_content")

    if reasoning_content is None:
        reasoning_content = ''

    return f"------ Reasoning content:\n{reasoning_content}\n\n\n------ Content:\n{response['content']}"


def hash_request(url: str, headers: dict[str, tp.Any], payload: dict[str, tp.Any]) -> str:
    return tools.hash64(
        tools.hash64(url) + \
        tools.hash64(json.dumps(headers, ensure_ascii=False)) + \
        tools.hash64(json.dumps(payload, ensure_ascii=False))
    )


def override_payload(payload: tp.Any, **overrives) -> tp.Any:
    if not isinstance(payload, dict) and len(overrives) > 0:
        raise NotImplementedError("Override behavior is not defined for non-dict payloads.")
    
    return tools.extend_dict(
        payload,
        overrives,
        override=True,
        inplace=False,
        deepcopy=True,
        deep=True,
    )


async def handle_delayed_mode(
    url: str,
    headers: dict[str, tp.Any],
    payload: dict[str, tp.Any],
    redis_list_client: redis_utils.RedisListStructure | None = None,
    timeout_to_absorb: float | None = None,
    hash_override: str | None = None,
    no_op_if_key_exists: bool = True,
    extra_params: tp.Any = None,
    delete_value_on_success: bool = True,

    # formatting
    payload_formater: tp.Callable | None = None,

    **payload_overrides,
) -> tp.Any:
    assert timeout_to_absorb is None or isinstance(timeout_to_absorb, float)

    payload_extended = tools.default_for_none(payload_formater, lambda x: x)(override_payload(payload, **payload_overrides))

    if hash_override is None:
        request_hash = hash_request(url, headers, payload_extended)  # 64-hex string
    else:
        request_hash = hash_override

    redis_consumer_key = f"router:delayed:consumer:{request_hash}"
    redis_producer_key = f"router:delayed:producer:{request_hash}"
    redis_processing_key = f"router:delayed:processing:{request_hash}"

    if redis_list_client is None:
        redis_list_client = redis_utils.RedisListStructure()

    if delete_value_on_success:
        response_raw = await redis_list_client.pop(redis_consumer_key)
    else:
        response_raw = await redis_list_client.peek(redis_consumer_key)

    if response_raw is None:
        producer_exists = (await redis_list_client.count(redis_producer_key)) > 0
        processing_exists = bool(await redis_list_client.r.exists(redis_processing_key))

        does_key_exist = producer_exists or processing_exists

        if not does_key_exist or not no_op_if_key_exists:
            await redis_list_client.add(redis_producer_key, json.dumps({
                "url": url,
                "headers": headers,
                "payload": payload_extended,
                "extra_params": extra_params if extra_params is not None else {},
            }, ensure_ascii=False))

            if timeout_to_absorb is not None:
                await asyncio.sleep(timeout_to_absorb)

        raise exceptions.DelayedError(f"key=`{redis_producer_key}`", color="minus")
    else:
        response = json.loads(response_raw)

        if isinstance(response, dict) and response.get("__router_delayed_error__") is True:
            raise exceptions.DelayedRequestFailedError(
                f"key=`{redis_producer_key}`",
                response,
                color="invalid",
            )

        return response


async def post_strict_safe_fixed_utf_8(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, tp.Any],
    payload: dict[str, tp.Any],
    timeout: int = 300,

    # formatting
    payload_formater: tp.Callable | None = None,

    # delayed & caches
    delayed_mode: bool = False,

    **kwargs,
) -> dict[str, tp.Any]:
    if delayed_mode:
        return await handle_delayed_mode(url, headers, payload, payload_formater=payload_formater, **kwargs)

    payload = tools.default_for_none(payload_formater, lambda x: x)(override_payload(payload, **kwargs))

    buffer = bytearray()
    saw_left_brace = False

    async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
        status = response.status

        try:
            async for chunk in response.content.iter_chunked(8192):
                if not chunk.strip():
                    continue

                if not saw_left_brace:
                    i = chunk.find(b'{')

                    if i == -1:
                        continue

                    buffer.extend(chunk[i:])
                    saw_left_brace = True
                else:
                    buffer.extend(chunk)

                try:
                    text = buffer.decode("utf-8")  # strict
                except UnicodeDecodeError:
                    continue

                try:
                    response_data = json.loads(text)

                    if 200 <= status < 300:
                        return response_data

                    raise exceptions.HTTPStatusError(status, response_data)

                except json.JSONDecodeError:
                    continue

        except (aiohttp.ClientPayloadError, aiohttp.http_exceptions.TransferEncodingError):
            # broken EOF
            pass

        try:
            text = buffer.decode("utf-8")

        except UnicodeDecodeError as e:
            tail = buffer[-16:].hex()
            raise exceptions.InvalidJSONResponseError(status, f"UTF-8 decode error at end: {e}, tail=0x{tail}.")

        text = text.strip()

        if not text:
            raise exceptions.EmptyBodyError(status)

        try:
            response_data = json.loads(text)

            if 200 <= status < 300:
                return response_data

            raise exceptions.HTTPStatusError(status, response_data)

        except json.JSONDecodeError:
            raise exceptions.InvalidJSONResponseError(status, text)


async def post_strict_safe_fixed_utf_8_extended(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, tp.Any],
    payload: tp.Any,
    timeout: int = 300,

    # formatting
    payload_formater: tp.Callable | None = None,

    # delayed & caches
    delayed_mode: bool = False,

    **kwargs,
) -> tp.Any:
    if delayed_mode:
        return await handle_delayed_mode(url, headers, payload, payload_formater=payload_formater, **kwargs)

    payload = tools.default_for_none(payload_formater, lambda x: x)(override_payload(payload, **kwargs))

    response_status: int | None = None

    json_started = False
    tail_bytes = bytearray()
    tail_limit_bytes = 16

    utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    decoded_buffer = ''

    json_decoder = json.JSONDecoder()

    candidate_object: tp.Any | None = None
    candidate_trailing_text: str | None = None

    try:
        async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
            response_status = response.status

            try:
                async for chunk_bytes in response.content.iter_chunked(8192):
                    if not chunk_bytes.strip():
                        continue

                    if not json_started:
                        json_start_index = tools.find_json_start(chunk_bytes)
                        if json_start_index is None:
                            continue
                        json_started = True
                        chunk_bytes = chunk_bytes[json_start_index:]

                    if chunk_bytes:
                        tail_bytes.extend(chunk_bytes)
                        if len(tail_bytes) > tail_limit_bytes:
                            del tail_bytes[:-tail_limit_bytes]

                    try:
                        decoded_buffer += utf8_decoder.decode(chunk_bytes, final=False)
                    except UnicodeDecodeError as decode_error:
                        raise exceptions.InvalidJSONResponseError(
                            response_status,
                            f"UTF-8 decode error while streaming: {decode_error}. tail=0x{tail_bytes.hex()}.",
                        )

                    leading_stripped_text = decoded_buffer.lstrip()
                    if not leading_stripped_text:
                        continue

                    try:
                        parsed_object, parsed_end_index = json_decoder.raw_decode(leading_stripped_text)
                    except json.JSONDecodeError:
                        continue

                    trailing_text = leading_stripped_text[parsed_end_index:].lstrip()

                    if not trailing_text:
                        if 200 <= response_status < 300:
                            return parsed_object
                        raise exceptions.HTTPStatusError(response_status, parsed_object)

                    if trailing_text.startswith('<'):
                        if 200 <= response_status < 300:
                            return parsed_object
                        raise exceptions.HTTPStatusError(response_status, parsed_object)

                    candidate_object = parsed_object
                    candidate_trailing_text = trailing_text

            except (aiohttp.ClientPayloadError, aiohttp.http_exceptions.TransferEncodingError):
                # broken EOF
                pass

    finally:
        pass

    if response_status is None:
        raise exceptions.InvalidJSONResponseError(0, "Request failed before receiving a response.")

    try:
        decoded_buffer += utf8_decoder.decode(b'', final=True)
    except UnicodeDecodeError as decode_error:
        raise exceptions.InvalidJSONResponseError(
            response_status,
            f"UTF-8 decode error at end: {decode_error}. tail=0x{tail_bytes.hex()}.",
        )

    stripped_text = decoded_buffer.strip()

    if not json_started or not stripped_text:
        raise exceptions.EmptyBodyError(response_status)

    leading_stripped_text = stripped_text.lstrip()

    try:
        parsed_object, parsed_end_index = json_decoder.raw_decode(leading_stripped_text)
        trailing_text = leading_stripped_text[parsed_end_index:].lstrip()
    except json.JSONDecodeError:
        if candidate_object is not None:
            raise exceptions.InvalidJSONResponseError(
                response_status,
                "Parsed JSON but response had extra non-HTML trailing data. Trailing starts with:\n"
                f"{candidate_trailing_text or ''}",
            )

        raise exceptions.InvalidJSONResponseError(response_status, stripped_text)

    if trailing_text and not trailing_text.startswith('<'):
        raise exceptions.InvalidJSONResponseError(
            response_status,
            "Extra data after JSON. Trailing starts with:\n"
            f'{trailing_text}',
        )

    if 200 <= response_status < 300:
        return parsed_object

    raise exceptions.HTTPStatusError(response_status, parsed_object)