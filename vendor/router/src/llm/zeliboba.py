import copy
import typing as tp
from decimal import Decimal

# local imports
import tools
from .. import utils


__all__ = [
    "PRICE_INPUT_CACHE_HIT",
    "PRICE_INPUT_CACHE_MISS",
    "PRICE_OUTPUT",
    "summarize_response_stats",
    "summarize_response_stats_string",
    "post_strict_safe_fixed_utf_8",
    "PayloadFormatter",
]


PRICE_INPUT_CACHE_HIT  = Decimal("0.0")  # $0.0 / 1M (cache hit)
PRICE_INPUT_CACHE_MISS = Decimal("0.0")  # $0.0 / 1M (cache miss)
PRICE_OUTPUT           = Decimal("0.0")  # $0.0 / 1M (output)


def summarize_response_stats(response_json: dict, decimals: bool = True) -> dict:
    try:
        out_tokens = response_json["Responses"][0]["NumTokens"]
    except Exception as e:
        print(response_json)
        raise

    cache_hit_price = Decimal(0.0)
    cache_miss_price = Decimal(0.0)
    out_tokens_price = out_tokens * PRICE_OUTPUT

    if decimals:
        return {
            "cache_hit_tokens": None,
            "cache_miss_tokens": None,
            "out_tokens": out_tokens,

            "cache_hit_price": cache_hit_price,
            "cache_miss_price": cache_miss_price,
            "out_tokens_price": out_tokens_price,

            "total_price": cache_hit_price + cache_miss_price + out_tokens_price,
        }
    else:
        return {
            "cache_hit_tokens": None,
            "cache_miss_tokens": None,
            "out_tokens": out_tokens,

            "cache_hit_price": float(cache_hit_price),
            "cache_miss_price": float(cache_miss_price),
            "out_tokens_price": float(out_tokens_price),

            "total_price": float(cache_hit_price + cache_miss_price + out_tokens_price),
        }


def summarize_response_stats_string(response_json: dict) -> dict:
    stats = summarize_response_stats(response_json, decimals=True)
    return f"Input cache hit tokens: unknown (0.0 $), Input cache miss tokens: unknown (0.0 $), Output total tokens: {stats['out_tokens']} ({stats['out_tokens_price']} $), Total price: {stats['cache_hit_price'] + stats['cache_miss_price'] + stats['out_tokens_price']} $"


post_strict_safe_fixed_utf_8 = utils.post_strict_safe_fixed_utf_8


DEFAULT_PARAMS = {
    "num_hypos": 1,
}


Transform = tp.Callable[[dict[str, tp.Any]], None]


class PayloadFormatter:
    _handlers: list[Transform] = []

    @classmethod
    def register(cls, func: Transform) -> Transform:
        cls._handlers.append(func)
        return func

    @classmethod
    def format(cls, payload: dict[str, tp.Any], *, inplace: bool = False, deepcopy: bool = True) -> dict[str, tp.Any]:
        if not inplace:
            payload = copy.deepcopy(payload) if deepcopy else copy.copy(payload)

        for handler in cls._handlers:
            handler(payload)

        return payload
    
    @staticmethod
    def extend_with_default_params(payload: dict[str, tp.Any], *, override: bool = False, inplace: bool = False, deepcopy: bool = True) -> dict[str, tp.Any]:
        return tools.extend_dict(payload, DEFAULT_PARAMS, override=override, inplace=inplace, deepcopy=deepcopy)


@PayloadFormatter.register
def _temperature(payload: dict[str, tp.Any]) -> None:
    if (value := payload.pop("temperature", None)) is None:
        return

    value = max(0.001, tools.types.cast(value, float))

    tools.extend_dict(
        payload,
        {"Params": {"SamplerParams": {"Temperature": value}}},
        inplace=True,
        deepcopy=False,
        deep=True,
    )


@PayloadFormatter.register
def _top_p(payload: dict[str, tp.Any]) -> None:
    if (value := payload.pop("top_p", None)) is None:
        return

    value = tools.types.cast(value, float)

    if not (0.0 < value <= 1.0):
        raise ValueError(f"top_p must be in (0, 1], got {value}.")

    tools.extend_dict(
        payload,
        {"Params": {"SamplerParams": {"NucleusSampling": value}}},
        inplace=True,
        deepcopy=True,
        deep=True,
    )


@PayloadFormatter.register
def _min_tokens(payload: dict[str, tp.Any]) -> None:
    if (value := payload.pop("min_tokens", None)) is None:
        return

    assert isinstance(value, int)

    tools.extend_dict(
        payload,
        {"Params": {"MinOutLen": value}},
        inplace=True,
        deepcopy=False,
        deep=True,
    )


@PayloadFormatter.register
def _max_tokens(payload: dict[str, tp.Any]) -> None:
    if (value := payload.pop("max_tokens", None)) is None:
        return

    assert isinstance(value, int)

    tools.extend_dict(
        payload,
        {"Params": {"MaxOutLen": value}},
        inplace=True,
        deepcopy=False,
        deep=True,
    )


@PayloadFormatter.register
def _num_hypos(payload: dict[str, tp.Any]) -> None:
    if (value := payload.pop("num_hypos", None)) is None:
        return

    assert isinstance(value, int)

    tools.extend_dict(
        payload,
        {"Params": {"NumHypos": value}},
        inplace=True,
        deepcopy=False,
        deep=True,
    )


@PayloadFormatter.register
def _mode(payload: dict[str, tp.Any]) -> None:
    if (value := payload.pop("mode", None)) is None:
        return

    assert isinstance(value, str)

    tools.extend_dict(
        payload,
        {"Params": {"SamplerParams": {"Mode": value}}},
        inplace=True,
        deepcopy=False,
        deep=True,
    )