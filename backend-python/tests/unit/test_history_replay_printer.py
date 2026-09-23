from __future__ import annotations

from datetime import datetime

from reactor_backend.domain.history_replay import (
    HistoryQueryPorts,
    HistoryReplayPrinter,
    abbreviate_session_title,
    is_meaningful_session_title,
    query_conversation_history,
    resolve_history_mode_snapshot,
    resolve_session_status,
    resolve_status_label,
    restore_session_title,
)
from reactor_backend.domain.ledger_types import (
    DialogueRunView,
    DialogueSessionView,
    LlmInvocationView,
)
from reactor_backend.domain.replay_projector import ReplayProjector


def test_status_labels_cover_all_codes() -> None:
    assert resolve_status_label(None) == "RUNNING"
    assert resolve_status_label(0) == "RUNNING"
    assert resolve_status_label(1) == "SUCCESS"
    assert resolve_status_label(2) == "FAILED"
    assert resolve_status_label(3) == "TIMEOUT"
    assert resolve_status_label(4) == "STOPPED"
    assert resolve_status_label(5) == "WAITING_INPUT"
    assert resolve_status_label(99) == "RUNNING"  # unknown → RUNNING


def test_title_restore_rules() -> None:
    assert not is_meaningful_session_title(None)
    assert not is_meaningful_session_title("")
    assert not is_meaningful_session_title("   ")
    assert not is_meaningful_session_title("新对话")
    assert not is_meaningful_session_title("  新对话  ")
    assert is_meaningful_session_title("real title")
    assert is_meaningful_session_title("新对话x")  # only exact match is placeholder


def test_abbreviate_truncates_to_30() -> None:
    assert abbreviate_session_title("short") == "short"
    assert abbreviate_session_title("  padded  ") == "padded"
    long = "x" * 50
    assert abbreviate_session_title(long) == "x" * 30
    assert abbreviate_session_title("x" * 30) == "x" * 30


def test_restore_session_title_picks_first_non_blank_query() -> None:
    session = DialogueSessionView(session_id="s1", title="新对话")
    runs = [
        DialogueRunView(request_id="r1", query_text="   "),
        DialogueRunView(request_id="r2", query_text="  actual first query  "),
        DialogueRunView(request_id="r3", query_text="later"),
    ]
    restore_session_title(session, runs)
    assert session.title == "actual first query"


def test_restore_session_title_leaves_meaningful_title() -> None:
    session = DialogueSessionView(session_id="s1", title="kept")
    restore_session_title(session, [DialogueRunView(query_text="q")])
    assert session.title == "kept"


def test_deep_think_last_run_wins() -> None:
    # blank-requestId runs do not update the snapshot
    assert resolve_history_mode_snapshot(None) is False
    assert resolve_history_mode_snapshot(DialogueRunView(entry_agent="react")) is False
    assert resolve_history_mode_snapshot(DialogueRunView(entry_agent="plan_solve")) is True
    assert resolve_history_mode_snapshot(DialogueRunView(entry_agent="other")) is False
    assert resolve_history_mode_snapshot(DialogueRunView(entry_agent="  plan_solve  ")) is True


def test_session_status_prefers_session_status() -> None:
    session = DialogueSessionView(status=4)
    runs = [DialogueRunView(status=1)]
    assert resolve_session_status(session, runs) == 4


def test_session_status_falls_back_to_last_run() -> None:
    session = DialogueSessionView(status=None)
    runs = [DialogueRunView(status=1), DialogueRunView(status=2)]
    assert resolve_session_status(session, runs) == 2


def test_session_status_defaults_to_running() -> None:
    assert resolve_session_status(DialogueSessionView(status=None), []) == 0
    assert (
        resolve_session_status(DialogueSessionView(status=None), [DialogueRunView(status=None)])
        == 0
    )


def test_printer_no_op_when_result_event_present() -> None:
    # a frame whose eventData.resultMap.messageType is "result" → no fallback
    frames = [
        {
            "resultMap": {
                "eventData": {"resultMap": {"messageType": "result"}},
            }
        }
    ]
    run = DialogueRunView(request_id="r1", final_summary_text="s")
    assert HistoryReplayPrinter().ensure_readable_conclusion(run, frames) == frames


def test_printer_no_op_when_summary_blank() -> None:
    run = DialogueRunView(request_id="r1", final_summary_text="  ")
    assert HistoryReplayPrinter().ensure_readable_conclusion(run, []) == []


