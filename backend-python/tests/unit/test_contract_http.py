from __future__ import annotations

import httpx
import pytest

from reactor_backend.contracts.http import capture_http, compare_http
from reactor_backend.contracts.models import (
    CookieSnapshot,
    HttpCase,
    HttpSnapshot,
    NormalizationRules,
)


def _snapshot(
    body: object,
    *,
    status: int = 200,
    cookies: tuple[CookieSnapshot, ...] = (),
) -> HttpSnapshot:
    return HttpSnapshot(
        status_code=status,
        content_type="application/json",
        headers={},
        cookies=cookies,
        body=body,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_http_capture_compares_types_nulls_headers_and_cookie_attributes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pageNo"] == "1"
        return httpx.Response(
            200,
            json={"code": "0000", "info": "成功", "data": {"id": "random", "next": None}},
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "X-Contract-Version": "1",
                "Set-Cookie": (
                    "visitor_id=random-value; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax"
                ),
            },
        )

    case = HttpCase(
        name="visitor",
        method="GET",
        path="/visitor",
        query={"pageNo": "1"},
        compared_headers=("x-contract-version",),
        normalization=NormalizationRules(
            ignored_json_pointers=("/body/data/id",),
            ignored_cookie_values=("visitor_id",),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        first = await capture_http(client, case)
        second = await capture_http(client, case)

    assert compare_http(first, second) == []
    assert first.content_type == "application/json"
    assert first.cookies[0].value_fingerprint == "<contract-ignored>"
    assert first.cookies[0].attributes["httponly"] is True
    assert first.cookies[0].attributes["samesite"] == "Lax"


@pytest.mark.asyncio
async def test_http_comparator_reports_bool_integer_type_drift() -> None:
    case = HttpCase(name="type", method="GET", path="/")

    async def capture(value: bool | int) -> HttpSnapshot:
        handler = lambda request: httpx.Response(200, json={"data": value})  # noqa: E731
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await capture_http(client, case)

    differences = compare_http(await capture(True), await capture(1))

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/body/data", "type mismatch")
    ]


def test_http_comparator_reports_status_code_drift() -> None:
    differences = compare_http(
        _snapshot({"code": "0000"}, status=200),
        _snapshot({"code": "0000"}, status=404),
    )

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/status_code", "value mismatch")
    ]


def test_http_comparator_reports_null_versus_missing_and_value() -> None:
    golden = _snapshot({"data": {"next": None}})

    missing = compare_http(golden, _snapshot({"data": {}}))
    assert [(difference.path, difference.reason) for difference in missing] == [
        ("/body/data/<keys>", "field mismatch")
    ]

    value = compare_http(golden, _snapshot({"data": {"next": 1}}))
    assert [(difference.path, difference.reason) for difference in value] == [
        ("/body/data/next", "type mismatch")
    ]


def test_http_comparator_reports_list_order_drift() -> None:
    golden = _snapshot({"data": {"runs": [{"id": "a"}, {"id": "b"}]}})
    candidate = _snapshot({"data": {"runs": [{"id": "b"}, {"id": "a"}]}})

    differences = compare_http(golden, candidate)

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/body/data/runs/0/id", "value mismatch"),
        ("/body/data/runs/1/id", "value mismatch"),
    ]


def test_http_comparator_ignores_object_key_order() -> None:
    golden = _snapshot({"data": {"alpha": 1, "beta": 2}})
    candidate = _snapshot({"data": {"beta": 2, "alpha": 1}})

    assert compare_http(golden, candidate) == []


@pytest.mark.asyncio
async def test_http_cookie_fingerprint_is_stable_and_mismatch_is_detected() -> None:
    async def capture(value: str) -> HttpSnapshot:
        handler = lambda request: httpx.Response(  # noqa: E731
            200,
            json={},
            headers={"Set-Cookie": f"ai_agent_visitor_token={value}; Path=/; HttpOnly"},
        )
        case = HttpCase(name="cookie", method="GET", path="/")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await capture_http(client, case)

    first = await capture("stable-token")
    second = await capture("stable-token")
    other = await capture("different-token")

    assert compare_http(first, second) == []
    assert first.cookies[0].value_fingerprint == second.cookies[0].value_fingerprint
    assert first.cookies[0].value_fingerprint != other.cookies[0].value_fingerprint

    differences = compare_http(first, other)
    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/cookies/0/value_fingerprint", "value mismatch")
    ]
    assert "stable-token" not in str(first.as_dict())


