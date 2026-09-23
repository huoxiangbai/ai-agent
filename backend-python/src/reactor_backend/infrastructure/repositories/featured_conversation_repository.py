"""Read-only featured-conversation repository.

SQL text mirrors ``featured_conversation_mapper.xml``. Bound parameters only —
no f-string SQL. ``LIMIT :offset, :limit`` binds Python ints.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from reactor_backend.domain.featured_conversation import FeaturedConversationRow

_QUERY_COLUMNS = """
    id, featured_id, session_id, title, summary, cover_resource_key, cover_url,
    tags_json, sort_order, status, published_by, published_at, updated_by,
    updated_at
"""

_SQL_BY_FEATURED_ID = text(
    f"""
    SELECT {_QUERY_COLUMNS}
    FROM ai_agent_featured_conversation
    WHERE featured_id = :featured_id
      AND deleted = 0
    LIMIT 1
    """
)

_SQL_ONLINE_LIST = text(
    f"""
    SELECT {_QUERY_COLUMNS}
    FROM ai_agent_featured_conversation
    WHERE status = 'ONLINE'
      AND deleted = 0
    ORDER BY sort_order DESC, id DESC
    LIMIT :offset, :limit
    """
)

_SQL_COUNT_ONLINE = text(
    """
    SELECT COUNT(1)
    FROM ai_agent_featured_conversation
    WHERE status = 'ONLINE'
      AND deleted = 0
    """
)


class _Connectable(Protocol):
    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]: ...


def _row_to_entity(row: Any) -> FeaturedConversationRow:
    return FeaturedConversationRow(
        id=row.id,
        featured_id=row.featured_id,
        session_id=row.session_id,
        title=row.title,
        summary=row.summary,
        cover_resource_key=row.cover_resource_key,
        cover_url=row.cover_url,
        tags_json=row.tags_json,
        sort_order=row.sort_order,
        status=row.status,
        published_by=row.published_by,
        published_at=row.published_at,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


class FeaturedConversationRepository:
    def __init__(self, db: _Connectable) -> None:
        self._db = db

    async def query_by_featured_id(self, featured_id: str) -> FeaturedConversationRow | None:
        async with self._db.connect() as connection:
            result = await connection.execute(
                _SQL_BY_FEATURED_ID, {"featured_id": featured_id}
            )
            row = result.first()
            return None if row is None else _row_to_entity(row)

    async def query_online_list(
        self, offset: int, limit: int
    ) -> Sequence[FeaturedConversationRow]:
        async with self._db.connect() as connection:
            result = await connection.execute(
                _SQL_ONLINE_LIST,
                {"offset": int(offset), "limit": int(limit)},
            )
            return [_row_to_entity(row) for row in result.all()]

    async def count_online(self) -> int:
        async with self._db.connect() as connection:
            result = await connection.execute(_SQL_COUNT_ONLINE)
            scalar = result.scalar()
            # COUNT returns Decimal on some drivers — force a plain int (R: 2.0 trap)
            return int(scalar or 0)
