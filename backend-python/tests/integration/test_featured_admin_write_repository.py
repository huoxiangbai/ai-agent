"""Write-side integration for the featured-admin slice.

Requires ``TEST_MYSQL_ADMIN_URL`` pointing at a **throwaway** database loaded with
``db/schema.sql`` and a throwaway account that may INSERT/UPDATE (it seeds
``ai_agent_dialogue_session`` and soft-deletes rows to set up races). Never point
it at a live database: these tests write, and every row name is prefixed with a
per-test uuid so a shared throwaway database cannot cross-contaminate (R-33).

Account *scope* is proven separately by
``test_featured_writer_account_scope.py`` under
``TEST_MYSQL_FEATURED_WRITER_URL``.

What is pinned here and why:

* ``ON DUPLICATE KEY UPDATE`` never touches ``session_id`` / ``featured_id`` /
  ``status`` / ``published_by`` / ``published_at`` — so ``update`` cannot retarget
  a row to a new session, and a soft-deleted row is revived with its old status.
* rowcount means **found** rows (``CLIENT_FOUND_ROWS``, which MySQL Connector/J
  sets for Java and which the engine now sets for Python). Without it an idempotent
  repeat upsert or a matched-but-unchanged ``updateStatus`` reports 0 and the
  boolean Java returns as ``true`` becomes ``false``.
* both UNIQUE keys (``featured_id``, ``session_id``) are separate conflict faces.
* a single statement is atomic: a NOT NULL violation leaves no row behind.
* ``create`` is **not** a transaction (Java has no ``@Transactional``).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from reactor_backend.application.featured_conversation_admin import (
    FeaturedConversationAdminUseCase,
    SettingsWriteOwnerFence,
)
from reactor_backend.config import Settings
from reactor_backend.domain.featured_admin import (
    OFFLINE_STATUS,
    ONLINE_STATUS,
    AdminQueryCondition,
    UpsertCommand,
)
from reactor_backend.infrastructure.database import Database
from reactor_backend.infrastructure.repositories import (
    ExecutionLedgerRepository,
    FeaturedConversationRepository,
)

_BASE = datetime(2026, 9, 23, 10, 0, 0, 250000)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _url() -> str | None:
    return os.getenv("TEST_MYSQL_ADMIN_URL")


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    url = _url()
    if not url:
        pytest.skip("TEST_MYSQL_ADMIN_URL is required for featured-admin write tests")
    database = Database(Settings(database_url=SecretStr(url)))
    await database.start()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def store(db: Database) -> FeaturedConversationRepository:
    return FeaturedConversationRepository(db)


@pytest.fixture
async def seed_session(db: Database) -> Any:
    """Insert a row into ``ai_agent_dialogue_session`` and return its session id."""

    async def _seed(session_id: str) -> str:
        async with db.connect() as connection:
            await connection.execute(
                text(
                    "INSERT INTO ai_agent_dialogue_session "
                    "(session_id, title, status, run_count, finished_run_count, "
                    " failed_run_count, deleted) "
                    "VALUES (:sid, 'seed', 0, 0, 0, 0, 0)"
                ),
                {"sid": session_id},
            )
        return session_id

    return _seed


def _use_case(
    store: FeaturedConversationRepository, db: Database, clock: Any = None
) -> FeaturedConversationAdminUseCase:
    return FeaturedConversationAdminUseCase(
        store=store,
        session_checker=ExecutionLedgerRepository(db),
        fence=SettingsWriteOwnerFence("python"),
        clock=clock or (lambda: _BASE),
    )


async def _raw_insert_session(db: Database, session_id: str) -> None:
    async with db.connect() as connection:
        await connection.execute(
            text(
                "INSERT INTO ai_agent_dialogue_session "
                "(session_id, title, status, run_count, finished_run_count, "
                " failed_run_count, deleted) "
                "VALUES (:sid, 'seed', 0, 0, 0, 0, 0)"
            ),
            {"sid": session_id},
        )


async def _raw_fetch(db: Database, featured_id: str) -> dict[str, Any] | None:
    async with db.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT featured_id, session_id, title, summary, cover_resource_key, "
                "       cover_url, tags_json, sort_order, status, published_by, "
                "       published_at, updated_by, updated_at, deleted "
                "FROM ai_agent_featured_conversation WHERE featured_id = :fid"
            ),
            {"fid": featured_id},
        )
        row = result.first()
        return None if row is None else dict(row._mapping)


async def _raw_exec(db: Database, sql: str, params: dict[str, Any] | None = None) -> int:
    async with db.connect() as connection:
        result = await connection.execute(text(sql), params or {})
        return int(result.rowcount or 0)


# --- insert branch defaults -----------------------------------------------------


@pytest.mark.integration
async def test_create_insert_branch_defaults(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-insert-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db)

    assert await case.create(
        UpsertCommand(
            session_id=session_id,
            title="标题",
            tags=None,
            sort_order=None,
            operator="bob",
        )
    )

    row = await _raw_fetch(db, f"featured_{session_id}")
    assert row is not None
    assert row["featured_id"] == f"featured_{session_id}"
    assert row["session_id"] == session_id
    assert row["status"] == OFFLINE_STATUS
    assert row["published_by"] == "bob"
    assert row["published_at"] is None
    assert row["sort_order"] == 0  # null sortOrder -> 0
    assert row["tags_json"] in ("[]", None) or str(row["tags_json"]).replace(" ", "") == "[]"
    assert row["updated_by"] == "bob"
    assert row["deleted"] == 0


@pytest.mark.integration
async def test_null_title_is_rejected_and_leaves_no_row(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    """Single-statement atomicity: a NOT NULL violation rolls the statement back."""
    session_id = f"s-null-title-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db)

    with pytest.raises(IntegrityError):
        await case.create(UpsertCommand(session_id=session_id, title=None, operator="bob"))

    assert await _raw_fetch(db, f"featured_{session_id}") is None
    # create is NOT one transaction (Java has no @Transactional): the session row
    # the existence check read is untouched and still visible.
    async with db.connect() as connection:
        result = await connection.execute(
            text("SELECT COUNT(1) FROM ai_agent_dialogue_session WHERE session_id = :sid"),
            {"sid": session_id},
        )
        assert int(result.scalar() or 0) == 1


# --- ON DUPLICATE KEY UPDATE column preservation --------------------------------


@pytest.mark.integration
async def test_duplicate_featured_id_updates_only_the_listed_columns(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-dup-fid-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: datetime(2026, 9, 23, 10, 0, 0))

    assert await case.create(
        UpsertCommand(session_id=session_id, title="一", sort_order=1, operator="bob")
    )
    assert await case.online(f"featured_{session_id}", "alice")
    before = await _raw_fetch(db, f"featured_{session_id}")
    assert before is not None
    assert before["status"] == ONLINE_STATUS
    assert before["published_at"] is not None

    # Second create for the same session: featuredId collides -> ON DUPLICATE.
    assert await case.create(
        UpsertCommand(session_id=session_id, title="二", sort_order=2, operator="carol")
    )
    after = await _raw_fetch(db, f"featured_{session_id}")

    assert after is not None
    assert after["title"] == "二"
    assert after["sort_order"] == 2
    assert after["updated_by"] == "carol"
    # NOT touched by the UPDATE clause:
    assert after["featured_id"] == before["featured_id"]
    assert after["session_id"] == before["session_id"]
    assert after["status"] == before["status"] == ONLINE_STATUS
    # published_by is insert-only: neither updateStatus nor the ON DUPLICATE
    # UPDATE clause writes it, so it still carries create's operator ("bob") even
    # though online ran with "alice". Java's mapper is the same (measured
    # 2026-09-24 against featured_conversation_mapper.xml) — do not "fix" this.
    assert before["published_by"] == after["published_by"] == "bob"
    assert after["published_at"] == before["published_at"]


@pytest.mark.integration
async def test_duplicate_session_id_does_not_retarget_featured_id(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-dup-sid-{_uid()}"
    await seed_session(session_id)
    # A pre-existing row already owns this session under a different featured_id.
    await _raw_exec(
        db,
        "INSERT INTO ai_agent_featured_conversation "
        "(featured_id, session_id, title, summary, tags_json, sort_order, status, "
        " published_by, published_at, updated_by, updated_at, deleted) "
        "VALUES (:fid, :sid, 'orig', NULL, '[]', 1, 'ONLINE', 'alice', :ts, "
        "        'alice', :ts, 0)",
        {"fid": f"featured_other-{_uid()}", "sid": session_id, "ts": _BASE},
    )
    existing = await store.query_by_session_id(session_id)
    assert existing is not None

    case = _use_case(store, db)
    assert await case.create(
        UpsertCommand(session_id=session_id, title="new", operator="bob")
    )

    row = await _raw_fetch(db, existing.featured_id or "")
    assert row is not None
    # The INSERT conflicted on session_id, so featured_id keeps its old value and
    # the freshly generated "featured_<session>" never lands.
    assert row["featured_id"] == existing.featured_id
    assert row["title"] == "new"
    assert row["status"] == ONLINE_STATUS
    assert await _raw_fetch(db, f"featured_{session_id}") is None


@pytest.mark.integration
async def test_soft_deleted_row_is_revived_and_keeps_its_status(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-revive-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: datetime(2026, 9, 23, 11, 0, 0))

    assert await case.create(
        UpsertCommand(session_id=session_id, title="一", operator="bob")
    )
    assert await case.online(f"featured_{session_id}", "alice")
    # Soft delete (what the domain calls a delete): only a flag flip, row stays.
    await _raw_exec(
        db,
        "UPDATE ai_agent_featured_conversation SET deleted = 1 WHERE session_id = :sid",
        {"sid": session_id},
    )
    assert await store.query_by_featured_id(f"featured_{session_id}") is None

    assert await case.create(
        UpsertCommand(session_id=session_id, title="二", operator="carol")
    )
    row = await _raw_fetch(db, f"featured_{session_id}")
    assert row is not None
    assert row["deleted"] == 0
    # ON DUPLICATE revived the row without touching status/published_*. The
    # re-create assembled an INSERT-branch PO with published_by="carol", but the
    # duplicate branch never writes that column — so it still holds create's
    # "bob", not online's "alice" and not this call's "carol".
    assert row["status"] == ONLINE_STATUS
    assert row["published_by"] == "bob"
    assert row["published_at"] is not None
    assert row["title"] == "二"


# --- rowcount semantics (CLIENT_FOUND_ROWS) -------------------------------------


@pytest.mark.integration
async def test_idempotent_repeat_upsert_reports_true(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    """The FOUND_ROWS pin.

    Without ``CLIENT_FOUND_ROWS`` the second, byte-identical upsert affects 0 rows
    and would report ``false``. Java's Connector/J sets the flag (its default is
    ``useAffectedRows=false``) and reports ``true``, so Python must too.
    """
    session_id = f"s-idem-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: _BASE)

    command = UpsertCommand(session_id=session_id, title="same", sort_order=4, operator="bob")
    assert await case.create(command) is True
    assert await case.create(command) is True
    assert await case.create(command) is True


@pytest.mark.integration
async def test_matched_but_unchanged_status_update_reports_true(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-unchanged-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: _BASE)

    assert await case.create(UpsertCommand(session_id=session_id, title="t", operator="bob"))
    assert await case.online(f"featured_{session_id}", "bob") is True
    # Second online with the same clock: every column in the UPDATE lands on the
    # value it already has. Affected rows = 0, found rows = 1 -> Java says true.
    assert await case.online(f"featured_{session_id}", "bob") is True


@pytest.mark.integration
async def test_status_update_reports_false_when_row_disappears_first(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    """The CAS race: a concurrent soft-delete makes the WHERE miss -> 0 rows."""
    session_id = f"s-race-del-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: _BASE)

    assert await case.create(UpsertCommand(session_id=session_id, title="t", operator="bob"))
    await _raw_exec(
        db,
        "UPDATE ai_agent_featured_conversation SET deleted = 1 WHERE session_id = :sid",
        {"sid": session_id},
    )
    # Repository-level guard short-circuits before the UPDATE and returns False.
    assert await case.online(f"featured_{session_id}", "bob") is False


# --- status transitions ---------------------------------------------------------


@pytest.mark.integration
async def test_online_stamps_published_at_and_offline_preserves_it(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-status-{_uid()}"
    await seed_session(session_id)
    stamps = iter(
        [
            datetime(2026, 9, 23, 9, 0, 0),
            datetime(2026, 9, 23, 9, 5, 0),
            datetime(2026, 9, 23, 9, 10, 0),
        ]
    )
    case = _use_case(store, db, clock=lambda: next(stamps))

    assert await case.create(UpsertCommand(session_id=session_id, title="t", operator="bob"))
    assert await case.online(f"featured_{session_id}", "alice") is True
    row = await _raw_fetch(db, f"featured_{session_id}")
    assert row is not None
    assert row["status"] == ONLINE_STATUS
    assert row["published_at"] == datetime(2026, 9, 23, 9, 5, 0)
    assert row["updated_by"] == "alice"

    assert await case.offline(f"featured_{session_id}", "bob") is True
    row = await _raw_fetch(db, f"featured_{session_id}")
    assert row is not None
    assert row["status"] == OFFLINE_STATUS
    # offline keeps published_at.
    assert row["published_at"] == datetime(2026, 9, 23, 9, 5, 0)
    assert row["updated_by"] == "bob"


@pytest.mark.integration
async def test_online_on_missing_row_is_false_not_an_error(
    db: Database, store: FeaturedConversationRepository
) -> None:
    case = _use_case(store, db)
    assert await case.online(f"ghost-{_uid()}", "bob") is False
    assert await case.offline("", "bob") is False


# --- unique-key conflicts -------------------------------------------------------


@pytest.mark.integration
async def test_both_unique_keys_reject_conflicting_raw_inserts(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-uniq-{_uid()}"
    other_session = f"s-uniq-b-{_uid()}"
    await seed_session(session_id)
    await seed_session(other_session)
    fid = f"featured_{session_id}"

    insert = (
        "INSERT INTO ai_agent_featured_conversation "
        "(featured_id, session_id, title, tags_json, sort_order, status, "
        " updated_by, updated_at, deleted) "
        "VALUES (:fid, :sid, 'x', '[]', 0, 'OFFLINE', 'bob', :ts, 0)"
    )
    await _raw_exec(db, insert, {"fid": fid, "sid": session_id, "ts": _BASE})

    # Conflict face 1: uk_featured_conversation_featured_id
    with pytest.raises(IntegrityError):
        await _raw_exec(
            db,
            insert,
            {"fid": fid, "sid": other_session, "ts": _BASE},
        )

    # Conflict face 2: uk_featured_conversation_session_id
    with pytest.raises(IntegrityError):
        await _raw_exec(
            db,
            insert,
            {"fid": f"featured_other-{_uid()}", "sid": session_id, "ts": _BASE},
        )

    assert await _raw_fetch(db, fid) is not None


# --- admin list -----------------------------------------------------------------


@pytest.mark.integration
async def test_admin_list_filters_pagination_and_sort(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    tag = _uid()
    # The tag lives inside every title so ``title=tag`` isolates this test's rows
    # from every other test's (R-33), and so the LIKE-wildcard case below has
    # something real to match on.
    rows = [
        (f"a-{tag}", f"s1-{tag}", f"苹果标题{tag}", 30, OFFLINE_STATUS),
        (f"b-{tag}", f"s2-{tag}", f"香蕉标题{tag}", 20, ONLINE_STATUS),
        (f"c-{tag}", f"s3-{tag}", f"苹果摘要{tag}", 10, ONLINE_STATUS),
    ]
    for fid, sid, title, sort, status in rows:
        await _raw_exec(
            db,
            "INSERT INTO ai_agent_featured_conversation "
            "(featured_id, session_id, title, tags_json, sort_order, status, "
            " updated_by, updated_at, deleted) "
            "VALUES (:fid, :sid, :title, '[]', :sort, :status, 'bob', :ts, 0)",
            {"fid": fid, "sid": sid, "title": title, "sort": sort, "status": status, "ts": _BASE},
        )

    # Sort: sort_order DESC, id DESC. The three rows are 30/20/10. Calls that
    # match rows beyond this test's own tag pass an explicit page size so a bare
    # condition's default width cannot truncate them.
    page_all = {"page_no": 1, "page_size": 50}
    everything = await store.query_admin_list(AdminQueryCondition(title=tag, **page_all))
    assert [row.featured_id for row in everything] == [
        f"a-{tag}",
        f"b-{tag}",
        f"c-{tag}",
    ]
    assert await store.count_admin_list(AdminQueryCondition(title=tag)) == 3

    # status filter is exact; '' and None skip the clause entirely.
    online_only = await store.query_admin_list(
        AdminQueryCondition(title=tag, status="ONLINE", **page_all)
    )
    assert sorted(row.featured_id or "" for row in online_only) == [f"b-{tag}", f"c-{tag}"]
    assert await store.count_admin_list(AdminQueryCondition(title=tag, status="OFFLINE")) == 1

    # sessionId filter is exact and skips on ''.
    one = await store.query_admin_list(AdminQueryCondition(session_id=f"s2-{tag}"))
    assert [row.featured_id for row in one] == [f"b-{tag}"]

    # title filter is a LIKE '%x%' and treats % and _ as wildcards (Java parity).
    apple = await store.query_admin_list(AdminQueryCondition(title="苹果", **page_all))
    apple_ids = [row.featured_id for row in apple if (row.featured_id or "").endswith(tag)]
    assert sorted(apple_ids) == [f"a-{tag}", f"c-{tag}"]
    wildcard = await store.query_admin_list(AdminQueryCondition(title=f"%{tag}", **page_all))
    assert len([row for row in wildcard if (row.featured_id or "").endswith(tag)]) == 3

    # Pagination: offset = (max(1,pageNo)-1)*max(1,pageSize), limit = max(1,pageSize).
    page2 = await store.query_admin_list(
        AdminQueryCondition(title=tag, page_no=2, page_size=2)
    )
    assert [row.featured_id for row in page2] == [f"c-{tag}"]
    # Absent pageNo/pageSize keep the Lombok constructor defaults (1/10), so a bare
    # condition pages at width 10. A *present* JSON null is what the setter drives
    # to 0 — and Math.max(1, 0) then clamps the page to width 1. The two must not
    # collapse into one another; live Java measures (0,10) for {} and (0,1) for
    # {"pageNo":null,"pageSize":null}.
    bare = AdminQueryCondition(title=tag)
    assert (bare.offset, bare.limit) == (0, 10)
    assert len(await store.query_admin_list(bare)) == 3
    nulled = AdminQueryCondition(title=tag, page_no=0, page_size=0)
    assert (nulled.offset, nulled.limit) == (0, 1)
    assert len(await store.query_admin_list(nulled)) == 1

    # Soft-deleted rows are excluded everywhere.
    await _raw_exec(
        db,
        "UPDATE ai_agent_featured_conversation SET deleted = 1 WHERE featured_id = :fid",
        {"fid": f"a-{tag}"},
    )
    assert await store.count_admin_list(AdminQueryCondition(title=tag)) == 2


@pytest.mark.integration
async def test_admin_list_whitespace_filter_is_applied_not_skipped(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    """OGNL ``status != ''`` is a strict empty check — ``'   ''`` filters."""
    tag = _uid()
    await _raw_exec(
        db,
        "INSERT INTO ai_agent_featured_conversation "
        "(featured_id, session_id, title, tags_json, sort_order, status, "
        " updated_by, updated_at, deleted) "
        "VALUES (:fid, :sid, :title, '[]', 0, 'OFFLINE', 'bob', :ts, 0)",
        {"fid": f"ws-{tag}", "sid": f"ws-s-{tag}", "title": "t", "ts": _BASE},
    )
    assert await store.count_admin_list(AdminQueryCondition(status="   ")) == 0
    assert await store.count_admin_list(AdminQueryCondition(status="")) >= 1
    assert await store.count_admin_list(AdminQueryCondition(status=None)) >= 1