def test_http_comparator_reports_cookie_name_drift() -> None:
    golden = _snapshot(
        {},
        cookies=(CookieSnapshot("ai_agent_visitor_token", "abc", {"path": "/"}),),
    )
    candidate = _snapshot(
        {},
        cookies=(CookieSnapshot("other_token", "abc", {"path": "/"}),),
    )

    differences = compare_http(golden, candidate)

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/cookies/0/name", "value mismatch")
    ]


def test_http_comparator_reports_cookie_attribute_drift() -> None:
    golden = _snapshot(
        {},
        cookies=(
            CookieSnapshot(
                "ai_agent_visitor_token",
                "abc",
                {"path": "/", "httponly": True, "samesite": "Lax"},
            ),
        ),
    )
    candidate = _snapshot(
        {},
        cookies=(
            CookieSnapshot(
                "ai_agent_visitor_token",
                "abc",
                {"path": "/admin", "httponly": False, "samesite": "Lax"},
            ),
        ),
    )

    differences = compare_http(golden, candidate)

    assert {(difference.path, difference.reason) for difference in differences} == {
        ("/cookies/0/attributes/path", "value mismatch"),
        ("/cookies/0/attributes/httponly", "value mismatch"),
    }


def test_http_capture_round_trips_utf8_body() -> None:
    body = {"code": "0000", "info": "成功", "data": {"title": "中文标题 🎉", "note": "ünïcödé"}}
    snapshot = _snapshot(body)

    assert HttpSnapshot.from_dict(snapshot.as_dict()) == snapshot
    assert snapshot.body == body


@pytest.mark.asyncio
async def test_allowlist_pointer_can_address_a_cookie_attribute() -> None:
    """``expires`` is derived from ``max-age`` plus the server clock.

    It has to be declarable per case — it cannot be dropped globally — so
    allowlist pointers reach the capture document, not just the body.
    """

    async def capture(expires: str) -> HttpSnapshot:
        handler = lambda request: httpx.Response(  # noqa: E731
            200,
            json={"code": "0000"},
            headers={
                "Set-Cookie": (
                    f"ai_agent_visitor_token=tok; Path=/; Max-Age=31536000; "
                    f"Expires={expires}; HttpOnly; SameSite=Lax"
                )
            },
        )
        case = HttpCase(
            name="bootstrap",
            method="GET",
            path="/",
            normalization=NormalizationRules(
                ignored_json_pointers=("/cookies/*/attributes/expires",),
            ),
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await capture_http(client, case)

    first = await capture("Wed, 22 Sep 2027 20:23:35 GMT")
    second = await capture("Thu, 23 Sep 2027 08:00:00 GMT")

    assert compare_http(first, second) == []
    assert first.cookies[0].attributes["expires"] == "<contract-ignored>"
    assert first.cookies[0].attributes["max-age"] == "31536000"
    assert first.cookies[0].attributes["httponly"] is True


def test_undeclared_additive_field_is_a_difference() -> None:
    golden = _snapshot({"data": {"a": 1}})
    candidate = _snapshot({"data": {"a": 1, "extra": 2}})

    differences = compare_http(golden, candidate)

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/body/data/<keys>", "field mismatch")
    ]


def test_declared_additive_field_passes_but_removal_never_does() -> None:
    golden = _snapshot({"data": {"a": 1}})
    candidate = _snapshot({"data": {"a": 1, "extra": 2}})

    assert compare_http(golden, candidate, ignored_json_pointers=("/body/data/extra",)) == []

    removed_golden = _snapshot({"data": {"a": 1, "gone": 2}})
    removed_candidate = _snapshot({"data": {"a": 1}})
    differences = compare_http(
        removed_golden,
        removed_candidate,
        ignored_json_pointers=("/body/data/gone",),
    )

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/body/data/<keys>", "field mismatch")
    ]
