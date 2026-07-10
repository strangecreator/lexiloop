import copy
import pytest

# local imports
from tools import exclude_fields_from_dict, truncate_dict_to_fields, extend_dict


def _sample_data():
    # nested mutable objects to test deep vs shallow copying
    return {
        "a": 1,
        "b": {"x": 10},
        "c": [1, 2, 3],
        "d": "keep",
    }


def _sample_new_data():
    return {
        "b": {"x": 999},        # collides with existing key
        "e": {"y": 5},          # new key
        "f": [7, 8],            # new key (list)
    }


def _make_data():
    data = {
        "a": 1,
        "b": {"x": 1, "y": 2},
        "c": {"z": {"u": 1}},
        "d": [1, 2],
    }
    new_data = {
        "a": 999,
        "b": {"y": 222, "k": 3},
        "c": {"z": {"u": 10, "v": 2}, "w": 5},
        "d": [9],
        "e": {"n": 1},
    }
    return data, new_data


def _expected(override: bool):
    if override:
        return {
            "a": 999,
            "b": {"x": 1, "y": 222, "k": 3},
            "c": {"z": {"u": 10, "v": 2}, "w": 5},
            "d": [9],
            "e": {"n": 1},
        }
    else:
        return {
            "a": 1,
            "b": {"x": 1, "y": 2, "k": 3},
            "c": {"z": {"u": 1, "v": 2}, "w": 5},
            "d": [1, 2],
            "e": {"n": 1},
        }


# ----------------------------------- exclude_fields_from_dict -----------------------------------

def test_exclude_fields_not_inplace_deepcopy_does_not_mutate_original_and_deepcopies():
    data = _sample_data()
    original = copy.deepcopy(data)

    out = exclude_fields_from_dict(data, fields=["a", "missing"], inplace=False, deepcopy=True)

    # original untouched
    assert data == original

    # output has key removed + ignores missing key
    assert "a" not in out
    assert set(out.keys()) == {"b", "c", "d"}

    # deep copy: nested objects should NOT be the same objects
    assert out["b"] == data["b"] and out["b"] is not data["b"]
    assert out["c"] == data["c"] and out["c"] is not data["c"]

    # mutating output should not affect original
    out["b"]["x"] = 111
    out["c"].append(999)
    assert data["b"]["x"] == 10
    assert data["c"] == [1, 2, 3]


def test_exclude_fields_not_inplace_shallowcopy_keeps_nested_references():
    data = _sample_data()
    out = exclude_fields_from_dict(data, fields=["a"], inplace=False, deepcopy=False)

    assert "a" not in out
    assert set(out.keys()) == {"b", "c", "d"}

    # shallow copy: nested objects are shared
    assert out["b"] is data["b"]
    assert out["c"] is data["c"]

    # mutating output mutates original due to shared refs
    out["b"]["x"] = 321
    out["c"].append(42)
    assert data["b"]["x"] == 321
    assert data["c"] == [1, 2, 3, 42]


def test_exclude_fields_inplace_mutates_and_returns_same_object():
    data = _sample_data()
    out = exclude_fields_from_dict(data, fields=["a", "c", "missing"], inplace=True, deepcopy=True)

    assert out is data
    assert set(data.keys()) == {"b", "d"}  # removed a, c; ignored missing
    assert "a" not in data
    assert "c" not in data


# ----------------------------------- truncate_dict_to_fields -----------------------------------

def test_truncate_not_inplace_preserves_fields_order_and_omits_missing():
    data = _sample_data()
    out = truncate_dict_to_fields(data, fields=["d", "missing", "b"], inplace=False, deepcopy=True)

    # order follows "fields" list (for inplace=False path)
    assert list(out.keys()) == ["d", "b"]
    assert out["d"] == "keep"
    assert out["b"] == {"x": 10}

    # deep copy per-field: nested objects not shared
    assert out["b"] is not data["b"]
    out["b"]["x"] = 77
    assert data["b"]["x"] == 10


