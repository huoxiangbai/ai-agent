"""HTTP-surface pins for the five featured-admin routes.

The subject is the response *shape*: ``{code, info, data}`` for business results,
Spring's four-key ``BasicErrorController`` body for everything the un-caught
``IllegalArgumentException`` and the transport failures produce. Mixing the two (or
inventing FastAPI's ``{"detail": ...}``) is the drift these pins prevent.

``FeaturedConversationAdminController`` has no try/catch and Java has no
``@ControllerAdvice``, so business-rule failures are HTTP **500**, not a 0002
envelope — unlike ``SubAgentDefinitionAdminController``, which does catch.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from test_featured_routes import (  # type: ignore[import-not-found]
    FakeDatabase,
    assert_spring_error_body,
)

from reactor_backend.config import Settings
from reactor_backend.domain.featured_admin import (
    ONLINE_STATUS,
    AdminQueryCondition,
    FeaturedAdminRuleError,
    UpsertCommand,
)
from reactor_backend.domain.featured_conversation import FeaturedConversationRow
from reactor_backend.main import create_app

_ROW = FeaturedConversationRow(
    id=1,
    featured_id="featured_s1",
    session_id="s1",
    title="标题",
    summary=None,
    cover_resource_key="internal-key",
    cover_url="https://example.invalid/c.png",
    tags_json='["精选"]',
    sort_order=2,
    status=ONLINE_STATUS,
    published_by="alice",
    published_at=None,
    updated_by="alice",
    updated_at=None,
)


class FakeAdminUseCase:
    """Records calls; canned booleans so the envelope is the subject."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.create_result: bool | FeaturedAdminRuleError = True
        self.update_result: bool | FeaturedAdminRuleError = True
        self.online_result = True
        self.offline_result = False

    async def create(self, command: UpsertCommand) -> bool:
        self.calls.append(("create", command))
        if isinstance(self.create_result, Exception):
            raise self.create_result
        return self.create_result

    async def update(self, command: UpsertCommand) -> bool:
        self.calls.append(("update", command))
        if isinstance(self.update_result, Exception):
            raise self.update_result
        return self.update_result

    async def online(self, featured_id: str, operator: str | None) -> bool:
        self.calls.append(("online", (featured_id, operator)))
        return self.online_result

    async def offline(self, featured_id: str, operator: str | None) -> bool:
        self.calls.append(("offline", (featured_id, operator)))
        return self.offline_result

    async def query_list(self, condition: AdminQueryCondition) -> dict[str, Any]:
        self.calls.append(("query_list", condition))
        return {"total": 1, "list": [_admin_payload_stub()]}


def _admin_payload_stub() -> dict[str, Any]:
    from reactor_backend.domain.featured_admin import to_admin_payload

    return to_admin_payload(_ROW)


@contextmanager
def _client(
    use_case: FakeAdminUseCase | None = None,
    owner: str = "python",
) -> Iterator[tuple[FakeAdminUseCase, TestClient]]:
    app = create_app(Settings(featured_admin_write_owner=owner), FakeDatabase)
    resolved = use_case or FakeAdminUseCase()
    with TestClient(app) as client:
        app.state.featured_admin_use_case = resolved
        yield resolved, client


def test_create_success_is_envelope_with_boolean() -> None:
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create",
            json={"sessionId": "s1", "title": "t", "operator": "bob"},
        )

    assert response.status_code == 200
    assert response.json() == {"code": "0000", "info": "成功", "data": True}
    _kind, command = use_case.calls[0]
    assert command.session_id == "s1"
    assert command.operator == "bob"


def test_create_false_is_still_http_200() -> None:
    use_case = FakeAdminUseCase()
    use_case.create_result = False
    with _client(use_case) as (_resolved, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create", json={"sessionId": "s1"}
        )
    assert response.status_code == 200
    assert response.json() == {"code": "0000", "info": "成功", "data": False}


