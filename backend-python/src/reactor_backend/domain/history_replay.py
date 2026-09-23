"""Conversation history assembly and the readable-conclusion printer.

Ported from ``ConversationHistoryReplayService`` + ``HistoryReplayPrinter`` +
``AgentFeaturedConversationController.resolveStatusLabel``.

``HistoryReplayPrinter``'s fallback frame is NOT the one in the contract golden:
golden frame 2 comes from ``ReplayProjector.appendRunSummaryFallback``. The
printer is a no-op when any projected frame already carries a
``result``/``task_summary`` inner messageType — including subagent ones (unlike
the projector's ``hasResultEvent``). Both behaviours are reproduced.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from reactor_backend.domain import execution_ledger_constants as consts
from reactor_backend.domain.context_usage import resolve_context_usage
from reactor_backend.domain.ledger_types import (
    DialogueRunView,
    DialogueSessionView,
    ExecutionRunDetail,
    ProjectedReplayEvent,
    ReplayFactBundle,
)
from reactor_backend.domain.summary_resolver import resolve as resolve_summary
from reactor_backend.domain.time_format import format_local_datetime
from reactor_backend.domain.tool_projectors import build_artifact_refs


def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _is_not_blank(value: str | None) -> bool:
    return not _is_blank(value)


def resolve_status_label(status: int | None) -> str:
    """English status labels; unknown/null/0 → ``RUNNING``."""
    normalized = consts.STATUS_RUNNING if status is None else status
    if normalized == consts.STATUS_SUCCESS:
        return "SUCCESS"
    if normalized == consts.STATUS_FAILED:
        return "FAILED"
    if normalized == consts.STATUS_TIMEOUT:
        return "TIMEOUT"
    if normalized == consts.STATUS_STOPPED:
        return "STOPPED"
    if normalized == consts.STATUS_WAITING_INPUT:
        return "WAITING_INPUT"
    return "RUNNING"


def is_meaningful_session_title(title: str | None) -> bool:
    return _is_not_blank(title) and (title or "").strip() != "新对话"


def abbreviate_session_title(query_text: str) -> str:
    normalized = query_text.strip()
    return normalized if len(normalized) <= 30 else normalized[:30]


def restore_session_title(
    session: DialogueSessionView,
    runs: Sequence[DialogueRunView],
) -> DialogueSessionView:
    """Blank or ``"新对话"`` titles are replaced by the first non-blank run query."""
    if session is None or is_meaningful_session_title(session.title):
        return session
    first_query = _first_non_blank_query(runs)
    if _is_not_blank(first_query):
        session.title = abbreviate_session_title(first_query or "")
        if _is_blank(session.latest_query_text):
            session.latest_query_text = first_query
    return session


def _first_non_blank_query(runs: Sequence[DialogueRunView]) -> str | None:
    for run in runs or []:
        if run is not None and _is_not_blank(run.query_text):
            return run.query_text
    return None


def resolve_session_status(
    session: DialogueSessionView, runs: Sequence[DialogueRunView]
) -> int:
    if session is not None and session.status is not None:
        return session.status
    if not runs:
        return consts.STATUS_RUNNING
    latest = runs[-1]
    if latest is None or latest.status is None:
        return consts.STATUS_RUNNING
    return latest.status


def resolve_history_mode_snapshot(run: DialogueRunView | None) -> bool:
    """deepThink flag. Last-run-wins is applied by the caller (see below)."""
    if run is None:
        return False
    entry_agent = (run.entry_agent or "").strip()
    if entry_agent == consts.ENTRY_AGENT_PLAN_SOLVE:
        return True
    return False


class HistoryReplayPrinter:
    def ensure_readable_conclusion(
        self,
        run: DialogueRunView,
        frames: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = list(frames or [])
        if self._has_readable_conclusion(result) or run is None or _is_blank(
            run.final_summary_text
        ):
            return result
        result.append(self._build_fallback_conclusion(run))
        return result

    @staticmethod
    def _has_readable_conclusion(frames: Sequence[dict[str, Any]]) -> bool:
        """Looks at ``eventData.resultMap.messageType`` — does NOT exclude subagent."""
        for frame in frames or []:
            if not isinstance(frame, dict):
                continue
            result_map = frame.get("resultMap")
            if not isinstance(result_map, dict):
                continue
            event_data = result_map.get("eventData")
            if not isinstance(event_data, dict):
                continue
            nested = event_data.get("resultMap")
            if not isinstance(nested, dict):
                continue
            if nested.get("messageType") in ("result", "task_summary"):
                return True
        return False

    def _build_fallback_conclusion(self, run: DialogueRunView) -> dict[str, Any]:
        resolved = resolve_summary(run.final_summary_text)
        nested: dict[str, Any] = {
            "messageType": "result",
            "isFinal": True,
            "taskSummary": resolved.summary_text,
            "result": resolved.summary_text,
        }
        if resolved.file_list:
            nested["fileList"] = resolved.file_list

        event_data: dict[str, Any] = {
            "taskId": f"{run.request_id}-summary",
            "taskOrder": 1,
            "messageType": "task",
            "messageOrder": 1,
            "messageId": f"{run.request_id}-summary",
        }
        if resolved.artifact_refs:
            event_data["artifactRefs"] = resolved.artifact_refs
        event_data["resultMap"] = nested

        result_map: dict[str, Any] = {
            "agentType": "history",
            "multiAgent": {},
            "eventData": event_data,
        }
        return {
            "status": "success",
            "response": resolved.summary_text,
            "responseAll": resolved.summary_text,
            "finished": True,
            "useTimes": 0,
            "useTokens": 0,
            "resultMap": result_map,
            "responseType": None,
            "traceId": None,
            "reqId": run.request_id,
            "encrypted": False,
            "query": None,
            "messages": None,
            "packageType": None,
            "errorMsg": None,
            "eventSeq": 0,
            "retryMs": None,
        }


def build_history_detail_payload(
    session: DialogueSessionView,
    runs: Sequence[DialogueRunView],
    run_details: Sequence[dict[str, Any]],
    deep_think: bool,
) -> dict[str, Any]:
    """``ConversationHistoryDetailRespVO`` JSON shape — field order is contract."""
    return {
        "sessionId": session.session_id,
        "title": session.title,
        "status": resolve_status_label(resolve_session_status(session, runs)),
        "deepThink": deep_think,
        "runCount": session.run_count,
        "finishedRunCount": session.finished_run_count,
        "failedRunCount": session.failed_run_count,
        "startedAt": format_local_datetime(session.started_at),
        "lastActiveAt": format_local_datetime(session.last_active_at),
        "runs": [dict(item) for item in run_details],
    }


def build_run_detail_payload(
    run: DialogueRunView,
    context_usage: dict[str, Any] | None,
    replay_frames: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """``RunDetailRespVO`` JSON shape — field order is contract."""
    return {
        "requestId": run.request_id,
        "status": resolve_status_label(run.status),
        "queryText": run.query_text,
        "finalSummaryText": run.final_summary_text,
        "startedAt": format_local_datetime(run.started_at),
        "finishedAt": format_local_datetime(run.finished_at),
        "contextUsage": dict(context_usage) if context_usage is not None else None,
        "replayFrames": [dict(frame) for frame in replay_frames],
    }


@dataclass
class HistoryQueryPorts:
    query_session: Callable[[str], DialogueSessionView | None]
    query_session_runs: Callable[[str], list[DialogueRunView]]
    query_run_detail: Callable[[str], ExecutionRunDetail | None]
    max_input_tokens: Callable[[str | None], int] | None = None


def query_conversation_history(
    session_id: str | None,
    ports: HistoryQueryPorts,
    projector: Any,
    printer: HistoryReplayPrinter | None = None,
) -> dict[str, Any] | None:
    """Port of ``ConversationHistoryReplayService.queryConversationHistory``."""
    if _is_blank(session_id):
        return None
    session = ports.query_session(session_id or "")
    if session is None:
        return None

    runs = ports.query_session_runs(session_id or "")
    run_payloads: list[dict[str, Any]] = []
    deep_think = False
    resolved_printer = printer if printer is not None else HistoryReplayPrinter()

    for run in runs or []:
        if run is None or _is_blank(run.request_id):
            continue
        run_detail = ports.query_run_detail(run.request_id or "")
        effective_run = run if run_detail is None else run_detail.run
        bundle = ReplayFactBundle(
            run=effective_run,
            llm_invocations=[] if run_detail is None else list(run_detail.llm_invocations),
            tool_invocations=[]
            if run_detail is None
            else list(run_detail.tool_invocations),
            artifacts=[] if run_detail is None else list(run_detail.artifacts),
        )
        replay_frames: list[dict[str, Any]] = (
            projector.project_history_frames(bundle) if projector is not None else []
        )
        # last-run-wins: reassigned on every iteration, matching the Java loop
        deep_think = resolve_history_mode_snapshot(run)
        frames = resolved_printer.ensure_readable_conclusion(run, replay_frames)
        run_payloads.append(
            build_run_detail_payload(
                run,
                resolve_context_usage(
                    [] if run_detail is None else run_detail.llm_invocations,
                    ports.max_input_tokens,
                ),
                frames,
            )
        )

    restore_session_title(session, runs or [])
    return build_history_detail_payload(session, runs or [], run_payloads, deep_think)


__all__ = [
    "HistoryQueryPorts",
    "HistoryReplayPrinter",
    "abbreviate_session_title",
    "build_history_detail_payload",
    "build_run_detail_payload",
    "is_meaningful_session_title",
    "query_conversation_history",
    "resolve_history_mode_snapshot",
    "resolve_session_status",
    "resolve_status_label",
    "restore_session_title",
    "build_artifact_refs",
    "ProjectedReplayEvent",
]
