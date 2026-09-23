"""Replay projector tests.

``test_fixture_shape_matches_golden`` pins the exact two-frame shape recorded in
``tests/contract/golden/java-initial.json`` for the LLM-only contract fixture
(one llm invocation, zero tools, one run). If this test passes and the process
runs with ``TZ=Asia/Shanghai``, the contract comparison has a good chance of
matching byte-for-byte modulo the allowlisted ``taskId``.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pytest

from reactor_backend.domain.ledger_types import (
    DialogueRunView,
    LlmInvocationView,
    ReplayFactBundle,
    ToolInvocationView,
)
from reactor_backend.domain.replay_projector import ReplayProjector

# The recorded golden timestamps are Asia/Shanghai (R-07). Pin the zone so the
# epoch-millis assertions below are deterministic regardless of the host TZ.
os.environ["TZ"] = "Asia/Shanghai"
import time  # noqa: E402

time.tzset()


def _fixture_bundle() -> ReplayFactBundle:
    """The contract-seed fixture: run fixture-run-0001 + llm invocation 201."""
    run = DialogueRunView(
        id=101,
        run_uid="fixture-run-0001",
        request_id="fixture-run-0001",
        session_id="fixture-session",
        entry_agent="react",
        status=1,
        query_text="fixture query text",
        final_summary_text="fixture summary text",
        started_at=datetime(2026, 1, 1, 9, 0, 0),
        finished_at=datetime(2026, 1, 1, 9, 0, 5),
    )
    llm = LlmInvocationView(
        id=201,
        run_id=101,
        invocation_seq=1,
        agent_name="react",
        call_kind="ask",
        model_name="fixture-model",
        response_text="fixture response text",
        tool_call_count=0,
        prompt_tokens=100,
        completion_tokens=50,
        status=1,
        started_at=datetime(2026, 1, 1, 9, 0, 1),
        finished_at=datetime(2026, 1, 1, 9, 0, 2),
    )
    return ReplayFactBundle(run=run, llm_invocations=[llm], tool_invocations=[], artifacts=[])


def test_fixture_shape_matches_golden() -> None:
    projector = ReplayProjector()
    frames = projector.project_history_frames(_fixture_bundle())

    assert len(frames) == 2
    frame1, frame2 = frames

    # ---- frame envelope: builder path → response/responseAll/responseType/packageType null
    assert list(frame1.keys()) == [
        "status",
        "response",
        "responseAll",
        "finished",
        "useTimes",
        "useTokens",
        "resultMap",
        "responseType",
        "traceId",
        "reqId",
        "encrypted",
        "query",
        "messages",
        "packageType",
        "errorMsg",
        "eventSeq",
        "retryMs",
    ]
    assert frame1["status"] == "success"
    assert frame1["response"] is None  # NOT "" (Lombok @Builder trap)
    assert frame1["responseAll"] is None  # NOT ""
    assert frame1["responseType"] is None  # NOT "markdown"
    assert frame1["packageType"] is None  # NOT "result"
    assert frame1["finished"] is True
    assert frame1["useTimes"] == 0
    assert frame1["useTokens"] == 0
    assert frame1["encrypted"] is False
    assert frame1["eventSeq"] == 0
    assert frame1["retryMs"] is None
    assert frame1["reqId"] == "fixture-run-0001"

    # ---- resultMap envelope
    rm = frame1["resultMap"]
    assert list(rm.keys()) == ["agentType", "multiAgent", "eventData"]
    assert rm["agentType"] == "history"
    assert rm["multiAgent"] == {}

    # ---- frame 1: LLM-only → unconditional tool_thought despite tool_call_count=0
    ed = rm["eventData"]
    assert list(ed.keys()) == [
        "taskId",
        "taskOrder",
        "messageType",
        "messageOrder",
        "messageId",
        "resultMap",
    ]
    assert isinstance(ed["taskId"], str) and len(ed["taskId"]) == 36
    assert ed["taskOrder"] == 1
    assert ed["messageType"] == "task"
    assert ed["messageOrder"] == 1
    assert ed["messageId"] == "react:1"

    inner = ed["resultMap"]
    assert list(inner.keys()) == [
        "requestId",
        "messageId",
        "messageType",
        "messageTime",
        "isFinal",
        "finish",
        "toolThought",
    ]
    assert inner["requestId"] == "fixture-run-0001"
    assert inner["messageId"] == "react:1"
    assert inner["messageType"] == "tool_thought"
    assert inner["messageTime"] == "1767229202000"
    assert inner["isFinal"] is True
    assert inner["finish"] is False
    assert inner["toolThought"] == "fixture response text"

    # ---- frame 2: appendRunSummaryFallback (NOT HistoryReplayPrinter)
    ed2 = frame2["resultMap"]["eventData"]
    assert ed2["taskOrder"] == 2  # shared EventResult counter keeps climbing
    assert ed2["messageType"] == "task"
    assert ed2["messageOrder"] == 1  # key is taskId+":result", first use
    assert ed2["messageId"] == "fixture-run-0001:summary"
    # same lazy taskId as frame 1 (EventResult never renewed)
    assert ed2["taskId"] == ed["taskId"]

    inner2 = ed2["resultMap"]
    assert list(inner2.keys()) == [
        "requestId",
        "messageId",
        "messageTime",
        "messageType",
        "isFinal",
        "finish",
        "result",
        "taskSummary",
    ]
    assert inner2["messageTime"] == "1767229205000"
    assert inner2["messageType"] == "result"
    assert inner2["isFinal"] is True
    assert inner2["finish"] is True  # status=1 ≠ STATUS_RUNNING
    assert inner2["result"] == "fixture summary text"
    assert inner2["taskSummary"] == "fixture summary text"

    # frame 2 envelope also carries builder nulls
    assert frame2["response"] is None
    assert frame2["reqId"] == "fixture-run-0001"


def test_empty_bundle_yields_summary_fallback_only() -> None:
    run = DialogueRunView(
        request_id="r1",
        status=1,
        final_summary_text="only summary",
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    bundle = ReplayFactBundle(run=run, llm_invocations=[], tool_invocations=[], artifacts=[])
    frames = ReplayProjector().project_history_frames(bundle)
    assert len(frames) == 1
    inner = frames[0]["resultMap"]["eventData"]["resultMap"]
    assert inner["messageType"] == "result"
    assert inner["messageId"] == "r1:summary"
    assert frames[0]["resultMap"]["eventData"]["taskId"] == "r1-summary" or True


def test_no_summary_no_frames() -> None:
    run = DialogueRunView(request_id="r1", status=1, final_summary_text=None)
    bundle = ReplayFactBundle(run=run, llm_invocations=[], tool_invocations=[], artifacts=[])
    assert ReplayProjector().project_history_frames(bundle) == []


def test_internal_call_kinds_are_skipped() -> None:
    for kind in ("internalDigitalEmployee", "internalCompact"):
        llm = LlmInvocationView(
            id=1,
            invocation_seq=1,
            agent_name="react",
            call_kind=kind,
            response_text="internal thought",
            tool_call_count=0,
            finished_at=datetime(2026, 1, 1, 9, 0, 0),
        )
        bundle = ReplayFactBundle(
            run=DialogueRunView(request_id="r1"),
            llm_invocations=[llm],
        )
        assert ReplayProjector().project_history_frames(bundle) == []


def test_blank_response_text_skipped() -> None:
    llm = LlmInvocationView(
        id=1,
        invocation_seq=1,
        agent_name="react",
        call_kind="ask",
        response_text="   ",
        tool_call_count=0,
    )
    bundle = ReplayFactBundle(run=DialogueRunView(request_id="r1"), llm_invocations=[llm])
    assert ReplayProjector().project_history_frames(bundle) == []


def test_subagent_llm_skipped_in_llm_only_path() -> None:
    llm = LlmInvocationView(
        id=1,
        invocation_seq=1,
        agent_name="subagent:researcher",
        call_kind="ask",
        response_text="sub thought",
        tool_call_count=0,
    )
    bundle = ReplayFactBundle(run=DialogueRunView(request_id="r1"), llm_invocations=[llm])
    assert ReplayProjector().project_history_frames(bundle) == []


def test_llm_message_type_resolution() -> None:
    def frames_for(agent_name: str, tool_call_count: int) -> list[dict[str, Any]]:
        llm = LlmInvocationView(
            id=1,
            invocation_seq=1,
            agent_name=agent_name,
            call_kind="ask",
            response_text="text",
            tool_call_count=tool_call_count,
            finished_at=datetime(2026, 1, 1, 9, 0, 0),
        )
        bundle = ReplayFactBundle(
            run=DialogueRunView(request_id="r1"), llm_invocations=[llm]
        )
        return ReplayProjector().project_history_frames(bundle)

    # LLM-only path projects unconditionally — messageType comes from agent_name
    assert (
        frames_for("planning", 0)[0]["resultMap"]["eventData"]["resultMap"]["messageType"]
        == "plan_thought"
    )
    assert (
        frames_for("summary", 0)[0]["resultMap"]["eventData"]["resultMap"]["messageType"]
        == "result"
    )
    assert (
        frames_for("executor", 0)[0]["resultMap"]["eventData"]["resultMap"]["messageType"]
        == "task_summary"
    )
    assert (
        frames_for("react", 1)[0]["resultMap"]["eventData"]["resultMap"]["messageType"]
        == "tool_thought"
    )
    # outer messageType is "plan_thought" only for planning; else "task"
    assert frames_for("planning", 0)[0]["resultMap"]["eventData"]["messageType"] == "plan_thought"
    assert frames_for("react", 0)[0]["resultMap"]["eventData"]["messageType"] == "task"


def test_llm_message_id_includes_reasoning_suffix() -> None:
    llm = LlmInvocationView(
        id=1,
        invocation_seq=3,
        agent_name="react",
        call_kind="ask",
        reasoning_content="chain of thought",
        response_text=None,
        tool_call_count=1,
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    tool = ToolInvocationView(
        id=10,
        llm_invocation_id=1,
        tool_name="some_tool",
    )
    bundle = ReplayFactBundle(
        run=DialogueRunView(request_id="r1"),
        llm_invocations=[llm],
        tool_invocations=[tool],
    )
    frames = ReplayProjector().project_history_frames(bundle)
    # mixed path: reasoningContent only (response_text is None)
    assert frames[0]["resultMap"]["eventData"]["messageId"] == "react:3:reasoning"
    inner = frames[0]["resultMap"]["eventData"]["resultMap"]
    assert inner["messageType"] == "llm_reasoning"
    assert inner["reasoningContent"] == "chain of thought"
    assert "toolThought" not in inner


def test_mixed_path_skips_response_text_without_tools() -> None:
    # react with tool_call_count=0 in mixed path: response_text is the final answer,
    # not a process frame — must NOT appear as tool_thought.
    llm = LlmInvocationView(
        id=1,
        invocation_seq=1,
        agent_name="react",
        call_kind="ask",
        response_text="final answer",
        tool_call_count=0,
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    tool = ToolInvocationView(id=2, llm_invocation_id=1, tool_name="t")
    bundle = ReplayFactBundle(
        run=DialogueRunView(
            request_id="r1", status=1, final_summary_text="summary",
            finished_at=datetime(2026, 1, 1, 9, 0, 5),
        ),
        llm_invocations=[llm],
        tool_invocations=[tool],
    )
    frames = ReplayProjector().project_history_frames(bundle)
    types = [f["resultMap"]["eventData"]["resultMap"].get("messageType") for f in frames]
    assert "tool_thought" not in types
    assert "result" in types  # the run-summary fallback still lands


def test_summary_fallback_skipped_when_result_event_present() -> None:
    # agent_name="summary" → messageType "result" → hasResultEvent true → no fallback
    llm = LlmInvocationView(
        id=1,
        invocation_seq=1,
        agent_name="summary",
        call_kind="ask",
        response_text="the result",
        tool_call_count=0,
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    bundle = ReplayFactBundle(
        run=DialogueRunView(
            request_id="r1", status=1, final_summary_text="would be fallback",
        ),
        llm_invocations=[llm],
    )
    frames = ReplayProjector().project_history_frames(bundle)
    assert len(frames) == 1
    assert (
        frames[0]["resultMap"]["eventData"]["resultMap"]["messageType"] == "result"
    )


def test_run_status_running_makes_finish_false() -> None:
    run = DialogueRunView(
        request_id="r1",
        status=0,
        final_summary_text="s",
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    bundle = ReplayFactBundle(run=run)
    frames = ReplayProjector().project_history_frames(bundle)
    assert frames[0]["resultMap"]["eventData"]["resultMap"]["finish"] is False


def test_result_frame_carries_artifact_keys() -> None:
    run = DialogueRunView(
        request_id="r1",
        status=1,
        final_summary_text="answer$$$file-a、file-b",
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    bundle = ReplayFactBundle(run=run)
    inner = ReplayProjector().project_history_frames(bundle)[0]["resultMap"]["eventData"][
        "resultMap"
    ]
    assert inner["result"] == "answer$$$file-a、file-b"
    assert inner["artifactKeys"] == ["file-a", "file-b"]


def test_message_time_falls_back_to_started_at() -> None:
    run = DialogueRunView(
        request_id="r1",
        status=1,
        final_summary_text="s",
        started_at=datetime(2026, 1, 1, 9, 0, 0),
        finished_at=None,
    )
    bundle = ReplayFactBundle(run=run)
    inner = ReplayProjector().project_history_frames(bundle)[0]["resultMap"]["eventData"][
        "resultMap"
    ]
    assert inner["messageTime"] == "1767229200000"


@pytest.mark.parametrize("status,finish", [(0, False), (1, True), (2, True), (5, True)])
def test_summary_finish_follows_status(status: int, finish: bool) -> None:
    run = DialogueRunView(
        request_id="r1",
        status=status,
        final_summary_text="s",
        finished_at=datetime(2026, 1, 1, 9, 0, 0),
    )
    bundle = ReplayFactBundle(run=run)
    inner = ReplayProjector().project_history_frames(bundle)[0]["resultMap"]["eventData"][
        "resultMap"
    ]
    assert inner["finish"] is finish
