"""Featured-conversation admin write rules.

Ported from ``FeaturedConversationAdminApplicationService`` plus the write half of
``FeaturedConversationRepository`` and the JSON shapes of
``FeaturedConversationAdminUpsertReqVO`` / ``FeaturedConversationAdminQueryReqVO`` /
``FeaturedConversationAdminRespVO``.

Two Java behaviours are load-bearing here and must not be "tidied up":

* ``create`` derives ``featuredId = "featured_" + trim(sessionId)`` and discards the
  request's ``featuredId`` entirely; ``update`` passes ``featuredId``/``sessionId``
  through **untrimmed** into the upsert.
* ``FeaturedConversationAdminQueryReqVO.pageNo``/``pageSize`` carry Lombok
  ``@Builder.Default`` initializers. Jackson binds through the **no-arg
  constructor**, and that constructor runs the ``$default$`` accessors — verified by
  ``javap`` on the compiled VO, whose ``<init>`` calls ``$default$pageNo()`` (1) then
  ``$default$pageSize()`` (10). So an **absent** key is ``1``/``10``, while a
  **present JSON null** is written by the setter as ``0``
  (``FAIL_ON_NULL_FOR_PRIMITIVES`` off). The two are observably different and are
  measured, not assumed: ``{}`` pages at width 10, ``{"pageSize":null}`` at width 1,
  ``{"pageNo":2}`` alone starts at offset 10.

Business-rule failures raise :class:`FeaturedAdminRuleError`, the port of
``IllegalArgumentException``. ``FeaturedConversationAdminController`` has no
try/catch and Java has no ``@ControllerAdvice``, so those escape as HTTP 500 +
Spring's ``BasicErrorController`` four-key body — never as a ``0002`` envelope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from reactor_backend.domain.featured_conversation import (
    FeaturedConversationRow,
    is_blank,
    parse_tags,
)
from reactor_backend.domain.time_format import format_local_datetime

ONLINE_STATUS = "ONLINE"
OFFLINE_STATUS = "OFFLINE"
FEATURED_ID_PREFIX = "featured_"

# Lombok ``@Builder.Default`` values the no-arg constructor installs. Absent keys
# land here; a present JSON null is overwritten with 0 by the setter.
ABSENT_PAGE_NO = 1
ABSENT_PAGE_SIZE = 10


class FeaturedAdminRuleError(Exception):
    """``IllegalArgumentException`` on the Java side → HTTP 500 four-key body."""


@dataclass
class UpsertCommand:
    """``FeaturedConversationUpsertCommand`` — field order mirrors the Java record."""

    featured_id: str | None = None
    session_id: str | None = None
    title: str | None = None
    summary: str | None = None
    cover_resource_key: str | None = None
    cover_url: str | None = None
    tags: list[str | None] | None = None
    sort_order: int | None = None
    operator: str | None = None


@dataclass
class AdminQueryCondition:
    """``FeaturedConversationQueryCondition`` as the controller builds it.

    ``page_no``/``page_size`` are the raw Jackson values: the Lombok default when
    the key is absent, ``0`` when it is a present JSON null. The offset/limit
    clamping happens on access, exactly like the controller's ``Math.max(1, ...)``
    expressions.
    """

    status: str | None = None
    session_id: str | None = None
    title: str | None = None
    page_no: int = ABSENT_PAGE_NO
    page_size: int = ABSENT_PAGE_SIZE

    @property
    def offset(self) -> int:
        """``(Math.max(1, pageNo) - 1) * Math.max(1, pageSize)``."""
        return (max(1, self.page_no) - 1) * max(1, self.page_size)

    @property
    def limit(self) -> int:
        """``Math.max(1, pageSize)``."""
        return max(1, self.page_size)


@dataclass
class UpsertPo:
    """Values bound by ``featured_conversation_mapper.xml``'s ``upsert`` statement.

    ``status``/``published_by``/``published_at`` are only consumed by the INSERT
    branch: the ``ON DUPLICATE KEY UPDATE`` clause deliberately does not touch them,
    nor ``session_id``/``featured_id``. They are still assembled faithfully so the
    statement text stays 1:1 with the mapper.
    """

    featured_id: str
    session_id: str
    title: str | None
    summary: str | None
    cover_resource_key: str | None
    cover_url: str | None
    tags_json: str
    sort_order: int
    status: str
    published_by: str | None
    published_at: datetime | None
    updated_by: str | None
    updated_at: datetime


@dataclass
class StatusUpdate:
    """Values bound by the mapper's ``updateStatus`` statement."""

    featured_id: str
    status: str
    published_at: datetime | None
    updated_by: str | None
    updated_at: datetime


