"""Featured-conversation public read rules.

Ported from ``FeaturedConversationPublicQueryApplicationService`` plus the
JSON shapes of ``FeaturedConversationCardRespVO`` / ``FeaturedConversationDetailRespVO``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reactor_backend.domain.time_format import format_local_datetime

ONLINE_STATUS = "ONLINE"
CONTENT_UNAVAILABLE_REASON = "session_history_missing"

HOME_DEFAULT_LIMIT = 6
LIST_DEFAULT_PAGE_NO = 1
LIST_DEFAULT_PAGE_SIZE = 20


def normalize_limit(limit: int) -> int:
    """``Math.max(1, limit)`` — lower bound only, no upper bound."""
    return max(1, limit)


def normalize_page_no(page_no: int) -> int:
    return max(1, page_no)


def normalize_page_size(page_size: int) -> int:
    return max(1, page_size)


def page_offset(page_no: int, page_size: int) -> int:
    return (normalize_page_no(page_no) - 1) * normalize_page_size(page_size)


def is_online(status: str | None) -> bool:
    """``"ONLINE".equalsIgnoreCase(StringUtils.trimToEmpty(status))``."""
    if status is None:
        return False
    return status.strip().upper() == ONLINE_STATUS


def is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def parse_tags(tags_json: Any) -> list[str]:
    """fastjson ``JSON.parseArray(tagsJson, String.class)``.

    Blank or unparsable JSON yields ``[]``; scalars inside the array are coerced
    to strings the way fastjson's String codec does. Accepts the raw column text
    or an already-deserialized value (MySQL JSON columns may surface as a list).
    """
    if tags_json is None:
        return []
    if isinstance(tags_json, (list, dict)):
        parsed: Any = tags_json
    else:
        text = tags_json if isinstance(tags_json, str) else str(tags_json)
        if text.strip() == "":
            return []
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    for item in parsed:
        if item is None:
            result.append("null")
        elif isinstance(item, str):
            result.append(item)
        elif isinstance(item, bool):
            result.append("true" if item else "false")
        elif isinstance(item, (int, float)):
            result.append(_number_to_string(item))
        elif isinstance(item, dict):
            result.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        else:
            result.append(str(item))
    return result


def _number_to_string(value: int | float) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return str(value)


@dataclass
class FeaturedConversationRow:
    """Raw row from ``ai_agent_featured_conversation``."""

    id: int | None = None
    featured_id: str | None = None
    session_id: str | None = None
    title: str | None = None
    summary: str | None = None
    cover_resource_key: str | None = None
    cover_url: str | None = None
    tags_json: str | None = None
    sort_order: int | None = None
    status: str | None = None
    published_by: str | None = None
    published_at: datetime | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


def to_card_payload(
    row: FeaturedConversationRow,
    content_last_active_at: datetime | None,
) -> dict[str, Any]:
    """JSON shape of ``FeaturedConversationCardRespVO`` — field order is contract."""
    return {
        "featuredId": row.featured_id,
        "sessionId": row.session_id,
        "title": row.title,
        "summary": row.summary,
        "coverUrl": row.cover_url,
        "tags": parse_tags(row.tags_json),
        "publishedAt": format_local_datetime(row.published_at),
        "contentLastActiveAt": format_local_datetime(content_last_active_at),
    }


def to_detail_payload(
    row: FeaturedConversationRow,
    content_last_active_at: datetime | None,
    history_detail: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """JSON shape of ``FeaturedConversationDetailRespVO`` — field order is contract."""
    return {
        "featuredId": row.featured_id,
        "sessionId": row.session_id,
        "title": row.title,
        "summary": row.summary,
        "coverUrl": row.cover_url,
        "tags": parse_tags(row.tags_json),
        "status": row.status,
        "publishedAt": format_local_datetime(row.published_at),
        "contentLastActiveAt": format_local_datetime(content_last_active_at),
        "contentAvailable": history_detail is not None,
        "contentUnavailableReason": (
            CONTENT_UNAVAILABLE_REASON if history_detail is None else None
        ),
        "historyDetail": dict(history_detail) if history_detail is not None else None,
    }


@dataclass
class PageResult:
    total: int
    list: Sequence[Mapping[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {"total": int(self.total), "list": [dict(item) for item in self.list]}
