"""Featured conversations public query use case.

Ported from ``FeaturedConversationPublicQueryApplicationService``. Ports keep the
domain layer free of SQLAlchemy/FastAPI; infrastructure implements them.

The history assembly is synchronous (pure CPU over already-loaded rows); the async
boundary is the repository fetch, which happens before :func:`query_conversation_history`
is invoked through an in-memory cache of the loaded facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from reactor_backend.domain.featured_conversation import (
    FeaturedConversationRow,
    PageResult,
    is_blank,
    is_online,
    normalize_limit,
    normalize_page_no,
    normalize_page_size,
    page_offset,
    to_card_payload,
    to_detail_payload,
)
from reactor_backend.domain.history_replay import (
    HistoryQueryPorts,
    query_conversation_history,
)
from reactor_backend.domain.ledger_types import (
    DialogueRunView,
    DialogueSessionView,
    ExecutionRunDetail,
)


class FeaturedConversationReader(Protocol):
    async def query_by_featured_id(
        self, featured_id: str
    ) -> FeaturedConversationRow | None: ...

    async def query_online_list(
        self, offset: int, limit: int
    ) -> Sequence[FeaturedConversationRow]: ...

    async def count_online(self) -> int: ...


class ExecutionLedgerReader(Protocol):
    async def query_session(self, session_id: str) -> DialogueSessionView | None: ...

    async def query_session_runs(self, session_id: str) -> Sequence[DialogueRunView]: ...

    async def query_run_detail(self, request_id: str) -> ExecutionRunDetail | None: ...


class ModelWindowResolver(Protocol):
    def max_input_tokens(self, model_name: str | None) -> int: ...


class FeaturedConversationQueryUseCase:
    def __init__(
        self,
        featured_reader: FeaturedConversationReader,
        ledger_reader: ExecutionLedgerReader,
        model_window: ModelWindowResolver,
        history_projector: Any,
    ) -> None:
        self._featured_reader = featured_reader
        self._ledger_reader = ledger_reader
        self._model_window = model_window
        self._history_projector = history_projector

    async def query_home_cards(self, limit: int) -> list[dict[str, Any]]:
        normalized = normalize_limit(limit)
        rows = await self._featured_reader.query_online_list(0, normalized)
        return [await self._to_card(row) for row in rows]

    async def query_public_list(self, page_no: int, page_size: int) -> dict[str, Any]:
        normalized_page = normalize_page_no(page_no)
        normalized_size = normalize_page_size(page_size)
        offset = page_offset(normalized_page, normalized_size)
        total = await self._featured_reader.count_online()
        rows = await self._featured_reader.query_online_list(offset, normalized_size)
        cards = [await self._to_card(row) for row in rows]
        return PageResult(total=total, list=cards).to_payload()

    async def query_detail(self, featured_id: str | None) -> dict[str, Any] | None:
        if is_blank(featured_id):
            return None
        row = await self._featured_reader.query_by_featured_id(featured_id or "")
        if row is None or not is_online(row.status):
            return None

        content_last_active_at = await self._resolve_content_last_active_at(row.session_id)
        history_detail = await self._load_history(row.session_id)
        return to_detail_payload(row, content_last_active_at, history_detail)

    async def _to_card(self, row: FeaturedConversationRow) -> dict[str, Any]:
        content_last_active_at = await self._resolve_content_last_active_at(row.session_id)
        return to_card_payload(row, content_last_active_at)

    async def _resolve_content_last_active_at(
        self, session_id: str | None
    ) -> datetime | None:
        if is_blank(session_id):
            return None
        session = await self._ledger_reader.query_session(session_id or "")
        return None if session is None else session.last_active_at

    async def _load_history(self, session_id: str | None) -> dict[str, Any] | None:
        if is_blank(session_id):
            return None
        sid = session_id or ""
        session = await self._ledger_reader.query_session(sid)
        if session is None:
            return None
        runs = list(await self._ledger_reader.query_session_runs(sid))
        run_details: dict[str, ExecutionRunDetail] = {}
        for run in runs:
            if run is None or is_blank(run.request_id):
                continue
            detail = await self._ledger_reader.query_run_detail(run.request_id or "")
            if detail is not None:
                run_details[run.request_id or ""] = detail

        cache = _FactCache(session=session, runs=runs, run_details=run_details)
        await self._prefill_model_windows(run_details)
        ports = HistoryQueryPorts(
            query_session=cache.query_session,
            query_session_runs=cache.query_session_runs,
            query_run_detail=cache.query_run_detail,
            max_input_tokens=self._model_window.max_input_tokens,
        )
        return query_conversation_history(sid, ports, self._history_projector)

    async def _prefill_model_windows(
        self, run_details: dict[str, ExecutionRunDetail]
    ) -> None:
        """Warm :class:`ModelWindowResolver` caches before the sync assembly runs.

        Optional so pure-Python fakes that only implement ``max_input_tokens``
        keep working; a resolver without ``prefill`` just uses its own default.
        """
        prefill = getattr(self._model_window, "prefill", None)
        if prefill is None:
            return
        names: list[str | None] = []
        for detail in run_details.values():
            for invocation in detail.llm_invocations:
                names.append(invocation.model_name)
        await prefill(names)


class _FactCache:
    def __init__(
        self,
        session: DialogueSessionView,
        runs: Sequence[DialogueRunView],
        run_details: dict[str, ExecutionRunDetail],
    ) -> None:
        self._session = session
        self._runs = list(runs)
        self._run_details = run_details

    def query_session(self, session_id: str) -> DialogueSessionView | None:
        return self._session

    def query_session_runs(self, session_id: str) -> list[DialogueRunView]:
        return list(self._runs)

    def query_run_detail(self, request_id: str) -> ExecutionRunDetail | None:
        return self._run_details.get(request_id)
