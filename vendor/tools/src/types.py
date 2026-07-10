import json
import typing as tp


__all__ = [
    "coerce_to_union",
    "cast",
]


def coerce_to_union(value: tp.Any, union_tp: tp.Any) -> tp.Any:
    """
    Coerce `value` into one of the types described by `union_tp`.

    Supports:
      - plain runtime types: int, str, dict, list, ...
      - PEP604 unions: int | str
      - typing.Union / Optional: tp.Union[int, str], tp.Optional[int]

    Notes:
      - tp.Any -> returns value as-is
      - typing-only constructs without runtime meaning (e.g. list[int]) are not supported here
        (we intentionally treat them as non-callable and non-isinstance-able).
    """
    if union_tp is tp.Any:
        return value

    # Union candidates (works for both PEP604 and typing.Union)
    candidates = tp.get_args(union_tp) or (union_tp,)

    # Fast path: already matches a candidate runtime type
    for _type in candidates:
        try:
            if isinstance(value, _type):
                return value
        except TypeError:
            # `_type` can be a typing construct that isn't usable in isinstance()
            pass

    # Try to construct in order
    last_exc: Exception | None = None
    for _type in candidates:
        try:
            return _type(value)
        except Exception as e:
            last_exc = e

    raise TypeError(
        f"Cannot coerce {value!r} ({type(value).__name__}) to any of {candidates}. "
        f"Last error: {last_exc!r}"
    )


def cast(value: tp.Any, to_type: type) -> tp.Any:
    if to_type == str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)

    return coerce_to_union(value, to_type)