from __future__ import annotations

import pytest

from reactor_backend.contracts.normalize import normalize_json


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
