from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from reactor_backend.contracts import cli
from reactor_backend.contracts.http import (
    compare_http,
    load_capture_file,
    load_snapshot,
    save_capture_file,
    save_snapshot,
)
from reactor_backend.contracts.models import (
    CaptureCase,
    CaptureFile,
    CookieSnapshot,
    HttpSnapshot,
)

_BODY = {
    "code": "0000",
    "info": "成功",
    "data": {"title": "中文标题 🎉", "next": None, "ok": True, "count": 1},
}
_COOKIE = CookieSnapshot(
    "ai_agent_visitor_token",
    "0123456789abcdef",
    {"path": "/", "httponly": True, "samesite": "Lax"},
)


def _snapshot(body: object = _BODY) -> HttpSnapshot:
    return HttpSnapshot(
        status_code=200,
        content_type="application/json",
        headers={"x-contract-version": "1"},
        cookies=(_COOKIE,),
        body=body,  # type: ignore[arg-type]
    )


def test_snapshot_round_trip_and_offline_compare(tmp_path: Path) -> None:
    """as_dict/from_dict are inverses and a golden matches itself exactly."""

    snapshot = _snapshot()

    assert HttpSnapshot.from_dict(json.loads(json.dumps(snapshot.as_dict()))) == snapshot

    path = tmp_path / "golden.json"
    save_snapshot(path, snapshot)
    assert load_snapshot(path) == snapshot

    document = CaptureFile(
        mode="java-baseline",
        base_url="http://127.0.0.1:8100",
        cases=(CaptureCase(name="c1", snapshot=snapshot),),
        skipped=(),
    )
    capture_path = tmp_path / "capture.json"
    save_capture_file(capture_path, document)
    assert load_capture_file(capture_path) == document

    assert compare_http(snapshot, load_snapshot(path)) == []


def test_offline_compare_detects_adversarial_mutations() -> None:
    golden = _snapshot()
    base = {"title": "中文标题 🎉", "next": None, "ok": True, "count": 1}

    def with_data(data: dict[str, object]) -> HttpSnapshot:
        return _snapshot({"code": "0000", "info": "成功", "data": data})

    mutated_value = with_data({**base, "count": 2})
    assert [(d.path, d.reason) for d in compare_http(golden, mutated_value)] == [
        ("/body/data/count", "value mismatch")
    ]

    mutated_type = with_data({**base, "ok": 1})
    assert [(d.path, d.reason) for d in compare_http(golden, mutated_type)] == [
        ("/body/data/ok", "type mismatch")
    ]

    deleted_field = with_data({"title": "中文标题 🎉", "next": None, "ok": True})
    assert [(d.path, d.reason) for d in compare_http(golden, deleted_field)] == [
        ("/body/data/<keys>", "field mismatch")
    ]

    added_field = with_data({**base, "extra": 2})
    assert [(d.path, d.reason) for d in compare_http(golden, added_field)] == [
        ("/body/data/<keys>", "field mismatch")
    ]

    mutated_cookie = HttpSnapshot(
        status_code=200,
        content_type="application/json",
        headers={"x-contract-version": "1"},
        cookies=(
            CookieSnapshot(
                "ai_agent_visitor_token",
                "fedcba9876543210",
                dict(_COOKIE.attributes),
            ),
        ),
        body=_BODY,
    )
    assert [(d.path, d.reason) for d in compare_http(golden, mutated_cookie)] == [
        ("/cookies/0/value_fingerprint", "value mismatch")
    ]


def test_offline_cli_compare_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot()
    golden_path = tmp_path / "golden.json"
    response_path = tmp_path / "response.json"
    save_capture_file(
        golden_path,
        CaptureFile("java-baseline", "http://java", (CaptureCase("c1", snapshot=snapshot),), ()),
    )
    save_capture_file(
        response_path,
        CaptureFile("python-capture", "http://python", (CaptureCase("c1", snapshot=snapshot),), ()),
    )

    manifest_path = tmp_path / "cases.json"
    manifest_path.write_text(
        json.dumps({"cases": [{"name": "c1", "method": "GET", "path": "/x"}]}),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reactor-contract",
            str(manifest_path),
            "--golden",
            str(golden_path),
            "--response",
            str(response_path),
            "--output",
            str(report_path),
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "comparison"
    assert report["cases"][0]["name"] == "c1"
    assert report["cases"][0]["matched"] is True
    assert report["cases"][0]["differences"] == []


def test_offline_cli_compare_reports_missing_case_without_hiding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot()
    golden_path = tmp_path / "golden.json"
    response_path = tmp_path / "response.json"
    save_capture_file(
        golden_path,
        CaptureFile("java-baseline", "http://java", (CaptureCase("c1", snapshot=snapshot),), ()),
    )
    save_capture_file(
        response_path,
        CaptureFile(
            "python-capture",
            "http://python",
            (CaptureCase("other", snapshot=snapshot),),
            (),
        ),
    )

    manifest_path = tmp_path / "cases.json"
    manifest_path.write_text(
        json.dumps({"cases": [{"name": "c1", "method": "GET", "path": "/x"}]}),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reactor-contract",
            str(manifest_path),
            "--golden",
            str(golden_path),
            "--response",
            str(response_path),
            "--output",
            str(report_path),
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["cases"][0]["matched"] is False
    assert "has no case named c1" in report["cases"][0]["error"]
