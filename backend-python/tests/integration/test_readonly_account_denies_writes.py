"""``reactor_py_ro`` must be SELECT-only (risk-register R-22 enforcement).

Requires ``TEST_MYSQL_URL`` to point at the read-only account. Every write must
fail with MySQL error 1142 (command denied) — if any write succeeds, the
single-writer rule has no technical enforcement and the test fails.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from reactor_backend.config import Settings
from reactor_backend.infrastructure.database import Database

_WRITE_STATEMENTS = [
    (
        "insert",
        "INSERT INTO ai_agent_featured_conversation "
        "(featured_id, session_id, title, summary, tags_json, sort_order, status, "
        "create_time, update_time, deleted) "
        "VALUES ('ro-denied', 'x', 'x', 'x', '[]', 0, 'ONLINE', NOW(), NOW(), 0)",
    ),
    (
        "update",
        "UPDATE ai_agent_featured_conversation SET summary = 'denied' "
        "WHERE featured_id = 'fixture-featured'",
    ),
    (
        "delete",
        "DELETE FROM ai_agent_featured_conversation WHERE featured_id = 'ro-denied'",
    ),
    (
        "create",
        "CREATE TABLE ro_denied_probe (id INT PRIMARY KEY)",
    ),
]


def _url() -> str | None:
    return os.getenv("TEST_MYSQL_URL")


@pytest.fixture
async def connection() -> Any:
    url = _url()
    if not url:
        pytest.skip("TEST_MYSQL_URL is required for the read-only account test")
    database = Database(Settings(database_url=SecretStr(url)))
    await database.start()
    try:
        async with database.connect() as conn:
            yield conn
    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_select_is_allowed(connection: Any) -> None:
    result = await connection.execute(
        text("SELECT COUNT(1) FROM ai_agent_featured_conversation")
    )
    assert int(result.scalar() or 0) >= 0


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "statement"), _WRITE_STATEMENTS, ids=[n for n, _ in _WRITE_STATEMENTS]
)
async def test_writes_are_denied(connection: Any, name: str, statement: str) -> None:
    with pytest.raises(DatabaseError) as excinfo:
        await connection.execute(text(statement))
    message = str(excinfo.value).lower()
    assert "1142" in message or "command denied" in message or "denied" in message, (
        f"{name} did not fail with a privilege error: {excinfo.value}"
    )
