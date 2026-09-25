"""``reactor_py_featured_writer`` must be scoped to one table and two verbs.

Risk-register R-22 enforcement for phase 4. Requires
``TEST_MYSQL_FEATURED_WRITER_URL`` to point at the account provisioned by
``db/migrations/20260923_provision_phase4_featured_writer_account.sql`` (or a
test-only clone of it). Every statement outside that scope must fail with MySQL
error 1142 (command denied) — if any succeeds, the single-writer rule has no
technical enforcement and the test fails.

The allowed surface is exactly what the slice needs:

* ``INSERT`` / ``UPDATE`` on ``ai_agent_featured_conversation`` (the writer);
* ``SELECT`` everywhere (create's session-existence check plus the pre-upsert
  lookups);
* **no ``DELETE``** — every "delete" in this domain is the ``deleted = 0`` flip
  inside ``UPDATE``, so a real DELETE can only ever be a bug;
* **no DDL** — the schema is frozen for this migration stage (no Alembic).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from reactor_backend.config import Settings
from reactor_backend.infrastructure.database import Database

_BASE = datetime(2026, 9, 23, 10, 0, 0)


def _url() -> str | None:
    return os.getenv("TEST_MYSQL_FEATURED_WRITER_URL")


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def connection() -> AsyncIterator[Any]:
    url = _url()
    if not url:
        pytest.skip(
            "TEST_MYSQL_FEATURED_WRITER_URL is required for the writer-account scope test"
        )
    database = Database(Settings(database_url=SecretStr(url)))
    await database.start()
    try:
        async with database.connect() as conn:
            yield conn
    finally:
        await database.close()


async def _exec(conn: Any, sql: str, params: dict[str, Any] | None = None) -> int:
    result = await conn.execute(text(sql), params or {})
    return int(result.rowcount or 0)


@pytest.mark.integration
async def test_insert_and_update_on_the_featured_table_are_allowed(
    connection: Any,
) -> None:
    fid = f"scope-{_uid()}"
    sid = f"scope-s-{_uid()}"
    await _exec(
        connection,
        "INSERT INTO ai_agent_featured_conversation "
        "(featured_id, session_id, title, tags_json, sort_order, status, "
        " updated_by, updated_at, deleted) "
        "VALUES (:fid, :sid, 'scope', '[]', 0, 'OFFLINE', 'scope', :ts, 0)",
        {"fid": fid, "sid": sid, "ts": _BASE},
    )
    assert (
        await _exec(
            connection,
            "UPDATE ai_agent_featured_conversation SET title = 'scoped' WHERE featured_id = :fid",
            {"fid": fid},
        )
        == 1
    )
    # The soft-delete flip the domain actually uses must work too.
    assert (
        await _exec(
            connection,
            "UPDATE ai_agent_featured_conversation SET deleted = 1 WHERE featured_id = :fid",
            {"fid": fid},
        )
        == 1
    )


@pytest.mark.integration
async def test_select_wide_is_allowed_for_the_session_check(connection: Any) -> None:
    result = await connection.execute(
        text("SELECT COUNT(1) FROM ai_agent_dialogue_session")
    )
    assert int(result.scalar() or 0) >= 0


_DENIED = [
    (
        "delete",
        "DELETE FROM ai_agent_featured_conversation WHERE featured_id = 'scope-denied'",
    ),
    (
        "insert-other-table",
        "INSERT INTO ai_agent_dialogue_session "
        "(session_id, title, status, run_count, finished_run_count, failed_run_count, deleted) "
        "VALUES ('scope-denied', 'x', 0, 0, 0, 0, 0)",
    ),
    (
        "update-other-table",
        "UPDATE ai_agent_dialogue_session SET title = 'denied' WHERE session_id = 'scope-denied'",
    ),
    ("create-table", "CREATE TABLE scope_denied_probe (id INT PRIMARY KEY)"),
    ("drop-table", "DROP TABLE IF EXISTS scope_denied_probe"),
    ("alter-table", "ALTER TABLE ai_agent_featured_conversation ADD COLUMN scope_probe INT"),
]


@pytest.mark.integration
@pytest.mark.parametrize(("name", "sql"), _DENIED, ids=[n for n, _ in _DENIED])
async def test_everything_outside_scope_is_denied_with_1142(
    connection: Any, name: str, sql: str
) -> None:
    with pytest.raises(DatabaseError) as raised:
        await _exec(connection, sql)
    # 1142 = ER_TABLEACCESS_DENIED_ERROR / ER_SPECIFIC_ACCESS_DENIED_ERROR family.
    assert "1142" in str(raised.value) or "command denied" in str(raised.value).lower(), (
        f"{name}: expected ERROR 1142, got {raised.value!r}"
    )
