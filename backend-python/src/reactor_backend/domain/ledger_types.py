"""Ledger view models and the replay event counter.

Ported from ``org.wwz.ai.domain.agent.ledger.model.*`` and ``EventResult``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DialogueSessionView:
    id: int | None = None
    session_id: str | None = None
    visitor_id: str | None = None
    title: str | None = None
    status: int | None = None
    latest_request_id: str | None = None
    latest_query_text: str | None = None
    latest_summary_text: str | None = None
    run_count: int = 0
    finished_run_count: int = 0
    failed_run_count: int = 0
    started_at: datetime | None = None
    last_active_at: datetime | None = None


@dataclass
class DialogueRunView:
    id: int | None = None
    run_uid: str | None = None
    request_id: str | None = None
    session_id: str | None = None
    visitor_id: str | None = None
    entry_agent: str | None = None
    status: int | None = None
    query_text: str | None = None
    final_summary_text: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifact_summaries: Sequence[ArtifactView] = field(default_factory=list)


@dataclass
class LlmInvocationView:
    id: int | None = None
    run_id: int | None = None
    invocation_seq: int | None = None
    agent_name: str | None = None
    step_no: int | None = None
    call_kind: str | None = None
    streaming: bool | None = None
    model_name: str | None = None
    response_text: str | None = None
    reasoning_content: str | None = None
    tool_call_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    est_system_tokens: int | None = None
    est_tool_tokens: int | None = None
    est_message_tokens: int | None = None
    est_total_tokens: int | None = None
    status: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class ToolInvocationView:
    id: int | None = None
    run_id: int | None = None
    llm_invocation_id: int | None = None
    tool_call_id: str | None = None
    parent_tool_call_id: str | None = None
    tool_name: str | None = None
    tool_provider: str | None = None
    agent_name: str | None = None
    sub_agent_id: str | None = None
    sub_agent_type: str | None = None
    sub_agent_description: str | None = None
    dispatch_index: int | None = None
    input_json: str | None = None
    llm_observation: str | None = None
    error_msg: str | None = None
    status: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    request_id: str | None = None
    session_id: str | None = None
    structured_output: Any = None


@dataclass
class ArtifactView:
    id: int | None = None
    run_id: int | None = None
    tool_invocation_id: int | None = None
    request_id: str | None = None
    tool_call_id: str | None = None
    artifact_role: str | None = None
    visibility: str | None = None
    source_type: str | None = None
    storage_key: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    preview_url: str | None = None
    download_url: str | None = None
    metadata_json: str | None = None


@dataclass
class ReplayFactBundle:
    run: DialogueRunView | None = None
    llm_invocations: Sequence[LlmInvocationView] = field(default_factory=list)
    tool_invocations: Sequence[ToolInvocationView] = field(default_factory=list)
    artifacts: Sequence[ArtifactView] = field(default_factory=list)


@dataclass
class ProjectedReplayEvent:
    task_id: str
    task_order: int
    message_id: str
    message_type: str
    message_order: int
    result_map: dict[str, Any]
    artifact_refs: list[dict[str, Any]] | None = None


@dataclass
class ExecutionRunDetail:
    run: DialogueRunView
    llm_invocations: list[LlmInvocationView] = field(default_factory=list)
    tool_invocations: list[ToolInvocationView] = field(default_factory=list)
    artifacts: list[ArtifactView] = field(default_factory=list)


class EventResult:
    """Incremental event assembly state (port of ``EventResult``).

    ``task_id`` is a lazily minted ``UUID.randomUUID()`` string; ``task_order``
    counts every projected event from 1; ``message_order`` is 1-based per
    ``taskId + ":" + logicalMessageType`` key.
    """

    def __init__(self) -> None:
        self._order_mapping: dict[str, int] = {}
        self._task_id: str | None = None
        self._task_order: int = 1
        self._planner_round_id: str | None = None

    def get_and_incr_order(self, key: str) -> int:
        order = self._order_mapping.get(key)
        if order is None:
            self._order_mapping[key] = 1
            return 1
        self._order_mapping[key] = order + 1
        return order + 1

    @property
    def task_id(self) -> str:
        if not self._task_id:
            self._task_id = str(uuid.uuid4())
        return self._task_id

    def renew_task_id(self) -> str:
        self._task_order = 1
        self._task_id = str(uuid.uuid4())
        return self._task_id

    @property
    def task_order(self) -> int:
        current = self._task_order
        self._task_order = current + 1
        return current

    @property
    def planner_round_id(self) -> str | None:
        return self._planner_round_id

    def set_planner_round_id(self, planner_round_id: str | None) -> None:
        if planner_round_id is None or planner_round_id.strip() == "":
            self._planner_round_id = None
            return
        self._planner_round_id = planner_round_id
