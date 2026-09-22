from __future__ import annotations

import httpx
import pytest

from reactor_backend.contracts.http import capture_http, compare_http
from reactor_backend.contracts.models import HttpCase, NormalizationRules


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
            ignored_json_pointers=("/data/id",),
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

    async def capture(value: bool | int) -> object:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": value}))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await capture_http(client, case)

    java = await capture(True)
    python = await capture(1)
    differences = compare_http(java, python)  # type: ignore[arg-type]

    assert [(difference.path, difference.reason) for difference in differences] == [
        ("/body/data", "type mismatch")
    ]
