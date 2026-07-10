import copy

# local imports
from tools import rename_fields_in_dict

# pytest & related imports
import pytest


def test_non_inplace_does_not_mutate_input_and_returns_new_dict():
    data = {"a": 1, "b": 2}
    mapping = {"a": "x"}
    data_before = copy.deepcopy(data)

    out = rename_fields_in_dict(data, mapping, inplace=False)

    assert out == {"x": 1, "b": 2}
    assert data == data_before
    assert out is not data


def test_non_inplace_keeps_unmapped_keys_and_skips_missing_and_identity():
    data = {"a": 1, "b": 2, "c": 3}
    mapping = {"a": "a", "missing": "z", "b": "x"}  # identity + missing + rename
    out = rename_fields_in_dict(data, mapping, inplace=False)

    assert out == {"a": 1, "x": 2, "c": 3}


def test_non_inplace_overwrite_is_by_data_iteration_order():
    # In non-inplace path, dict comprehension iterates over data.items():
    # if two keys map to the same destination key, the later key in data order wins.
    data = {"a": 1, "b": 2}  # 'b' comes after 'a'
    mapping = {"a": "x", "b": "x"}

    out = rename_fields_in_dict(data, mapping, inplace=False)
    assert out == {"x": 2}


def test_non_inplace_deepcopy_true_breaks_reference():
    data = {"a": {"nested": [1, 2]}}
    mapping = {"a": "x"}

    out = rename_fields_in_dict(data, mapping, inplace=False, deepcopy=True)

    assert out == {"x": {"nested": [1, 2]}}
    assert out["x"] is not data["a"]
    assert out["x"]["nested"] is not data["a"]["nested"]

    out["x"]["nested"].append(3)
    assert data["a"]["nested"] == [1, 2]


def test_non_inplace_deepcopy_false_shares_reference():
    nested = {"nested": [1, 2]}
    data = {"a": nested}
    mapping = {"a": "x"}

    out = rename_fields_in_dict(data, mapping, inplace=False, deepcopy=False)

    assert out["x"] is nested  # same object
    out["x"]["nested"].append(3)
    assert data["a"]["nested"] == [1, 2, 3]


def test_inplace_returns_same_object_and_mutates_in_place():
    data = {"a": 1, "b": 2}
    mapping = {"a": "x"}

    out = rename_fields_in_dict(data, mapping, inplace=True)

    assert out is data
    assert data == {"x": 1, "b": 2}


def test_inplace_skips_missing_and_identity_and_preserves_others():
    data = {"a": 1, "b": 2, "c": 3}
    mapping = {"a": "a", "missing": "z", "b": "x"}

    out = rename_fields_in_dict(data, mapping, inplace=True)

    assert out is data
    assert data == {"a": 1, "x": 2, "c": 3}


def test_inplace_collision_chain_a_to_b_b_to_c_is_safe():
    # This is the classic failure case of naive inplace renaming.
    data = {"a": 1, "b": 2, "c": 3}
    mapping = {"a": "b", "b": "c"}

    out = rename_fields_in_dict(data, mapping, inplace=True)

    assert out is data
    # 'c' overwritten by old 'b'
    assert data == {"b": 1, "c": 2}


def test_inplace_cycle_a_to_b_b_to_a_is_safe_and_swaps():
    data = {"a": 1, "b": 2}
    mapping = {"a": "b", "b": "a"}

    out = rename_fields_in_dict(data, mapping, inplace=True)

    assert out is data
    assert data == {"a": 2, "b": 1}


def test_inplace_overwrites_existing_destination_key():
    data = {"a": 1, "b": 999, "x": 7}
    mapping = {"a": "b"}

    rename_fields_in_dict(data, mapping, inplace=True)

    assert data == {"b": 1, "x": 7}


def test_inplace_mapping_order_controls_duplicate_destination_winner():
    data = {"a": 1, "b": 2}
    mapping = {"a": "x", "b": "x"}  # b processed after a => b wins

    rename_fields_in_dict(data, mapping, inplace=True)

    assert data == {"x": 2}


def test_inplace_mapping_order_controls_duplicate_destination_winner_reversed():
    data = {"a": 1, "b": 2}
    mapping = {"b": "x", "a": "x"}  # a processed after b => a wins

    rename_fields_in_dict(data, mapping, inplace=True)

    assert data == {"x": 1}


def test_inplace_preserves_value_object_identity_when_moving():
    # deepcopy argument is irrelevant for inplace: values should be moved, not copied.
    lst = [1, 2]
    data = {"a": lst}
    mapping = {"a": "b"}

    rename_fields_in_dict(data, mapping, inplace=True, deepcopy=True)
    assert data["b"] is lst

    data["b"].append(3)
    assert lst == [1, 2, 3]


def test_inplace_does_not_leave_temporary_keys_behind_for_string_key_dict():
    data = {"a": 1, "b": 2}
    mapping = {"a": "b", "b": "a"}  # forces temp keys internally

    rename_fields_in_dict(data, mapping, inplace=True)

    assert set(data.keys()) == {"a", "b"}
    assert all(isinstance(k, str) for k in data.keys())


@pytest.mark.parametrize(
    "data,mapping,expected",
    [
        ({1: "one", 2: "two"}, {1: 10}, {10: "one", 2: "two"}),
        ({(1, 2): 3, "x": 9}, {(1, 2): "pair"}, {"pair": 3, "x": 9}),
        ({"a": 1, "b": 2}, {"missing": "x"}, {"a": 1, "b": 2}),
    ],
)
def test_works_with_non_string_keys_inplace_true(data, mapping, expected):
    rename_fields_in_dict(data, mapping, inplace=True)
    assert data == expected


@pytest.mark.parametrize(
    "data,mapping,expected",
    [
        ({1: "one", 2: "two"}, {1: 10}, {10: "one", 2: "two"}),
        ({(1, 2): 3, "x": 9}, {(1, 2): "pair"}, {"pair": 3, "x": 9}),
        ({"a": 1, "b": 2}, {"missing": "x"}, {"a": 1, "b": 2}),
    ],
)
def test_works_with_non_string_keys_inplace_false(data, mapping, expected):
    out = rename_fields_in_dict(data, mapping, inplace=False)
    assert out == expected
    assert out is not data