from __future__ import annotations

import json
from pathlib import Path

from reactor_backend.contracts.manifest import load_cases


def test_manifest_skips_case_with_missing_fixture_environment(
    tmp_path: Path, monkeypatch: object
) -> None:
    del monkeypatch
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {"name": "ready", "method": "GET", "path": "/ready"},
                    {
                        "name": "fixture",
                        "method": "GET",
                        "path": "/session/${CONTRACT_TEST_MISSING_SESSION}",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    cases, skipped = load_cases(path)

    assert [case.name for case in cases] == ["ready"]
    assert skipped == ["fixture: missing CONTRACT_TEST_MISSING_SESSION"]