def test_truncate_not_inplace_shallowcopy_shares_nested_selected_values():
    data = _sample_data()
    out = truncate_dict_to_fields(data, fields=["b", "c"], inplace=False, deepcopy=False)

    assert set(out.keys()) == {"b", "c"}
    assert out["b"] is data["b"]
    assert out["c"] is data["c"]

    out["b"]["x"] = 555
    out["c"].append(-1)
    assert data["b"]["x"] == 555
    assert data["c"][-1] == -1


def test_truncate_inplace_keeps_only_requested_keys_and_returns_same_object():
    data = _sample_data()
    b_ref = data["b"]  # should remain same object (inplace path doesn't deepcopy)
    out = truncate_dict_to_fields(data, fields=["b", "d", "missing"], inplace=True, deepcopy=True)

    assert out is data
    assert set(data.keys()) == {"b", "d"}

    # order should remain as in the original dict (pop() doesn't reorder survivors)
    # original insertion order: a, b, c, d -> after removing a,c => b, d
    assert list(data.keys()) == ["b", "d"]

    # inplace path keeps original nested references (deepcopy flag is effectively irrelevant here)
    assert data["b"] is b_ref


# ----------------------------------- extend_dict -----------------------------------

@pytest.mark.parametrize("deepcopy_flag", [True, False])
def test_extend_not_inplace_override_true_updates_and_does_not_mutate_original(deepcopy_flag: bool):
    data = _sample_data()
    new_data = _sample_new_data()

    data_before = copy.deepcopy(data)
    new_before = copy.deepcopy(new_data)

    out = extend_dict(data, new_data, inplace=False, override=True, deepcopy=deepcopy_flag)

    # originals unchanged
    assert data == data_before
    assert new_data == new_before

    # override=True: "b" replaced; new keys added
    assert out["b"] == {"x": 999}
    assert out["e"] == {"y": 5}
    assert out["f"] == [7, 8]
    assert out["a"] == 1

    if deepcopy_flag:
        # values coming from new_data are deepcopied
        assert out["b"] is not new_data["b"]
        assert out["e"] is not new_data["e"]
        assert out["f"] is not new_data["f"]
    else:
        # values coming from new_data are shared
        assert out["b"] is new_data["b"]
        assert out["e"] is new_data["e"]
        assert out["f"] is new_data["f"]


def test_extend_not_inplace_override_false_does_not_override_existing_keys():
    data = _sample_data()
    new_data = _sample_new_data()

    out = extend_dict(data, new_data, inplace=False, override=False, deepcopy=True)

    # existing key "b" should NOT be overridden
    assert out["b"] == {"x": 10}

    # new keys should be added
    assert out["e"] == {"y": 5}
    assert out["f"] == [7, 8]

    # deep copy at start: untouched nested values from original should not be shared
    assert out["b"] is not data["b"]
    assert out["c"] is not data["c"]


def test_extend_not_inplace_override_false_shallowcopy_shares_untouched_original_nested():
    data = _sample_data()
    new_data = _sample_new_data()

    out = extend_dict(data, new_data, inplace=False, override=False, deepcopy=False)

    # "b" not overridden
    assert out["b"] == {"x": 10}
    # shallow copy of data: "b" and "c" refs are shared with original (since not overridden)
    assert out["b"] is data["b"]
    assert out["c"] is data["c"]


def test_extend_inplace_mutates_and_returns_same_object():
    data = _sample_data()
    new_data = _sample_new_data()

    out = extend_dict(data, new_data, inplace=True, override=False, deepcopy=True)

    assert out is data
    # override=False => do not override "b", but add "e","f"
    assert data["b"] == {"x": 10}
    assert data["e"] == {"y": 5}
    assert data["f"] == [7, 8]


