import requests

from . import auth
from . import utils
from . import exceptions
from . import redis_utils

# subpackages
from . import llm


__all__ = [
    # utils
    "auth",
    "exceptions",
    "utils",
    "redis_utils",

    # llm
    "llm",

    # other
    "ELIZA_ALL_MODELS_URL",
    "get_all_eliza_models",
]


ELIZA_ALL_MODELS_URL = "https://api.eliza.yandex.net/models"


def get_all_eliza_models():
    headers = {
        "authorization": f"OAuth {auth.guess_token_by_quota('personal')}"
    }
    response = requests.get(ELIZA_ALL_MODELS_URL, headers=headers, verify=False)

    try:
        return response.json()
    except Exception as e:
        print(f"Getting all eliza models has failed with status code {response.status_code}.")

        raise