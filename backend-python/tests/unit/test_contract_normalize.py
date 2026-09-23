from __future__ import annotations

import pytest

from reactor_backend.contracts.normalize import drop_additive, normalize_json


def test_normalizes_only_allowlisted_paths_and_preserves_shape() -> None:
    value = {
        "data": {
            "visitorId": "v-java",
            "named": False,
            "runs": [
                {"requestId": "r-1", "status": "SUCCESS"},
                {"requestId": "r-2", "status": "FAILED"},
            ],
        }
    }

    normalized = normalize_json(
        value,
        ("/data/visitorId", "/data/runs/*/requestId"),
    )

    assert normalized == {
        "data": {
            "visitorId": "<contract-ignored>",
            "named": False,
            "runs": [
                {"requestId": "<contract-ignored>", "status": "SUCCESS"},
                {"requestId": "<contract-ignored>", "status": "FAILED"},
            ],
        }
    }
    assert value["data"]["visitorId"] == "v-java"


def test_rejects_non_pointer_ignore_rule() -> None:
    with pytest.raises(ValueError, match="must start"):
        normalize_json({"id": "value"}, ("id",))


def test_rejects_unresolvable_ignore_pointer() -> None:
    """A missing *intermediate* segment is a broken allowlist, not a no-op."""

    with pytest.raises(ValueError, match="unresolvable JSON pointer segment"):
        normalize_json({"data": {"ok": 1}}, ("/data/missing/deeper",))


def test_rejects_non_integer_list_index_token() -> None:
    with pytest.raises(ValueError, match="list index token must be an integer"):
        normalize_json({"data": {"runs": []}}, ("/data/runs/abc/useTimes",))


def test_rejects_out_of_range_list_index() -> None:
    with pytest.raises(ValueError, match="list index out of range"):
        normalize_json({"data": {"runs": [1, 2]}}, ("/data/runs/5",))


def test_rejects_descending_into_scalar() -> None:
    with pytest.raises(ValueError, match="cannot descend"):
        normalize_json({"a": "scalar"}, ("/a/b",))


def test_absent_final_leaf_is_a_no_op() -> None:
    """One pointer list also declares additive fields.

    An additive leaf is by definition absent from at least one side at capture
    time, so a missing *final* key must stay a no-op. Only structure errors raise.
    """

    value = {"data": {"ok": 1}}
    assert normalize_json(value, ("/data/visitorId",)) == value
    assert normalize_json(value, ("/data/extra",)) == value


def test_drop_additive_removes_declared_candidate_only_leaf() -> None:
    golden = {"data": {"a": 1}}
    candidate = {"data": {"a": 1, "extra": 2}}

    assert drop_additive(golden, candidate, ("/data/extra",)) == {"data": {"a": 1}}


def test_drop_additive_keeps_removal_as_a_difference() -> None:
    golden = {"data": {"a": 1, "gone": 2}}
    candidate = {"data": {"a": 1}}

    assert drop_additive(golden, candidate, ("/data/gone",)) == {"data": {"a": 1}}


def test_drop_additive_never_deletes_list_elements() -> None:
    golden = {"data": {"runs": [{"id": "a"}]}}
    candidate = {"data": {"runs": [{"id": "a"}, {"id": "b"}]}}

    assert drop_additive(golden, candidate, ("/data/runs/*",)) == candidate
