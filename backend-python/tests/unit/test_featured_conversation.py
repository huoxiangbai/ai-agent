from __future__ import annotations

from datetime import datetime

from reactor_backend.domain.featured_conversation import (
    FeaturedConversationRow,
    PageResult,
    is_blank,
    is_online,
    normalize_limit,
    normalize_page_no,
    normalize_page_size,
    page_offset,
    parse_tags,
    to_card_payload,
    to_detail_payload,
)


def test_home_default_limit_6() -> None:
    assert normalize_limit(6) == 6
    assert normalize_limit(0) == 1


def test_list_default_page_1_size_20() -> None:
    assert normalize_page_no(1) == 1
    assert normalize_page_size(20) == 20


def test_lower_bound_clamping_without_upper_bound() -> None:
    # Math.max(1, x) — no upper bound on any of the three.
    assert normalize_limit(0) == 1
    assert normalize_limit(-1) == 1
    assert normalize_limit(10_000) == 10_000
    assert normalize_page_no(0) == 1
    assert normalize_page_no(-5) == 1
    assert normalize_page_size(0) == 1
    assert normalize_page_size(-5) == 1
    assert normalize_page_size(9_999) == 9_999


def test_offset_formula() -> None:
    assert page_offset(1, 20) == 0
    assert page_offset(2, 20) == 20
    assert page_offset(3, 7) == 14
    # clamped inputs feed the same formula
    assert page_offset(0, 0) == 0


def test_empty_list_is_empty_not_null() -> None:
    payload = PageResult(total=0, list=[]).to_payload()
    assert payload == {"total": 0, "list": []}
    assert isinstance(payload["list"], list)


def test_total_is_json_number() -> None:
    payload = PageResult(total=2, list=[]).to_payload()
    assert isinstance(payload["total"], int)


def test_not_found_and_blank_id() -> None:
    assert is_blank(None)
    assert is_blank("")
    assert is_blank("   ")
    # detail for blank id → data:null (None)
    assert to_detail_payload(
        FeaturedConversationRow(), None, None
    )["featuredId"] is None


def test_content_unavailable_reason_exact_string() -> None:
    row = FeaturedConversationRow(featured_id="f1", session_id="s1")
    payload = to_detail_payload(row, None, None)
    assert payload["contentAvailable"] is False
    assert payload["contentUnavailableReason"] == "session_history_missing"


def test_content_available_when_history_present() -> None:
    row = FeaturedConversationRow(featured_id="f1", session_id="s1")
    payload = to_detail_payload(row, None, {"sessionId": "s1"})
    assert payload["contentAvailable"] is True
    assert payload["contentUnavailableReason"] is None


def test_online_filter_is_equals_ignore_case_trim() -> None:
    assert is_online("ONLINE")
    assert is_online("online")
    assert is_online("  Online  ")
    assert not is_online("OFFLINE")
    assert not is_online("")
    assert not is_online(None)
    assert not is_online("  ")


def test_tags_parsing_shapes() -> None:
    assert parse_tags(None) == []
    assert parse_tags("") == []
    assert parse_tags("   ") == []
    assert parse_tags('["a","b"]') == ["a", "b"]
    assert parse_tags('["a", 1, true, null]') == ["a", "1", "true", "null"]
    assert parse_tags('["中文","、分隔"]') == ["中文", "、分隔"]
    # malformed → [] (fastjson throws and the repository swallows → empty)
    assert parse_tags("{not json") == []
    assert parse_tags('"scalar"') == []
    assert parse_tags("42") == []
    # empty array
    assert parse_tags("[]") == []


def test_time_format_zero_millis_omits_fraction() -> None:
    row = FeaturedConversationRow(
        featured_id="f1",
        published_at=datetime(2026, 1, 2, 10, 0, 0),
    )
    payload = to_card_payload(row, datetime(2026, 1, 3, 9, 0, 0))
    assert payload["publishedAt"] == "2026-01-02T10:00:00"
    assert payload["contentLastActiveAt"] == "2026-01-03T09:00:00"


def test_time_format_nonzero_millis_three_digits() -> None:
    row = FeaturedConversationRow(
        featured_id="f1",
        published_at=datetime(2026, 1, 2, 10, 0, 0, 123000),
    )
    payload = to_card_payload(row, None)
    assert payload["publishedAt"] == "2026-01-02T10:00:00.123"
    assert payload["contentLastActiveAt"] is None


def test_time_format_never_emits_microseconds() -> None:
    row = FeaturedConversationRow(
        featured_id="f1",
        published_at=datetime(2026, 1, 2, 10, 0, 0, 123456),
    )
    payload = to_card_payload(row, None)
    # sub-millisecond precision degrades to milliseconds (3 digits), never 6
    assert payload["publishedAt"] == "2026-01-02T10:00:00.123"


def test_card_field_order_is_contract() -> None:
    row = FeaturedConversationRow(
        featured_id="f1",
        session_id="s1",
        title="t",
        summary="s",
        cover_url=None,
        tags_json='["a"]',
        published_at=datetime(2026, 1, 2, 10, 0, 0),
    )
    payload = to_card_payload(row, datetime(2026, 1, 3, 9, 0, 0))
    assert list(payload.keys()) == [
        "featuredId",
        "sessionId",
        "title",
        "summary",
        "coverUrl",
        "tags",
        "publishedAt",
        "contentLastActiveAt",
    ]
    # coverUrl:null must be emitted, not omitted
    assert "coverUrl" in payload
    assert payload["coverUrl"] is None


def test_detail_field_order_is_contract() -> None:
    row = FeaturedConversationRow(
        featured_id="f1",
        session_id="s1",
        title="t",
        summary="s",
        status="ONLINE",
        published_at=datetime(2026, 1, 2, 10, 0, 0),
    )
    payload = to_detail_payload(row, datetime(2026, 1, 3, 9, 0, 0), {"sessionId": "s1"})
    assert list(payload.keys()) == [
        "featuredId",
        "sessionId",
        "title",
        "summary",
        "coverUrl",
        "tags",
        "status",
        "publishedAt",
        "contentLastActiveAt",
        "contentAvailable",
        "contentUnavailableReason",
        "historyDetail",
    ]
    # detail carries the raw DB status value
    assert payload["status"] == "ONLINE"
