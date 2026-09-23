from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from http.cookies import SimpleCookie
from pathlib import Path
from typing import cast

import httpx

from reactor_backend.contracts.models import (
    CaptureFile,
    CookieSnapshot,
    Difference,
    HttpCase,
    HttpSnapshot,
    JsonValue,
)
from reactor_backend.contracts.normalize import drop_additive, normalize_json


async def capture_http(client: httpx.AsyncClient, case: HttpCase) -> HttpSnapshot:
    response = await client.request(
        case.method,
        case.path,
        params=case.query,
        headers=case.headers,
        json=case.json_body,
    )
    content_type = _media_type(response.headers.get("content-type"))
    body = _response_body(response, content_type)
    compared_headers = {
        name.lower(): response.headers[name]
        for name in case.compared_headers
        if name.lower() in response.headers
    }
    cookies = _snapshot_cookies(
        response.headers.get_list("set-cookie"),
        set(case.normalization.ignored_cookie_values),
    )
    snapshot = HttpSnapshot(
        status_code=response.status_code,
        content_type=content_type,
        headers=compared_headers,
        cookies=cookies,
        body=body,
    )
    return _normalize_snapshot(snapshot, case.normalization.ignored_json_pointers)


def compare_http(
    java: HttpSnapshot,
    python: HttpSnapshot,
    *,
    ignored_json_pointers: tuple[str, ...] = (),
) -> list[Difference]:
    """Compare a reference snapshot against a candidate snapshot.

    ``java``/``python`` name the two sides of a migration comparison: the
    recorded reference (golden) and the candidate response. With
    ``ignored_json_pointers``, candidate-only leaves declared on the allowlist
    are dropped before the comparison so an additive field may pass; removals on
    the candidate side never pass.

    Allowlist pointers address the capture document (``HttpSnapshot.as_dict()``),
    so a body field is ``/body/data/visitorId`` and a cookie attribute is
    ``/cookies/*/attributes/expires``. The same list that replaces a
    nondeterministic value at capture time declares an additive field at compare
    time.
    """

    differences: list[Difference] = []
    candidate = python
    if ignored_json_pointers:
        candidate = _drop_snapshot_additive(java, python, ignored_json_pointers)
    _compare("/status_code", java.status_code, candidate.status_code, differences)
    _compare("/content_type", java.content_type, candidate.content_type, differences)
    _compare("/headers", java.headers, candidate.headers, differences)
    _compare(
        "/cookies",
        [cookie.as_dict() for cookie in java.cookies],
        [cookie.as_dict() for cookie in candidate.cookies],
        differences,
    )
    _compare("/body", java.body, candidate.body, differences)
    return differences


def _normalize_snapshot(snapshot: HttpSnapshot, pointers: tuple[str, ...]) -> HttpSnapshot:
    if not pointers:
        return snapshot
    payload = normalize_json(cast("JsonValue", snapshot.as_dict()), pointers)
    if not isinstance(payload, dict):
        raise ValueError("normalized snapshot must remain a JSON object")
    return HttpSnapshot.from_dict(payload)


def _drop_snapshot_additive(
    golden: HttpSnapshot,
    candidate: HttpSnapshot,
    pointers: tuple[str, ...],
) -> HttpSnapshot:
    payload = drop_additive(
        cast("JsonValue", golden.as_dict()),
        cast("JsonValue", candidate.as_dict()),
        pointers,
    )
    if not isinstance(payload, dict):
        raise ValueError("candidate snapshot must remain a JSON object")
    return HttpSnapshot.from_dict(payload)


def dump_snapshot(snapshot: HttpSnapshot) -> str:
    return json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def save_snapshot(path: Path, snapshot: HttpSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_snapshot(snapshot), encoding="utf-8")


def load_snapshot(path: Path) -> HttpSnapshot:
    return HttpSnapshot.from_dict(_read_object(path, "snapshot"))


def load_capture_file(path: Path) -> CaptureFile:
    return CaptureFile.from_dict(_read_object(path, "capture"))


def save_capture_file(path: Path, document: CaptureFile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_object(path: Path, label: str) -> Mapping[str, object]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{label} file must contain a JSON object: {path}")
    return raw


def _response_body(response: httpx.Response, content_type: str | None) -> JsonValue:
    if content_type == "application/json" or (content_type and content_type.endswith("+json")):
        parsed: JsonValue = response.json()
        return parsed
    return response.text


def _media_type(value: str | None) -> str | None:
    return value.split(";", 1)[0].strip().lower() if value else None


def _snapshot_cookies(
    set_cookie_headers: list[str], ignored_values: set[str]
) -> tuple[CookieSnapshot, ...]:
    snapshots: list[CookieSnapshot] = []
    for header in set_cookie_headers:
        parsed = SimpleCookie()
        parsed.load(header)
        for name, morsel in parsed.items():
            fingerprint = (
                "<contract-ignored>"
                if name in ignored_values
                else hashlib.sha256(morsel.value.encode()).hexdigest()[:16]
            )
            attributes: dict[str, str | bool] = {}
            for attribute in ("path", "domain", "expires", "max-age", "samesite"):
                if morsel[attribute]:
                    attributes[attribute] = morsel[attribute]
            for flag in ("secure", "httponly"):
                attributes[flag] = bool(morsel[flag])
            snapshots.append(CookieSnapshot(name, fingerprint, attributes))
    return tuple(sorted(snapshots, key=lambda item: item.name))


def _compare(path: str, java: object, python: object, output: list[Difference]) -> None:
    if type(java) is not type(python):
        output.append(Difference(path, java, python, "type mismatch"))
        return
    if isinstance(java, dict) and isinstance(python, dict):
        java_keys = set(java)
        python_keys = set(python)
        if java_keys != python_keys:
            output.append(Difference(
                f"{path}/<keys>",
                sorted(java_keys),
                sorted(python_keys),
                "field mismatch",
            ))
        for key in sorted(java_keys & python_keys):
            _compare(f"{path}/{key}", java[key], python[key], output)
        return
    if isinstance(java, (list, tuple)) and isinstance(python, (list, tuple)):
        if len(java) != len(python):
            output.append(Difference(f"{path}/<length>", len(java), len(python), "length mismatch"))
        for index, (java_item, python_item) in enumerate(zip(java, python, strict=False)):
            _compare(f"{path}/{index}", java_item, python_item, output)
        return
    if java != python:
        output.append(Difference(path, java, python, "value mismatch"))
