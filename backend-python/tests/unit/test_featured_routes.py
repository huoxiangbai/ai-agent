"""HTTP-surface pins for the three public featured GETs.

These cover the FastAPI drift traps that would otherwise silently change the
contract: 422-on-bad-query, 307-on-trailing-slash, and ``null`` dropping out of
the JSON body.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

from reactor_backend.api.coercion import CoercionError, coerce_int
from reactor_backend.config import Settings
from reactor_backend.main import create_app


def assert_spring_error_body(response: Any, status: int, path: str) -> None:
    """Pin the measured ``BasicErrorController`` shape.

    Measured 2026-09-23 against Java ``--spring.profiles.active=prod``: exactly
    ``timestamp, status, error, path`` in that order, UTC millis with ``+00:00``,
    ``error`` equal to the HTTP reason phrase, ``path`` = request URI sans query.
    Timestamp is compared structurally, not value-equal (it is ``now``).
    """
    body = response.json()
    assert list(body) == ["timestamp", "status", "error", "path"], body
    assert body["status"] == status
    assert body["error"] == response.reason_phrase
    assert body["path"] == path
    # 2026-09-23T10:08:05.470+00:00 — millisecond precision, '+00:00', never 'Z'.
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00", body["timestamp"]
    ), body["timestamp"]
    assert "detail" not in body
    assert "code" not in body


class FakeFeaturedUseCase:
    """Records calls; returns canned payloads so the envelope is the subject."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def query_home_cards(self, limit: int) -> list[dict[str, Any]]:
        self.calls.append(("home", (limit,)))
        return [{"featuredId": "f-1", "summary": None}]

    async def query_public_list(self, page_no: int, page_size: int) -> dict[str, Any]:
        self.calls.append(("list", (page_no, page_size)))
        return {"total": 0, "list": []}

    async def query_detail(self, featured_id: str | None) -> dict[str, Any] | None:
        self.calls.append(("detail", (featured_id,)))
        return None


class FakeDatabase:
    def __init__(self, _settings: Settings) -> None:
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


@contextmanager
def _client(
    use_case: FakeFeaturedUseCase | None = None,
) -> Iterator[tuple[FakeFeaturedUseCase, TestClient]]:
    app = create_app(Settings(), FakeDatabase)
    resolved = use_case or FakeFeaturedUseCase()
    with TestClient(app) as client:
        # Lifespan installs the real use case; tests replace it afterwards.
        app.state.featured_query_use_case = resolved
        yield resolved, client


def test_home_default_limit_is_6_when_param_missing() -> None:
    with _client() as (use_case, client):
        response = client.get("/api/agent/featured-conversations/home")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "0000"
    assert body["info"] == "成功"
    assert use_case.calls == [("home", (6,))]


def test_home_empty_limit_uses_default_not_422() -> None:
    with _client() as (use_case, client):
        response = client.get(
            "/api/agent/featured-conversations/home", params={"limit": ""}
        )

    assert response.status_code == 200
    assert use_case.calls == [("home", (6,))]


def test_home_whitespace_limit_uses_default() -> None:
    with _client() as (use_case, client):
        response = client.get(
            "/api/agent/featured-conversations/home", params={"limit": "   "}
        )

    assert response.status_code == 200
    assert use_case.calls == [("home", (6,))]


def test_home_non_numeric_limit_is_400_not_422() -> None:
    with _client() as (use_case, client):
        response = client.get(
            "/api/agent/featured-conversations/home", params={"limit": "abc"}
        )

    assert response.status_code == 400
    assert use_case.calls == []
    assert_spring_error_body(response, 400, "/api/agent/featured-conversations/home")


def test_list_default_page_1_size_20() -> None:
    with _client() as (use_case, client):
        response = client.get("/api/agent/featured-conversations")

    assert response.status_code == 200
    assert use_case.calls == [("list", (1, 20))]
    assert response.json()["data"] == {"total": 0, "list": []}


def test_list_unparsable_page_no_is_400() -> None:
    with _client() as (use_case, client):
        response = client.get("/api/agent/featured-conversations", params={"pageNo": "x"})

    assert response.status_code == 400
    assert use_case.calls == []
    assert_spring_error_body(response, 400, "/api/agent/featured-conversations")


def test_method_not_allowed_is_spring_shape_with_allow() -> None:
    with _client() as (use_case, client):
        response = client.post("/api/agent/featured-conversations/home")

    assert response.status_code == 405
    assert use_case.calls == []
    assert response.headers["allow"] == "GET"
    assert_spring_error_body(response, 405, "/api/agent/featured-conversations/home")


def test_unmapped_path_is_spring_shape() -> None:
    with _client() as (_use_case, client):
        response = client.get("/api/agent/featured-conversations/a/b")

    assert response.status_code == 404
    assert_spring_error_body(response, 404, "/api/agent/featured-conversations/a/b")


def test_detail_null_is_emitted_as_json_null() -> None:
    with _client() as (use_case, client):
        response = client.get("/api/agent/featured-conversations/missing-id")

    assert response.status_code == 200
    body = response.json()
    assert body == {"code": "0000", "info": "成功", "data": None}
    assert "data" in body  # key present, value null — not dropped
    assert use_case.calls == [("detail", ("missing-id",))]


def test_home_null_summary_survives_in_body() -> None:
    with _client() as (_use_case, client):
        response = client.get("/api/agent/featured-conversations/home")

    assert response.json()["data"] == [{"featuredId": "f-1", "summary": None}]


def test_trailing_slash_is_404_not_307() -> None:
    with _client() as (_use_case, client):
        response = client.get("/api/agent/featured-conversations/")

    assert response.status_code == 404
    assert "location" not in {k.lower() for k in response.headers}


def test_home_trailing_slash_is_404_not_307() -> None:
    with _client() as (_use_case, client):
        response = client.get("/api/agent/featured-conversations/home/")

    assert response.status_code == 404


def test_detail_multi_segment_path_is_404() -> None:
    with _client() as (_use_case, client):
        response = client.get("/api/agent/featured-conversations/a/b")

    assert response.status_code == 404


def test_non_ascii_body_is_not_escaped() -> None:
    use_case = FakeFeaturedUseCase()

    async def _detail(_featured_id: str | None) -> dict[str, Any] | None:
        return {"title": "精选对话", "summary": None}

    use_case.query_detail = _detail  # type: ignore[method-assign]
    with _client(use_case) as (_resolved, client):
        response = client.get("/api/agent/featured-conversations/any")

    assert "精选对话" in response.text
    assert "\\u" not in response.text


def test_coerce_int_matches_spring_string_to_number() -> None:
    assert coerce_int(None, 6) == 6
    assert coerce_int("", 6) == 6
    assert coerce_int("  ", 6) == 6
    assert coerce_int(" 12 ", 6) == 12
    assert coerce_int("-3", 6) == -3
    assert coerce_int("+4", 6) == 4
    try:
        coerce_int("1.5", 6)
    except CoercionError:
        pass
    else:  # pragma: no cover - regression guard
        raise AssertionError("expected CoercionError for '1.5'")
