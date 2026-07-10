from decimal import Decimal

# local imports
from .. import utils


PRICE_INPUT_CACHE_HIT  = Decimal("0.000000002800")  # $0.002800 / 1M (cache hit)
PRICE_INPUT_CACHE_MISS = Decimal("0.000000140000")  # $0.140000 / 1M (cache miss)
PRICE_OUTPUT           = Decimal("0.000000280000")  # $0.280000 / 1M (output)


def summarize_response_stats(response_json: dict, decimals: bool = True) -> dict:
    try:
        cache_hit_tokens = response_json["usage"]["prompt_cache_hit_tokens"]
        cache_miss_tokens = response_json["usage"]["prompt_cache_miss_tokens"]
        out_tokens = response_json["usage"]["completion_tokens"]
    except Exception as e:
        print(response_json)
        raise

    cache_hit_price = cache_hit_tokens * PRICE_INPUT_CACHE_HIT
    cache_miss_price = cache_miss_tokens * PRICE_INPUT_CACHE_MISS
    out_tokens_price = out_tokens * PRICE_OUTPUT

    if decimals:
        return {
            "cache_hit_tokens": cache_hit_tokens,
            "cache_miss_tokens": cache_miss_tokens,
            "out_tokens": out_tokens,

            "cache_hit_price": cache_hit_price,
            "cache_miss_price": cache_miss_price,
            "out_tokens_price": out_tokens_price,

            "total_price": cache_hit_price + cache_miss_price + out_tokens_price,
        }
    else:
        return {
            "cache_hit_tokens": float(cache_hit_tokens),
            "cache_miss_tokens": float(cache_miss_tokens),
            "out_tokens": float(out_tokens),

            "cache_hit_price": float(cache_hit_price),
            "cache_miss_price": float(cache_miss_price),
            "out_tokens_price": float(out_tokens_price),

            "total_price": float(cache_hit_price + cache_miss_price + out_tokens_price),
        }


def summarize_response_stats_string(response_json: dict) -> dict:
    stats = summarize_response_stats(response_json, decimals=True)
    return f"Input cache hit tokens: {stats['cache_hit_tokens']} ({stats['cache_hit_price']} $), Input cache miss tokens: {stats['cache_miss_tokens']} ({stats['cache_miss_price']} $), Output total tokens: {stats['out_tokens']} ({stats['out_tokens_price']} $), Total price: {stats['cache_hit_price'] + stats['cache_miss_price'] + stats['out_tokens_price']} $"


post_strict_safe_fixed_utf_8 = utils.post_strict_safe_fixed_utf_8