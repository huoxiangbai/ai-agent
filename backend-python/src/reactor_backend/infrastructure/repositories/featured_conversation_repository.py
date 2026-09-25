"""Featured-conversation repository (public reads + admin writes).

SQL text mirrors ``featured_conversation_mapper.xml`` — including the columns the
``ON DUPLICATE KEY UPDATE`` clause deliberately leaves alone (``session_id``,
``featured_id``, ``status``, ``published_by``, ``published_at``). Bound parameters
only; the admin filter fragment is assembled from fixed clause strings and never
interpolates user text. ``LIMIT :offset, :limit`` binds Python ints.

Rowcounts are compared with ``> 0`` on the caller side and mean **found** rows, not
affected rows: the engine ORs ``CLIENT.FOUND_ROWS`` into the connection so that a
matched-but-unchanged ``UPDATE`` / no-op ``ON DUPLICATE KEY UPDATE`` returns 1 here
exactly as MySQL Connector/J reports it to Java (its default is
``useAffectedRows=false``).
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from reactor_backend.domain.featured_admin import AdminQueryCondition, StatusUpdate, UpsertPo
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

_SQL_BY_SESSION_ID = text(
    f"""
    SELECT {_QUERY_COLUMNS}
    FROM ai_agent_featured_conversation
    WHERE session_id = :session_id
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

# The UPDATE clause is intentionally partial: session_id / featured_id / status /
# published_by / published_at are never touched on the duplicate branch.
_SQL_UPSERT = text(
    """
    INSERT INTO ai_agent_featured_conversation (
        featured_id, session_id, title, summary, cover_resource_key, cover_url,
        tags_json, sort_order, status, published_by, published_at, updated_by,
        updated_at, deleted
    ) VALUES (
        :featured_id, :session_id, :title, :summary, :cover_resource_key, :cover_url,
        :tags_json, :sort_order, :status, :published_by, :published_at, :updated_by,
        :updated_at, 0
    )
    ON DUPLICATE KEY UPDATE
        title = VALUES(title),
        summary = VALUES(summary),
        cover_resource_key = VALUES(cover_resource_key),
        cover_url = VALUES(cover_url),
        tags_json = VALUES(tags_json),
        sort_order = VALUES(sort_order),
        updated_by = VALUES(updated_by),
        updated_at = VALUES(updated_at),
        deleted = 0
    """
)

_SQL_UPDATE_STATUS = text(
    """
    UPDATE ai_agent_featured_conversation
    SET status = :status,
        published_at = :published_at,
        updated_by = :updated_by,
        updated_at = :updated_at,
        deleted = 0
    WHERE featured_id = :featured_id
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


def _admin_where(
    status: str | None, session_id: str | None, title: str | None
) -> tuple[str, dict[str, Any]]:
    """Mirror the MyBatis ``<if test="... != null and ... != ''">`` guards.

    The guard is a strict empty-string check (OGNL ``!= ''``), not a blank check:
    a whitespace-only filter *is* applied (``status = '   '``). ``title`` stays a
    bound parameter inside ``CONCAT('%', :title, '%')`` so ``%``/``_`` keep their
    LIKE-wildcard meaning, matching Java.
    """
    clauses = ["deleted = 0"]
    params: dict[str, Any] = {}
    if status is not None and status != "":
        clauses.append("status = :status")
        params["status"] = status
    if session_id is not None and session_id != "":
        clauses.append("session_id = :session_id")
        params["session_id"] = session_id
    if title is not None and title != "":
        clauses.append("title LIKE CONCAT('%', :title, '%')")
        params["title"] = title
    return " AND ".join(clauses), params


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

    async def query_by_session_id(self, session_id: str) -> FeaturedConversationRow | None:
        async with self._db.connect() as connection:
            result = await connection.execute(
                _SQL_BY_SESSION_ID, {"session_id": session_id}
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

    async def query_admin_list(
        self, condition: AdminQueryCondition
    ) -> Sequence[FeaturedConversationRow]:
        where, params = _admin_where(condition.status, condition.session_id, condition.title)
        statement = text(
            f"""
            SELECT {_QUERY_COLUMNS}
            FROM ai_agent_featured_conversation
            WHERE {where}
            ORDER BY sort_order DESC, id DESC
            LIMIT :offset, :limit
            """
        )
        async with self._db.connect() as connection:
            result = await connection.execute(
                statement,
                {**params, "offset": int(condition.offset), "limit": int(condition.limit)},
            )
            return [_row_to_entity(row) for row in result.all()]

    async def count_admin_list(self, condition: AdminQueryCondition) -> int:
        where, params = _admin_where(condition.status, condition.session_id, condition.title)
        statement = text(
            f"""
            SELECT COUNT(1)
            FROM ai_agent_featured_conversation
            WHERE {where}
            """
        )
        async with self._db.connect() as connection:
            result = await connection.execute(statement, params)
            return int(result.scalar() or 0)

    async def upsert(self, po: UpsertPo) -> bool:
        """``featuredConversationDao.upsert(po) > 0`` — found rows, not affected rows."""
        async with self._db.connect() as connection:
            result = await connection.execute(
                _SQL_UPSERT,
                {
                    "featured_id": po.featured_id,
                    "session_id": po.session_id,
                    "title": po.title,
                    "summary": po.summary,
                    "cover_resource_key": po.cover_resource_key,
                    "cover_url": po.cover_url,
                    "tags_json": po.tags_json,
                    "sort_order": int(po.sort_order),
                    "status": po.status,
                    "published_by": po.published_by,
                    "published_at": po.published_at,
                    "updated_by": po.updated_by,
                    "updated_at": po.updated_at,
                },
            )
            return (result.rowcount or 0) > 0

    async def update_status(self, update: StatusUpdate) -> bool:
        """``featuredConversationDao.updateStatus(...) > 0`` — found rows.

        A concurrent soft-delete between the caller's SELECT and this UPDATE makes
        the WHERE miss and reports ``0``/``false`` on both sides.
        """
        async with self._db.connect() as connection:
            result = await connection.execute(
                _SQL_UPDATE_STATUS,
                {
                    "status": update.status,
                    "published_at": update.published_at,
                    "updated_by": update.updated_by,
                    "updated_at": update.updated_at,
                    "featured_id": update.featured_id,
                },
            )
            return (result.rowcount or 0) > 0