def generate_featured_id(session_id: str) -> str:
    """``"featured_" + StringUtils.trim(sessionId)`` — request ``featuredId`` ignored."""
    return FEATURED_ID_PREFIX + session_id.strip()


def validate_create_command(command: UpsertCommand | None) -> str:
    """Return the trimmed session id, or raise ``IllegalArgumentException``."""
    if command is None or is_blank(command.session_id):
        raise FeaturedAdminRuleError("sessionId 不能为空")
    return (command.session_id or "").strip()


def upsert_guard_blocks(command: UpsertCommand | None) -> bool:
    """``FeaturedConversationRepository.upsert``'s entry guard.

    Java returns ``false`` **without issuing any SQL** when ``command`` is null or
    ``featuredId``/``sessionId`` is blank. ``create`` cannot trip it (sessionId is
    validated and ``featuredId`` is generated), but ``update`` can: a body with a
    valid ``featuredId`` and no ``sessionId`` passes the existence pre-check, then
    no-ops here. The request looks successful — HTTP 200 + ``data:false`` — and the
    row is untouched.
    """
    return (
        command is None
        or is_blank(command.featured_id)
        or is_blank(command.session_id)
    )


def validate_update_command(command: UpsertCommand | None) -> str:
    """Return the ``featuredId`` **untrimmed**, or raise ``IllegalArgumentException``."""
    if command is None or is_blank(command.featured_id):
        raise FeaturedAdminRuleError("featuredId 不能为空")
    return command.featured_id or ""


def to_tags_json(tags: list[str | None] | None) -> str:
    """fastjson ``JSON.toJSONString(tags == null ? List.of() : tags)``.

    Compact separators and raw non-ASCII, matching fastjson's default writer.
    ``None`` elements stay JSON ``null`` — fastjson keeps nulls inside arrays.
    """
    return json.dumps(
        tags if tags is not None else [],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_upsert_po(
    command: UpsertCommand,
    existing: FeaturedConversationRow | None,
    *,
    now: datetime,
) -> UpsertPo:
    """Assemble the mapper ``upsert`` bindings the way the Java adapter does.

    ``existing`` is ``queryByFeaturedId`` falling back to ``queryBySessionId``. When
    it is non-null the INSERT branch cannot fire (both lookups only miss rows that
    the two UNIQUE keys would still collide with), so ``status``/``published_*`` are
    discarded by ``ON DUPLICATE KEY UPDATE`` — they are written here for statement
    fidelity, not because they take effect.
    """
    if existing is None:
        status = OFFLINE_STATUS
        published_by = command.operator
        published_at = None
    else:
        # StringUtils.defaultIfBlank(existing.getStatus(), OFFLINE_STATUS)
        status = (
            OFFLINE_STATUS if is_blank(existing.status) else (existing.status or OFFLINE_STATUS)
        )
        published_by = existing.published_by
        published_at = existing.published_at
    return UpsertPo(
        featured_id=command.featured_id or "",
        session_id=command.session_id or "",
        title=command.title,
        summary=command.summary,
        cover_resource_key=command.cover_resource_key,
        cover_url=command.cover_url,
        tags_json=to_tags_json(command.tags),
        sort_order=0 if command.sort_order is None else command.sort_order,
        status=status,
        published_by=published_by,
        published_at=published_at,
        updated_by=command.operator,
        updated_at=now,
    )


def build_status_update(
    featured_id: str,
    status: str,
    operator: str | None,
    existing: FeaturedConversationRow,
    *,
    now: datetime,
) -> StatusUpdate:
    """Online stamps ``published_at = now``; offline keeps the existing value.

    ``StringUtils.upperCase(status)`` — the two call sites already pass the
    constants, so this only matters for direct repository use.
    """
    normalized_status = status.upper()
    published_at = now if normalized_status == ONLINE_STATUS else existing.published_at
    return StatusUpdate(
        featured_id=featured_id,
        status=normalized_status,
        published_at=published_at,
        updated_by=operator,
        updated_at=now,
    )


def to_admin_payload(row: FeaturedConversationRow) -> dict[str, Any]:
    """``FeaturedConversationAdminRespVO`` — field order is contract, no ``coverResourceKey``."""
    return {
        "featuredId": row.featured_id,
        "sessionId": row.session_id,
        "title": row.title,
        "summary": row.summary,
        "tags": parse_tags(row.tags_json),
        "coverUrl": row.cover_url,
        "sortOrder": row.sort_order,
        "status": row.status,
        "publishedAt": format_local_datetime(row.published_at),
        "updatedAt": format_local_datetime(row.updated_at),
    }
