"""Repository integration for the featured public-read slice.

Requires ``TEST_MYSQL_URL`` pointing at the throwaway database seeded with
``tests/contract/fixtures/contract-seed.sql`` and
``tests/integration/fixtures/featured_read_edge_seed.sql``. The account should be
``reactor_py_ro`` (SELECT-only) so these tests double as the read-only runtime
verification.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import SecretStr

from reactor_backend.application.featured_conversation_query import (
    FeaturedConversationQueryUseCase,
)
from reactor_backend.config import Settings
from reactor_backend.domain.replay_projector import ReplayProjector
from reactor_backend.infrastructure.database import Database
from reactor_backend.infrastructure.llm_model_window import LlmModelWindowResolver
from reactor_backend.infrastructure.repositories import (
    ExecutionLedgerRepository,
    FeaturedConversationRepository,
)


def _url() -> str | None:
    return os.getenv("TEST_MYSQL_URL")


@pytest.fixture
async def use_case() -> Any:
    url = _url()
    if not url:
        pytest.skip("TEST_MYSQL_URL is required for repository integration tests")
    database = Database(Settings(database_url=SecretStr(url)))
    await database.start()
    try:
        yield FeaturedConversationQueryUseCase(
            featured_reader=FeaturedConversationRepository(database),
            ledger_reader=ExecutionLedgerRepository(database),
            model_window=LlmModelWindowResolver(database),
            history_projector=ReplayProjector(),
        )
    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_online_list_orders_by_sort_order_desc_then_id_desc(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    cards = await use_case.query_home_cards(50)
    ids = [card["featuredId"] for card in cards]

    # Edge rows (sort 500/400/200/150) precede the contract fixtures (100/50);
    # OFFLINE (300) and deleted (250) rows are excluded entirely.
    assert ids.index("edge-featured-tags") == 0  # sort_order 500
    assert ids.index("edge-featured-millis") == 1  # sort_order 400
    assert "edge-featured-offline" not in ids
    assert "edge-featured-deleted" not in ids
    # Contract fixtures keep their relative order at the tail.
    assert ids.index("fixture-featured") < ids.index("fixture-featured-2")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_count_online_excludes_offline_and_deleted(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    page = await use_case.query_public_list(1, 100)
    listed = page["total"]
    # 2 contract + 4 edge ONLINE-and-not-deleted rows.
    assert listed == 6
    assert listed == len(page["list"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_out_of_range_page_returns_empty_list_with_total(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    page = await use_case.query_public_list(999, 20)
    assert page["total"] >= 6
    assert page["list"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_malformed_tags_json_falls_back_to_empty_list(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-tags")
    assert detail is not None
    # {"not":"an array"} is unparsable as an array → [].
    assert detail["tags"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tags_scalars_are_coerced_to_strings(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-millis")
    assert detail is not None
    # [1, true, null] → fastjson String codec: "1", "true", "null".
    assert detail["tags"] == ["1", "true", "null"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_millisecond_timestamps_keep_three_digits(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-millis")
    assert detail is not None
    # .456 → exactly three digits; never isoformat() six-digit microseconds.
    assert detail["publishedAt"] == "2026-01-05T10:00:00.456"
    assert detail["contentLastActiveAt"] == "2026-01-05T10:30:00.456"

    tags_detail = await use_case.query_detail("edge-featured-tags")
    assert tags_detail is not None
    # .123 → three digits too.
    assert tags_detail["publishedAt"] == "2026-01-05T09:00:00.123"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_millisecond_timestamps_omit_fraction(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("fixture-featured")
    assert detail is not None
    assert detail["publishedAt"] == "2026-01-02T10:00:00"
    assert detail["contentLastActiveAt"] == "2026-01-03T09:00:00"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_offline_row_yields_null_detail(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    assert await use_case.query_detail("edge-featured-offline") is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleted_row_yields_null_detail(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    assert await use_case.query_detail("edge-featured-deleted") is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blank_and_unknown_ids_yield_null_detail(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    assert await use_case.query_detail("") is None
    assert await use_case.query_detail("   ") is None
    assert await use_case.query_detail("no-such-featured") is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_run_session_still_reports_content_available(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-empty-history")
    assert detail is not None
    assert detail["contentAvailable"] is True
    assert detail["contentUnavailableReason"] is None
    history = detail["historyDetail"]
    assert history is not None
    assert history["runs"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deep_think_is_last_run_wins(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-millis")
    assert detail is not None
    history = detail["historyDetail"]
    assert history is not None
    # Runs are create_time ASC: edge-run-plan (plan_solve) then edge-run-empty
    # (entry_agent 'other'). Last run wins → deepThink False.
    assert [run["requestId"] for run in history["runs"]] == [
        "edge-run-plan",
        "edge-run-empty",
    ]
    assert history["deepThink"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_title_restored_from_new_dialogue_placeholder(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-millis")
    assert detail is not None
    history = detail["historyDetail"]
    assert history is not None
    # Session title is "新对话" → first non-blank run query, trimmed, ≤30 chars.
    assert history["title"] == "plan the thing"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_llm_run_has_context_usage_null_and_empty_frames(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-millis")
    assert detail is not None
    runs = detail["historyDetail"]["runs"]
    empty_run = next(r for r in runs if r["requestId"] == "edge-run-empty")
    assert empty_run["contextUsage"] is None
    assert empty_run["replayFrames"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_internal_call_kind_and_subagent_llm_are_skipped(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-deep")
    assert detail is not None
    frames = detail["historyDetail"]["runs"][0]["replayFrames"]
    text = str(frames)
    assert "must not appear" not in text
    assert "subagent must not appear" not in text
    assert "thinking about code" in text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_code_interpreter_tool_output_is_hydrated(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    detail = await use_case.query_detail("edge-featured-deep")
    assert detail is not None
    frames = detail["historyDetail"]["runs"][0]["replayFrames"]
    text = str(frames)
    # Rich output wins over llm_oberserve fallback.
    assert "printed 1" in text
    assert "print(1)" in text
    assert "prints one" in text
    assert "result.txt" in text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_usage_measured_vs_estimate(
    use_case: FeaturedConversationQueryUseCase,
) -> None:
    deep = await use_case.query_detail("edge-featured-deep")
    assert deep is not None
    usage = deep["historyDetail"]["runs"][0]["contextUsage"]
    # prompt_tokens = 0 → estimate path with est_total_tokens = 40.
    assert usage["source"] == "estimate"
    assert usage["used"] == 40
    assert usage["sys"] == 10
    assert usage["tools"] == 10
    assert usage["history"] == 20

    fixture = await use_case.query_detail("fixture-featured")
    assert fixture is not None
    fixture_usage = fixture["historyDetail"]["runs"][0]["contextUsage"]
    assert fixture_usage["source"] == "measured"
    assert fixture_usage["used"] == 100
    assert fixture_usage["promptTokens"] == 100
    assert fixture_usage["completionTokens"] == 50