@pytest.mark.parametrize("override", [True, False])
@pytest.mark.parametrize("inplace", [True, False])
def test_extend_dict_deep_deepcopy_true_core_behaviour(override: bool, inplace: bool):
    data, new_data = _make_data()
    data_before = copy.deepcopy(data)
    new_before = copy.deepcopy(new_data)

    res = extend_dict(
        data,
        new_data,
        inplace=inplace,
        override=override,
        deepcopy=True,
        deep=True,
    )

    assert res == _expected(override)

    # inplace contract + original preservation
    if inplace:
        assert res is data
    else:
        assert res is not data
        assert data == data_before  # original unchanged

    # new_data is never mutated
    assert new_data == new_before

    # deepcopy=True: new_data mutations after merge must not leak into result
    new_data["e"]["n"] = 777
    new_data["b"]["k"] = 999
    new_data["c"]["z"]["v"] = 888
    assert res == _expected(override)

    # When inplace=False and deepcopy=True, result should not share nested dicts with original
    if not inplace:
        assert res["b"] is not data_before["b"]
        assert res["c"] is not data_before["c"]
        assert res["c"]["z"] is not data_before["c"]["z"]


def test_extend_dict_deep_override_false_still_merges_nested_dicts():
    # This is the key nuance: override=False does NOT overwrite leaf values,
    # but nested dicts still get missing keys added when deep=True.
    data = {"cfg": {"keep": 1, "nested": {"a": 1}}}
    new_data = {"cfg": {"keep": 999, "nested": {"a": 999, "b": 2}, "new": 3}}

    res = extend_dict(data, new_data, inplace=False, override=False, deepcopy=True, deep=True)

    assert res == {"cfg": {"keep": 1, "nested": {"a": 1, "b": 2}, "new": 3}}


def test_extend_dict_deep_does_not_merge_non_dict_types():
    data = {"x": {"a": 1}, "y": 1, "z": {"k": 1}}
    new_data = {"x": [1, 2, 3], "y": {"b": 2}, "z": {"k": [9]}}

    # override=False: conflicts preserved, but z.k is a leaf and exists -> stays 1
    res_no = extend_dict(data, new_data, inplace=False, override=False, deepcopy=True, deep=True)
    assert res_no == {"x": {"a": 1}, "y": 1, "z": {"k": 1}}

    # override=True: conflicting non-dict values overwritten
    res_yes = extend_dict(data, new_data, inplace=False, override=True, deepcopy=True, deep=True)
    assert res_yes == {"x": [1, 2, 3], "y": {"b": 2}, "z": {"k": [9]}}


def test_extend_dict_deep_deepcopy_false_shares_new_objects():
    data = {"a": {"x": 1}}
    new_data = {"b": {"y": 2}}

    res = extend_dict(data, new_data, inplace=False, override=True, deepcopy=False, deep=True)

    # key "b" didn't exist -> assigned directly -> same object when deepcopy=False
    assert res["b"] is new_data["b"]

    # Mutating new_data mutates res
    new_data["b"]["y"] = 999
    assert res["b"]["y"] == 999


def test_extend_dict_deep_deepcopy_true_does_not_share_new_objects():
    data = {"a": {"x": 1}}
    new_data = {"b": {"y": 2}}

    res = extend_dict(data, new_data, inplace=False, override=True, deepcopy=True, deep=True)

    assert res["b"] == {"y": 2}
    assert res["b"] is not new_data["b"]

    new_data["b"]["y"] = 999
    assert res["b"]["y"] == 2


def test_extend_dict_deep_inplace_false_deepcopy_false_can_mutate_original_nested():
    # With inplace=False but deepcopy=False, only a shallow copy of `data` is made.
    # Deep merge mutates nested dicts, so original nested dicts can be affected.
    data = {"b": {"x": 1}}
    new_data = {"b": {"y": 2}}

    res = extend_dict(data, new_data, inplace=False, override=True, deepcopy=False, deep=True)

    assert res == {"b": {"x": 1, "y": 2}}
    # This is the important behavior: original data's nested dict got modified
    assert data == {"b": {"x": 1, "y": 2}}


def test_extend_dict_deep_inplace_false_deepcopy_true_does_not_mutate_original_nested():
    data = {"b": {"x": 1}}
    new_data = {"b": {"y": 2}}

    res = extend_dict(data, new_data, inplace=False, override=True, deepcopy=True, deep=True)

    assert res == {"b": {"x": 1, "y": 2}}
    assert data == {"b": {"x": 1}}  # unchanged