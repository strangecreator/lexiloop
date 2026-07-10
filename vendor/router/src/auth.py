import os
import pathlib
from functools import lru_cache

BASE_DIR = pathlib.Path(__file__).parents[1]
ENV_PATH = BASE_DIR / ".env"

from dotenv import load_dotenv


__all__ = [
    "QUOTA_TO_TOKEN_MAPPING",
    "_ensure_env_loaded",
    "guess_token_by_quota",
]


QUOTA_TO_TOKEN_MAPPING = {
    "personal": "INTERNAL_PERSONAL_QUOTA_SOY_TOKEN",
    "market_learn": "INTERNAL_ROBOT_ECOM_ASSISTANT_SOY_TOKEN",
    "market-search": "INTERNAL_MARKET_SEARCH_SOY_TOKEN",
    "ads": "INTERNAL_ROBOT_ECOM_ASSISTANT_SOY_TOKEN",
}


@lru_cache(maxsize=1)
def _ensure_env_loaded() -> None:
    load_dotenv(dotenv_path=ENV_PATH)


def guess_token_by_quota(quota: str | None) -> str:
    _ensure_env_loaded()

    if quota is None:
        quota = "personal"

    if quota in QUOTA_TO_TOKEN_MAPPING:
        return os.getenv(QUOTA_TO_TOKEN_MAPPING[quota])
    else:
        raise RuntimeError(f"No entry for quota=`{quota}` is provided in the quota-to-token mapping.")