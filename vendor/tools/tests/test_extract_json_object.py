# pytest & related imports
import pytest

# local imports
import tools


@pytest.mark.parametrize(
    "text, expected",
    [
        # simplest: pure JSON
        ('{"a": 1}', '{"a": 1}'),
        ("  \n\t{\"a\": 1}\n  ", '{"a": 1}'),

        # prefix/suffix noise
        ('prefix {"a": 1} suffix', '{"a": 1}'),
        ('garbage\n{"a": 1}\nmore garbage', '{"a": 1}'),

        # nested objects
        ('xxx {"a": {"b": 2}, "c": 3} yyy', '{"a": {"b": 2}, "c": 3}'),

        # braces inside strings should NOT affect balancing
        ('xxx {"a": "brace } inside", "b": 2} yyy', '{"a": "brace } inside", "b": 2}'),
        ('xxx {"a": "brace { inside", "b": 2} yyy', '{"a": "brace { inside", "b": 2}'),

        # escaped quotes inside strings
        ('xxx {"a": "he said: \\"hi\\"", "b": 2} yyy', '{"a": "he said: \\"hi\\"", "b": 2}'),

        # escaped backslashes and then a quote
        (r'xxx {"path":"C:\\temp\\file.json","b":2} yyy', r'{"path":"C:\\temp\\file.json","b":2}'),

        # multiple JSON objects -> should return the first *complete* one
        ('xxx {"a": 1} yyy {"b": 2}', '{"a": 1}'),

        # whitespace around extracted object is stripped
        ('xxx \n  {"a": 1, "b": 2}   \n yyy', '{"a": 1, "b": 2}'),

        # JSON with escaped braces inside strings (still just normal chars)
        ('xxx {"a": "\\\\{not a brace\\\\}", "b": 1} yyy', '{"a": "\\\\{not a brace\\\\}", "b": 1}'),

        # braces in later noise should be ignored once first object is complete
        ('xxx {"a": 1} trailing }}} {{{', '{"a": 1}'),

        # valid JSON object followed by garbage (including extra braces)
        ("xxx { } }", "{ }"),
    ],
)
def test_extract_json_object_success(text, expected):
    assert tools.extract_json_object(text) == expected


@pytest.mark.parametrize(
    "text, err_substr",
    [
        # no opening brace at all
        ("", "No '{' found"),
        ("no json here", "No '{' found"),

        # opening brace but never closes
        ("xxx {", "Unbalanced braces"),
        ('xxx {"a": 1', "Unbalanced braces"),
        ('xxx {"a": {"b": 2}', "Unbalanced braces"),

        # tricky: quote opens and never closes -> we should still fail (never balances)
        ('xxx {"a": "unterminated string }', "Unbalanced braces"),
    ],
)
def test_extract_json_object_errors(text, err_substr):
    with pytest.raises(ValueError) as e:
        tools.extract_json_object(text)

    assert err_substr in str(e.value)


def test_extract_json_object_first_brace_is_inside_quotes_in_prefix():
    # The algorithm finds the first '{' even if it's inside quotes in the prefix.
    # That's expected behavior given the spec ("until the first '{' character").
    # This test documents the behavior.
    text = 'prefix "not json { still in quotes" then {"a": 1} suffix'
    # It will start at the '{' inside quotes and then fail because braces won't balance.
    with pytest.raises(ValueError):
        tools.extract_json_object(text)


def test_extract_json_object_handles_large_noise_prefix_and_suffix():
    text = ("noise " * 10_000) + '{"a": 1, "b": {"c": 2}}' + (" tail" * 10_000)
    assert tools.extract_json_object(text) == '{"a": 1, "b": {"c": 2}}'


def test_extract_json_object_does_not_strip_internal_whitespace():
    text = 'xxx {"a": 1,\n "b": 2} yyy'
    assert tools.extract_json_object(text) == '{"a": 1,\n "b": 2}'