# --- idempotence / concurrency --------------------------------------------------


@pytest.mark.integration
async def test_concurrent_create_on_one_session_yields_one_row(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-conc-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: _BASE)
    command = UpsertCommand(session_id=session_id, title="t", operator="bob")

    results = await asyncio.gather(
        case.create(command),
        case.create(command),
        case.create(command),
    )
    assert all(results) is True

    async with db.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT COUNT(1) FROM ai_agent_featured_conversation "
                "WHERE session_id = :sid AND deleted = 0"
            ),
            {"sid": session_id},
        )
        assert int(result.scalar() or 0) == 1


@pytest.mark.integration
async def test_concurrent_online_offline_last_writer_wins(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    session_id = f"s-flip-{_uid()}"
    await seed_session(session_id)
    ticks = {"n": 0}

    def _clock() -> datetime:
        ticks["n"] += 1
        return datetime(2026, 9, 23, 12, 0, 0, ticks["n"] * 1000)

    case = _use_case(store, db, clock=_clock)
    assert await case.create(UpsertCommand(session_id=session_id, title="t", operator="bob"))

    await asyncio.gather(
        case.online(f"featured_{session_id}", "alice"),
        case.offline(f"featured_{session_id}", "bob"),
    )
    row = await _raw_fetch(db, f"featured_{session_id}")
    assert row is not None
    # Either terminal state is legal under a real race; what must hold is that the
    # row is exactly one of them and published_at only moves on ONLINE.
    assert row["status"] in (ONLINE_STATUS, OFFLINE_STATUS)
    if row["status"] == OFFLINE_STATUS:
        assert row["published_at"] is None  # never went ONLINE
    else:
        assert row["published_at"] is not None


@pytest.mark.integration
async def test_replaying_the_whole_sequence_is_safe(
    db: Database, store: FeaturedConversationRepository, seed_session: Any
) -> None:
    """Idempotence of the full create -> online -> update -> offline chain."""
    session_id = f"s-replay-{_uid()}"
    await seed_session(session_id)
    case = _use_case(store, db, clock=lambda: _BASE)

    def _script() -> list[Any]:
        # Thunks, not coroutines: building the four calls eagerly would leak
        # un-awaited coroutines (and their RuntimeWarnings) the moment one of the
        # assertions below fails.
        return [
            lambda: case.create(
                UpsertCommand(session_id=session_id, title="t", sort_order=1, operator="bob")
            ),
            lambda: case.online(f"featured_{session_id}", "alice"),
            lambda: case.update(
                UpsertCommand(
                    featured_id=f"featured_{session_id}",
                    # Java's repo.upsert refuses a blank sessionId without writing,
                    # so the update leg must carry one or it answers false. The UI
                    # always does (sessionId is required in its payload type).
                    session_id=session_id,
                    title="t2",
                    operator="carol",
                )
            ),
            lambda: case.offline(f"featured_{session_id}", "bob"),
        ]

    for step in _script():
        assert await step() is True
    first = await _raw_fetch(db, f"featured_{session_id}")
    for step in _script():
        assert await step() is True
    second = await _raw_fetch(db, f"featured_{session_id}")

    # Replaying must not accumulate side effects beyond updated_by/updated_at.
    for key in ("featured_id", "session_id", "title", "sort_order", "status", "deleted"):
        assert first[key] == second[key], key