def test_create_business_rule_failure_is_500_four_key_not_0002() -> None:
    use_case = FakeAdminUseCase()
    use_case.create_result = FeaturedAdminRuleError("sessionId 不能为空")
    with _client(use_case) as (_resolved, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create", json={"sessionId": "  "}
        )

    assert response.status_code == 500
    assert_spring_error_body(response, 500, "/api/v1/admin/featured-conversations/create")
    assert response.json()["error"] == "Internal Server Error"


def test_create_missing_body_is_400() -> None:
    with _client() as (use_case, client):
        response = client.post("/api/v1/admin/featured-conversations/create")

    assert response.status_code == 400
    assert use_case.calls == []
    assert_spring_error_body(response, 400, "/api/v1/admin/featured-conversations/create")


def test_create_malformed_json_is_400() -> None:
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create",
            content=b"{not json",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert use_case.calls == []


def test_create_json_null_body_is_500() -> None:
    # Jackson returns Java null for a ``null`` body; ``toCommand(null)`` NPEs.
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create",
            content=b"null",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 500
    assert use_case.calls == []
    assert_spring_error_body(response, 500, "/api/v1/admin/featured-conversations/create")


def test_create_field_type_mismatch_is_400() -> None:
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create",
            json={"sessionId": "s1", "sortOrder": "not-a-number"},
        )

    assert response.status_code == 400
    assert use_case.calls == []


def test_update_missing_featured_id_is_500_four_key() -> None:
    use_case = FakeAdminUseCase()
    use_case.update_result = FeaturedAdminRuleError("featuredId 不能为空")
    with _client(use_case) as (_resolved, client):
        response = client.put(
            "/api/v1/admin/featured-conversations/update",
            json={"title": "t"},
        )

    assert response.status_code == 500
    assert_spring_error_body(response, 500, "/api/v1/admin/featured-conversations/update")


def test_update_success_is_envelope() -> None:
    with _client() as (use_case, client):
        response = client.put(
            "/api/v1/admin/featured-conversations/update",
            json={"featuredId": "featured_s1", "title": "t2"},
        )

    assert response.status_code == 200
    assert response.json() == {"code": "0000", "info": "成功", "data": True}
    _kind, command = use_case.calls[0]
    assert command.featured_id == "featured_s1"


def test_online_missing_operator_is_400_four_key() -> None:
    with _client() as (use_case, client):
        response = client.post("/api/v1/admin/featured-conversations/online/featured_s1")

    assert response.status_code == 400
    assert use_case.calls == []
    assert_spring_error_body(
        response, 400, "/api/v1/admin/featured-conversations/online/featured_s1"
    )


def test_offline_missing_operator_is_400_four_key() -> None:
    with _client() as (use_case, client):
        response = client.post("/api/v1/admin/featured-conversations/offline/featured_s1")

    assert response.status_code == 400
    assert use_case.calls == []


def test_online_empty_operator_is_present_and_accepted() -> None:
    # @RequestParam only requires the parameter to be present; ?operator= is "".
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/online/featured_s1?operator="
        )

    assert response.status_code == 200
    assert response.json() == {"code": "0000", "info": "成功", "data": True}
    assert use_case.calls == [("online", ("featured_s1", ""))]


def test_online_false_is_http_200_data_false_not_500() -> None:
    # Blank id / missing row -> repository returns false; never an exception.
    use_case = FakeAdminUseCase()
    use_case.online_result = False
    with _client(use_case) as (_resolved, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/online/ghost?operator=bob"
        )

    assert response.status_code == 200
    assert response.json() == {"code": "0000", "info": "成功", "data": False}


def test_offline_carries_operator_through() -> None:
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/offline/featured_s1?operator=%E5%BC%A0%E4%B8%89"
        )

    assert response.status_code == 200
    assert response.json()["data"] is False  # FakeAdminUseCase.offline_result
    assert use_case.calls == [("offline", ("featured_s1", "张三"))]


def test_query_list_absent_page_fields_keep_lombok_defaults() -> None:
    # Absent keys never reach a setter, so the no-arg constructor's Lombok
    # defaults stand: pageNo=1, pageSize=10 -> offset 0, limit 10.
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/query-list", json={}
        )

    assert response.status_code == 200
    _kind, condition = use_case.calls[0]
    assert (condition.page_no, condition.page_size) == (1, 10)
    assert (condition.offset, condition.limit) == (0, 10)


