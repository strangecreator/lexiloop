# pytest & related imports
import pytest

# local imports
import tools


@pytest.mark.parametrize("kwargs, expected", [
    pytest.param(
        {"string": "short", "max_len": 10},
        "short",
        id="simple",
    ),
    pytest.param(
        {"string": "hello world", "max_len": 8},
        "hello...",
        id="end",
    ),
    pytest.param(
        {"string": "a  b   c", "max_len": 6, "end": '…', "save_spaces": True},
        "a  b…",
        id="save_spaces",
    ),
])
def test_simple(kwargs: dict, expected: str) -> None:
    assert tools.truncate_word_aware(**kwargs) == expected