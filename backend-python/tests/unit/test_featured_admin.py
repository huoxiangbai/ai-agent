"""Domain rules + use-case behaviour for the featured-admin write slice.

Pins the Java quirks that a "clean" rewrite would silently lose: the generated
``featuredId``, the untrimmed ``update`` passthrough, the absent-vs-JSON-null split
in Lombok's ``@Builder.Default`` pagination, fastjson tag serialization, and the
fact that ``ON DUPLICATE KEY UPDATE`` never touches ``status``/``published_*``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from reactor_backend.application.featured_conversation_admin import (
    FeaturedConversationAdminUseCase,
    SettingsWriteOwnerFence,
)
from reactor_backend.domain.featured_admin import (
    OFFLINE_STATUS,
    ONLINE_STATUS,
    AdminQueryCondition,
    FeaturedAdminRuleError,
    StatusUpdate,
    UpsertCommand,
    UpsertPo,
    build_status_update,
    build_upsert_po,
    generate_featured_id,
    to_admin_payload,
    to_tags_json,
    validate_create_command,
    validate_update_command,
)
from reactor_backend.domain.featured_conversation import FeaturedConversationRow
from reactor_backend.shared.errors import ApiError

NOW = datetime(2026, 9, 23, 12, 0, 0, 123000)
EARLIER = datetime(2026, 9, 1, 8, 30, 0)


def _row(**overrides: Any) -> FeaturedConversationRow:
    base: dict[str, Any] = {
        "id": 7,
        "featured_id": "featured_s1",
        "session_id": "s1",
        "title": "标题",
        "summary": "摘要",
        "cover_resource_key": "key-1",
        "cover_url": "https://example.invalid/cover.png",
        "tags_json": '["a","b"]',
        "sort_order": 3,
        "status": ONLINE_STATUS,
        "published_by": "alice",
        "published_at": EARLIER,
        "updated_by": "alice",
        "updated_at": EARLIER,
    }
    base.update(overrides)
    return FeaturedConversationRow(**base)


# --- featuredId generation / command validation ---------------------------------


def test_generate_featured_id_prefixes_and_trims() -> None:
    assert generate_featured_id("s1") == "featured_s1"
    assert generate_featured_id("  s1  ") == "featured_s1"


def test_validate_create_trims_session_id_and_rejects_blank() -> None:
    assert validate_create_command(UpsertCommand(session_id="  s1  ")) == "s1"
    for blank in (None, "", "   "):
        with pytest.raises(FeaturedAdminRuleError):
            validate_create_command(UpsertCommand(session_id=blank))
    with pytest.raises(FeaturedAdminRuleError):
        validate_create_command(None)


def test_validate_update_rejects_blank_featured_id() -> None:
    for blank in (None, "", "\t"):
        with pytest.raises(FeaturedAdminRuleError):
            validate_update_command(UpsertCommand(featured_id=blank))


def test_validate_update_passes_featured_id_untrimmed() -> None:
    # create trims; update deliberately does not.
    assert validate_update_command(UpsertCommand(featured_id="  f-1  ")) == "  f-1  "


# --- Lombok @Builder.Default pagination -----------------------------------------
# Two cases a "clean" rewrite collapses into one, and the wire shows they differ:
#   {}                    -> absent keys, constructor installs 1/10 -> offset 0, limit 10
#   {"pageNo":null,...}   -> setter overwrites with 0             -> offset 0, limit 1
# Ground truth (live Java, total=4): {} len=4; {"pageSize":null} len=1;
# {"pageNo":2} alone len=0 because offset=(2-1)*10=10.


def test_absent_page_fields_keep_the_lombok_defaults() -> None:
    # Jackson binds through the no-arg constructor, whose <init> runs
    # $default$pageNo()=1 / $default$pageSize()=10 (javap-verified). Keys that are
    # never present never reach a setter, so the initializers stand.
    condition = AdminQueryCondition()
    assert condition.page_no == 1
    assert condition.page_size == 10
    assert condition.offset == 0
    assert condition.limit == 10


def test_json_null_page_fields_become_zero_not_the_defaults() -> None:
    # A present null is written by the setter (FAIL_ON_NULL_FOR_PRIMITIVES off),
    # so it overwrites the Lombok default with 0 — and Math.max(1, x) then makes
    # the page width 1.
    condition = AdminQueryCondition(page_no=0, page_size=0)
    assert condition.offset == 0
    assert condition.limit == 1


def test_explicit_page_fields_use_max_1_clamping() -> None:
    condition = AdminQueryCondition(page_no=3, page_size=20)
    assert (condition.offset, condition.limit) == (40, 20)
    zeroed = AdminQueryCondition(page_no=0, page_size=0)
    assert (zeroed.offset, zeroed.limit) == (0, 1)
    negative = AdminQueryCondition(page_no=-5, page_size=-2)
    assert (negative.offset, negative.limit) == (0, 1)


# --- fastjson tag serialization -------------------------------------------------


def test_to_tags_json_matches_fastjson_compact_writer() -> None:
    assert to_tags_json(None) == "[]"
    assert to_tags_json([]) == "[]"
    assert to_tags_json(["a", "b"]) == '["a","b"]'
    # Non-ASCII stays raw (fastjson's default), never \\u-escaped.
    assert to_tags_json(["精选"]) == '["精选"]'
    # fastjson keeps nulls inside arrays.
    assert to_tags_json(["a", None]) == '["a",null]'
    # Compact separators only — no spaces after ':' or ','.
    assert " " not in to_tags_json(["x", "y"])


# --- upsert PO assembly ---------------------------------------------------------


def test_upsert_insert_branch_defaults_status_and_publish_fields() -> None:
    command = UpsertCommand(
        featured_id="featured_s1",
        session_id="s1",
        title="t",
        summary=None,
        cover_resource_key=None,
        cover_url=None,
        tags=None,
        sort_order=None,
        operator="bob",
    )
    po = build_upsert_po(command, None, now=NOW)
    assert po.status == OFFLINE_STATUS
    assert po.published_by == "bob"
    assert po.published_at is None
    assert po.sort_order == 0  # null sortOrder -> 0
    assert po.tags_json == "[]"
    assert po.updated_by == "bob"
    assert po.updated_at is NOW


def test_upsert_existing_branch_preserves_status_and_publish_fields() -> None:
    existing = _row(status=ONLINE_STATUS, published_by="alice", published_at=EARLIER)
    po = build_upsert_po(
        UpsertCommand(featured_id="featured_s1", session_id="s1", operator="bob"),
        existing,
        now=NOW,
    )
    assert po.status == ONLINE_STATUS
    assert po.published_by == "alice"
    assert po.published_at is EARLIER
    assert po.updated_by == "bob"


def test_upsert_blank_existing_status_falls_back_to_offline() -> None:
    # StringUtils.defaultIfBlank(existing.getStatus(), OFFLINE_STATUS)
    for blank in (None, "", "   "):
        po = build_upsert_po(
            UpsertCommand(featured_id="f", session_id="s", operator="bob"),
            _row(status=blank),
            now=NOW,
        )
        assert po.status == OFFLINE_STATUS


# --- status transitions ---------------------------------------------------------


def test_online_stamps_published_at_now() -> None:
    update = build_status_update(
        "featured_s1", ONLINE_STATUS, "bob", _row(published_at=EARLIER), now=NOW
    )
    assert update.status == ONLINE_STATUS
    assert update.published_at is NOW
    assert update.updated_by == "bob"
    assert update.updated_at is NOW


def test_offline_keeps_existing_published_at() -> None:
    update = build_status_update(
        "featured_s1", OFFLINE_STATUS, "bob", _row(published_at=EARLIER), now=NOW
    )
    assert update.status == OFFLINE_STATUS
    assert update.published_at is EARLIER


def test_status_update_uppercases_status() -> None:
    update = build_status_update("f", "online", None, _row(), now=NOW)
    assert update.status == "ONLINE"


# --- admin response shape -------------------------------------------------------


def test_admin_payload_field_order_is_contract() -> None:
    payload = to_admin_payload(_row())
    assert list(payload) == [
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
    # coverResourceKey must NOT leak into the admin response.
    assert "coverResourceKey" not in payload
    assert payload["tags"] == ["a", "b"]
    # Millisecond precision, three digits — never isoformat()'s six.
    assert payload["publishedAt"] == "2026-09-01T08:30:00"
    assert payload["updatedAt"] == "2026-09-01T08:30:00"


def test_admin_payload_timestamps_keep_three_millis() -> None:
    payload = to_admin_payload(_row(published_at=NOW, updated_at=NOW))
    assert payload["publishedAt"] == "2026-09-23T12:00:00.123"
    assert payload["updatedAt"] == "2026-09-23T12:00:00.123"


# --- use case + writer fence ----------------------------------------------------


class FakeStore:
    def __init__(self, rows: list[FeaturedConversationRow] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, Any]] = []
        self.upsert_result = True
        self.update_status_result = True

    async def query_by_featured_id(self, featured_id: str) -> FeaturedConversationRow | None:
        self.calls.append(("query_by_featured_id", featured_id))
        for row in self.rows:
            if row.featured_id == featured_id and row.featured_id is not None:
                return row
        return None

    async def query_by_session_id(self, session_id: str) -> FeaturedConversationRow | None:
        self.calls.append(("query_by_session_id", session_id))
        for row in self.rows:
            if row.session_id == session_id:
                return row
        return None

    async def upsert(self, po: UpsertPo) -> bool:
        self.calls.append(("upsert", po))
        return self.upsert_result

    async def update_status(self, update: StatusUpdate) -> bool:
        self.calls.append(("update_status", update))
        return self.update_status_result

    async def query_admin_list(
        self, condition: AdminQueryCondition
    ) -> list[FeaturedConversationRow]:
        self.calls.append(("query_admin_list", condition))
        return list(self.rows)

    async def count_admin_list(self, condition: AdminQueryCondition) -> int:
        self.calls.append(("count_admin_list", condition))
        return len(self.rows)


class FakeSessionChecker:
    def __init__(self, known: set[str] | None = None) -> None:
        self.known = known if known is not None else set()
        self.calls: list[str] = []

    async def query_session(self, session_id: str) -> object | None:
        self.calls.append(session_id)
        return {"sessionId": session_id} if session_id in self.known else None


class OpenFence:
    def assert_python_owns_writes(self) -> None:
        return None


def _use_case(
    store: FakeStore | None = None,
    checker: FakeSessionChecker | None = None,
    fence: Any = None,
) -> tuple[FeaturedConversationAdminUseCase, FakeStore, FakeSessionChecker]:
    resolved_store = store or FakeStore()
    resolved_checker = checker or FakeSessionChecker({"s1"})
    case = FeaturedConversationAdminUseCase(
        store=resolved_store,
        session_checker=resolved_checker,
        fence=fence or OpenFence(),
        clock=lambda: NOW,
    )
    return case, resolved_store, resolved_checker


async def test_create_generates_featured_id_and_trims_session() -> None:
    case, store, checker = _use_case()
    assert await case.create(
        UpsertCommand(featured_id="ignored", session_id="  s1  ", title="t", operator="bob")
    )
    assert checker.calls == ["s1"]
    kind, po = store.calls[-1]
    assert kind == "upsert"
    assert po.featured_id == "featured_s1"
    assert po.session_id == "s1"
    assert po.updated_at is NOW


async def test_create_rejects_blank_session_id_before_any_sql() -> None:
    case, store, checker = _use_case()
    with pytest.raises(FeaturedAdminRuleError):
        await case.create(UpsertCommand(session_id="   "))
    assert store.calls == []
    assert checker.calls == []


async def test_create_rejects_unknown_session() -> None:
    case, store, _checker = _use_case(checker=FakeSessionChecker(set()))
    with pytest.raises(FeaturedAdminRuleError):
        await case.create(UpsertCommand(session_id="nope"))
    assert store.calls == []


async def test_update_rejects_missing_row_and_blank_id() -> None:
    case, store, _checker = _use_case()
    with pytest.raises(FeaturedAdminRuleError):
        await case.update(UpsertCommand(featured_id="   "))
    with pytest.raises(FeaturedAdminRuleError):
        await case.update(UpsertCommand(featured_id="ghost"))
    assert store.calls == [("query_by_featured_id", "ghost")]


async def test_update_requeries_existing_like_java_upsert() -> None:
    row = _row()
    case, store, _checker = _use_case(store=FakeStore([row]))
    assert await case.update(
        UpsertCommand(
            featured_id="featured_s1", session_id="s1", title="t2", operator="bob"
        )
    )
    kinds = [kind for kind, _payload in store.calls]
    assert kinds == ["query_by_featured_id", "query_by_featured_id", "upsert"]


async def test_update_without_session_id_is_false_and_writes_nothing() -> None:
    # Java's FeaturedConversationRepository.upsert refuses a blank sessionId
    # *before any SQL*. The existence pre-check above has already passed by then,
    # so the request answers 200 + data:false and looks like it succeeded while
    # the row is untouched. Parity run caught this: Python used to write.
    row = _row(title="原标题")
    store = FakeStore([row])
    case, _store, _checker = _use_case(store=store)
    assert (
        await case.update(UpsertCommand(featured_id="featured_s1", title="t2")) is False
    )
    # Existence SELECT only — the guard fires before the resolve SELECTs.
    assert [kind for kind, _payload in store.calls] == ["query_by_featured_id"]
    assert row.title == "原标题"


async def test_online_and_offline_return_false_without_throwing() -> None:
    case, store, _checker = _use_case()
    assert await case.online("", "bob") is False
    assert await case.online("ghost", "bob") is False
    assert await case.offline("ghost", "bob") is False
    assert [kind for kind, _p in store.calls] == ["query_by_featured_id", "query_by_featured_id"]


async def test_online_marks_true_through_rowcount() -> None:
    row = _row(status=OFFLINE_STATUS, published_at=EARLIER)
    case, store, _checker = _use_case(store=FakeStore([row]))
    assert await case.online("featured_s1", "bob") is True
    _kind, update = store.calls[-1]
    assert update.status == ONLINE_STATUS
    assert update.published_at is NOW
    store.calls.clear()
    assert await case.offline("featured_s1", "bob") is True
    _kind, update = store.calls[-1]
    assert update.status == OFFLINE_STATUS
    assert update.published_at is EARLIER


async def test_query_list_shape_and_order() -> None:
    case, store, _checker = _use_case(store=FakeStore([_row()]))
    page = await case.query_list(AdminQueryCondition(page_no=1, page_size=10))
    assert list(page) == ["total", "list"]
    assert page["total"] == 1
    assert list(page["list"][0]) == [  # type: ignore[index]
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


# --- writer fence is fail-closed ------------------------------------------------


@pytest.mark.parametrize("owner", ["java", "", "JAVA", "none", "python-please-no"])
async def test_fence_refuses_every_owner_but_python(owner: str) -> None:
    fence = SettingsWriteOwnerFence(owner)
    with pytest.raises(ApiError) as raised:
        fence.assert_python_owns_writes()
    assert raised.value.code == "0001"
    assert raised.value.status_code == 200


def test_fence_allows_python() -> None:
    SettingsWriteOwnerFence("python").assert_python_owns_writes()


@pytest.mark.parametrize(
    "invoke",
    [
        lambda case: case.create(UpsertCommand(session_id="s1", title="t")),
        lambda case: case.update(UpsertCommand(featured_id="featured_s1", title="t")),
        lambda case: case.online("featured_s1", "bob"),
        lambda case: case.offline("featured_s1", "bob"),
    ],
)
async def test_closed_fence_blocks_all_four_writes_before_any_sql(
    invoke: Any,
) -> None:
    store = FakeStore([_row()])
    checker = FakeSessionChecker({"s1"})
    case, _store, _checker = _use_case(
        store=store, checker=checker, fence=SettingsWriteOwnerFence("java")
    )
    with pytest.raises(ApiError):
        await invoke(case)
    # Fail closed: not a single SQL round-trip, not even a read.
    assert store.calls == []
    assert checker.calls == []