def test_printer_appends_fallback_with_task_id_suffix() -> None:
    run = DialogueRunView(request_id="req-9", final_summary_text="the end")
    frames = HistoryReplayPrinter().ensure_readable_conclusion(run, [])
    assert len(frames) == 1
    event = frames[0]["resultMap"]["eventData"]
    # HistoryReplayPrinter's frame uses taskId = requestId + "-summary", taskOrder 1
    assert event["taskId"] == "req-9-summary"
    assert event["taskOrder"] == 1
    assert event["messageId"] == "req-9-summary"
    # and it DOES set response/responseAll (unlike the projector's builder frames)
    assert frames[0]["response"] == "the end"
    assert frames[0]["responseAll"] == "the end"
    assert event["resultMap"]["messageType"] == "result"
    assert event["resultMap"]["taskSummary"] == "the end"
    assert event["resultMap"]["result"] == "the end"


def test_printer_sees_task_summary_as_conclusion() -> None:
    frames = [
        {"resultMap": {"eventData": {"resultMap": {"messageType": "task_summary"}}}}
    ]
    run = DialogueRunView(request_id="r", final_summary_text="s")
    assert HistoryReplayPrinter().ensure_readable_conclusion(run, frames) == frames


def test_query_conversation_history_null_when_session_missing() -> None:
    ports = HistoryQueryPorts(
        query_session=lambda _sid: None,
        query_session_runs=lambda _sid: [],
        query_run_detail=lambda _rid: None,
    )
    assert query_conversation_history("s1", ports, ReplayProjector()) is None
    assert query_conversation_history(None, ports, ReplayProjector()) is None
    assert query_conversation_history("  ", ports, ReplayProjector()) is None


def test_query_conversation_history_zero_runs_still_available() -> None:
    session = DialogueSessionView(
        session_id="s1",
        title="Fixture session two",
        status=1,
        run_count=0,
        finished_run_count=0,
        failed_run_count=0,
        started_at=datetime(2026, 1, 1, 8, 0, 0),
        last_active_at=datetime(2026, 1, 3, 8, 0, 0),
    )
    ports = HistoryQueryPorts(
        query_session=lambda _sid: session,
        query_session_runs=lambda _sid: [],
        query_run_detail=lambda _rid: None,
    )
    payload = query_conversation_history("s1", ports, ReplayProjector())
    assert payload is not None
    assert payload["runCount"] == 0
    assert payload["runs"] == []
    assert payload["status"] == "SUCCESS"
    assert payload["deepThink"] is False
    assert list(payload.keys()) == [
        "sessionId",
        "title",
        "status",
        "deepThink",
        "runCount",
        "finishedRunCount",
        "failedRunCount",
        "startedAt",
        "lastActiveAt",
        "runs",
    ]


def test_query_conversation_history_run_payload_shape() -> None:
    session = DialogueSessionView(session_id="s1", title="t", status=1, run_count=1)
    run = DialogueRunView(
        request_id="r1",
        status=1,
        query_text="q",
        final_summary_text="s",
        started_at=datetime(2026, 1, 1, 9, 0, 0),
        finished_at=datetime(2026, 1, 1, 9, 0, 5),
    )
    llm = LlmInvocationView(
        id=1,
        run_id=101,
        invocation_seq=1,
        agent_name="react",
        call_kind="ask",
        response_text="text",
        tool_call_count=0,
        prompt_tokens=100,
        completion_tokens=50,
        finished_at=datetime(2026, 1, 1, 9, 0, 2),
    )
    from reactor_backend.domain.ledger_types import ExecutionRunDetail

    detail = ExecutionRunDetail(run=run, llm_invocations=[llm], tool_invocations=[], artifacts=[])
    ports = HistoryQueryPorts(
        query_session=lambda _sid: session,
        query_session_runs=lambda _sid: [run],
        query_run_detail=lambda _rid: detail,
    )
    payload = query_conversation_history("s1", ports, ReplayProjector())
    assert payload is not None
    assert len(payload["runs"]) == 1
    run_payload = payload["runs"][0]
    assert list(run_payload.keys()) == [
        "requestId",
        "status",
        "queryText",
        "finalSummaryText",
        "startedAt",
        "finishedAt",
        "contextUsage",
        "replayFrames",
    ]
    assert run_payload["status"] == "SUCCESS"
    assert run_payload["contextUsage"]["used"] == 100
    assert len(run_payload["replayFrames"]) == 2  # tool_thought + summary fallback


def test_blank_request_id_runs_are_skipped() -> None:
    session = DialogueSessionView(session_id="s1", title="t", status=1)
    blank_run = DialogueRunView(request_id="  ", entry_agent="plan_solve")
    good_run = DialogueRunView(request_id="r1", status=1, entry_agent="react")
    ports = HistoryQueryPorts(
        query_session=lambda _sid: session,
        query_session_runs=lambda _sid: [blank_run, good_run],
        query_run_detail=lambda _rid: None,
    )
    payload = query_conversation_history("s1", ports, ReplayProjector())
    assert payload is not None
    assert len(payload["runs"]) == 1
    # deepThink is last-run-wins over the runs that actually contribute (blank skipped)
    assert payload["deepThink"] is False