def test_query_list_json_null_page_fields_are_zero() -> None:
    # A present null reaches the setter and lands on 0, which is *not* the same
    # wire behaviour as an absent key: limit collapses to 1.
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/query-list",
            json={"pageNo": None, "pageSize": None},
        )

    assert response.status_code == 200
    _kind, condition = use_case.calls[0]
    assert (condition.page_no, condition.page_size) == (0, 0)
    assert (condition.offset, condition.limit) == (0, 1)


def test_query_list_explicit_pagination_and_filters_pass_through() -> None:
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/query-list",
            json={
                "status": "ONLINE",
                "sessionId": "s1",
                "title": "  ",
                "pageNo": 3,
                "pageSize": 20,
            },
        )

    assert response.status_code == 200
    _kind, condition = use_case.calls[0]
    assert condition.status == "ONLINE"
    assert condition.session_id == "s1"
    assert condition.title == "  "  # whitespace filters are applied, not skipped
    assert (condition.offset, condition.limit) == (40, 20)


def test_query_list_payload_shape_and_field_order() -> None:
    with _client() as (_use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/query-list", json={"pageNo": 1, "pageSize": 10}
        )

    body = response.json()
    assert body["code"] == "0000"
    assert list(body["data"]) == ["total", "list"]
    item = body["data"]["list"][0]
    assert list(item) == [
        "featuredId",
        "sessionId",
        "title",
        "summary",
        "tags",
        "coverUrl",
        "sortOrder",
        "status",
        "publishedAt",
        "updatedAt",
    ]
    assert "coverResourceKey" not in item
    assert item["tags"] == ["精选"]


def test_query_list_missing_body_is_400() -> None:
    with _client() as (use_case, client):
        response = client.post("/api/v1/admin/featured-conversations/query-list")

    assert response.status_code == 400
    assert use_case.calls == []
    assert_spring_error_body(
        response, 400, "/api/v1/admin/featured-conversations/query-list"
    )


def test_query_list_field_type_mismatch_is_400() -> None:
    with _client() as (use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/query-list",
            json={"pageNo": {"nested": 1}},
        )

    assert response.status_code == 400
    assert use_case.calls == []


def test_non_ascii_body_is_not_escaped() -> None:
    with _client() as (_use_case, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/query-list", json={"pageNo": 1, "pageSize": 1}
        )

    assert "精选" in response.text
    assert "\\u" not in response.text


def test_trailing_slash_is_404_not_307() -> None:
    with _client() as (_use_case, client):
        response = client.post("/api/v1/admin/featured-conversations/query-list/")

    assert response.status_code == 404
    assert "location" not in {k.lower() for k in response.headers}


def test_unknown_method_is_405_with_allow() -> None:
    with _client() as (_use_case, client):
        response = client.get("/api/v1/admin/featured-conversations/create")

    assert response.status_code == 405
    assert_spring_error_body(response, 405, "/api/v1/admin/featured-conversations/create")


# --- writer fence surfaces through the HTTP layer -------------------------------


def test_fence_closed_answers_0001_envelope_without_touching_sql() -> None:
    use_case = _RecordingClosedFenceUseCase()
    with _client(use_case, owner="java") as (_resolved, client):
        response = client.post(
            "/api/v1/admin/featured-conversations/create", json={"sessionId": "s1"}
        )

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["code", "info", "data"]
    assert body["code"] == "0001"
    assert body["data"] is None
    assert "owner=java" in body["info"]


class _RecordingClosedFenceUseCase(FakeAdminUseCase):
    """Raises the real fence error so the ApiError handler is what we observe."""

    async def create(self, command: UpsertCommand) -> bool:
        self.calls.append(("create", command))
        from reactor_backend.application.featured_conversation_admin import (
            SettingsWriteOwnerFence,
        )

        SettingsWriteOwnerFence("java").assert_python_owns_writes()
        raise AssertionError("unreachable")
