from __future__ import annotations

import hashlib
import json
from http.cookies import SimpleCookie

import httpx

from reactor_backend.contracts.models import (
    CookieSnapshot,
    Difference,
    HttpCase,
    HttpSnapshot,
    JsonValue,
)
from reactor_backend.contracts.normalize import normalize_json


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
    body = normalize_json(body, case.normalization.ignored_json_pointers)
    compared_headers = {
        name.lower(): response.headers[name]
        for name in case.compared_headers
        if name.lower() in response.headers
    }
    cookies = _snapshot_cookies(
        response.headers.get_list("set-cookie"),
        set(case.normalization.ignored_cookie_values),
    )
    return HttpSnapshot(
        status_code=response.status_code,
        content_type=content_type,
        headers=compared_headers,
        cookies=cookies,
        body=body,
    )


def compare_http(java: HttpSnapshot, python: HttpSnapshot) -> list[Difference]:
    differences: list[Difference] = []
    _compare("/status_code", java.status_code, python.status_code, differences)
    _compare("/content_type", java.content_type, python.content_type, differences)
    _compare("/headers", java.headers, python.headers, differences)
    _compare("/cookies", java.cookies, python.cookies, differences)
    _compare("/body", java.body, python.body, differences)
    return differences


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


def dump_snapshot(snapshot: HttpSnapshot) -> str:
    return json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
