"""Execution-ledger history replay projector.

Ported from ``org.wwz.ai.domain.agent.ledger.replay.ReplayProjector``.

Two projection branches exist and they are NOT symmetric:

* LLM-only (``projectLlmHistory``) projects ``response_text`` **unconditionally**
  as a process frame — this is why the contract fixture's frame 1 exists despite
  ``tool_call_count = 0``.
* Mixed (``projectMixedHistory``) only projects ``response_text`` when
  ``should_project_response_text_as_process`` holds.

Frame envelopes are built through the Lombok ``@Builder`` path of
``GptProcessResult``: ``response``/``responseAll``/``responseType``/``packageType``
serialize as ``null`` even though the class has field initializers (no
``@Builder.Default``). Copying the Java field defaults is a contract failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from reactor_backend.domain import execution_ledger_constants as consts
from reactor_backend.domain.ledger_types import (
    ArtifactView,
    EventResult,
    LlmInvocationView,
    ProjectedReplayEvent,
    ReplayFactBundle,
    ToolInvocationView,
)
from reactor_backend.domain.summary_resolver import resolve as resolve_summary
from reactor_backend.domain.time_format import epoch_millis_string
from reactor_backend.domain.tool_projectors import ToolInvocationProjectorRegistry

_SUBAGENT_PREFIX = "subagent:"
_OUTER_TYPE_PLAN = "plan_thought"


def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _is_not_blank(value: str | None) -> bool:
    return not _is_blank(value)


def _string_or_none(value: object) -> str | None:
    return None if value is None else str(value)


class ReplayProjector:
    def __init__(
        self,
        tool_registry: ToolInvocationProjectorRegistry | None = None,
    ) -> None:
        self._tool_registry = tool_registry or ToolInvocationProjectorRegistry()

    # ------------------------------------------------------------------ public

    def project_history(
        self, bundle: ReplayFactBundle | None
    ) -> list[ProjectedReplayEvent]:
        state = EventResult()
        events: list[ProjectedReplayEvent] = []
        if bundle is None:
            return events

        llms = list(bundle.llm_invocations or [])
        tools = list(bundle.tool_invocations or [])
        has_llm = len(llms) > 0
        has_tool = len(tools) > 0

        if has_llm and has_tool:
            events.extend(self._project_mixed_history(bundle, state))
            self._append_run_summary_fallback(events, bundle, state)
            return events

        if has_llm:
            events.extend(self._project_llm_history(bundle, state))

        if has_tool:
            events.extend(self._project_tool_history(bundle, state))

        self._append_run_summary_fallback(events, bundle, state)
        return events

    def project_history_frames(
        self, bundle: ReplayFactBundle | None
    ) -> list[dict[str, Any]]:
        events = self.project_history(bundle)
        if not events:
            return []
        request_id = (
            None if bundle is None or bundle.run is None else bundle.run.request_id
        )
        return [self._to_frame(request_id, event) for event in events]

    # ----------------------------------------------------------------- branches

    def _project_llm_history(
        self, bundle: ReplayFactBundle, state: EventResult
    ) -> list[ProjectedReplayEvent]:
        events: list[ProjectedReplayEvent] = []
        for invocation in bundle.llm_invocations or []:
            if (
                self._should_skip_internal_llm_replay(invocation)
                or self._is_subagent_llm(invocation)
                or _is_blank(invocation.response_text)
            ):
                continue
            message_type = self._resolve_llm_message_type(invocation)
            events.append(
                self._build_llm_replay_event(
                    bundle, state, invocation, message_type, None, None
                )
            )
        return events

    def _project_mixed_history(
        self, bundle: ReplayFactBundle, state: EventResult
    ) -> list[ProjectedReplayEvent]:
        events: list[ProjectedReplayEvent] = []
        artifacts_by_tool = self._group_artifacts(bundle.artifacts)
        tools_by_llm = self._group_tools_by_llm_invocation_id(bundle.tool_invocations)
        orphan_tools: list[ToolInvocationView] = []
        for invocation in bundle.tool_invocations or []:
            if invocation is None:
                continue
            if invocation.llm_invocation_id is None:
                orphan_tools.append(invocation)

        for llm_invocation in self._sort_llm_invocations(bundle.llm_invocations):
            linked_tools = tools_by_llm.get(llm_invocation.id or -1, [])
            if self._should_skip_internal_llm_replay(llm_invocation):
                self._append_linked_tool_events(
                    events, linked_tools, artifacts_by_tool, state
                )
                continue

            subagent_parent_id: str | None = None
            if self._is_subagent_llm(llm_invocation):
                subagent_parent_id = self._resolve_subagent_parent_tool_use_id(
                    llm_invocation, linked_tools, bundle.tool_invocations
                )
                if _is_blank(subagent_parent_id):
                    self._append_linked_tool_events(
                        events, linked_tools, artifacts_by_tool, state
                    )
                    continue

            if _is_not_blank(llm_invocation.reasoning_content):
                events.append(
                    self._build_llm_replay_event(
                        bundle,
                        state,
                        llm_invocation,
                        "llm_reasoning",
                        None,
                        subagent_parent_id,
                    )
                )

            message_type: str | None = None
            if _is_not_blank(llm_invocation.response_text) and (
                self._should_project_response_text_as_process(llm_invocation)
            ):
                message_type = self._resolve_llm_message_type(llm_invocation)
                events.append(
                    self._build_llm_replay_event(
                        bundle,
                        state,
                        llm_invocation,
                        message_type,
                        self._resolve_planner_round_id(message_type, linked_tools),
                        subagent_parent_id,
                    )
                )
            elif (
                self._is_subagent_llm(llm_invocation)
                and _is_not_blank(llm_invocation.response_text)
                and (llm_invocation.tool_call_count is None or llm_invocation.tool_call_count == 0)
            ):
                events.append(
                    self._build_llm_replay_event(
                        bundle, state, llm_invocation, "result", None, subagent_parent_id
                    )
                )

            self._append_linked_tool_events(
                events, linked_tools, artifacts_by_tool, state
            )

        for orphan_tool in self._sort_tool_invocations(orphan_tools):
            artifacts = artifacts_by_tool.get(orphan_tool.id or -1, [])
            events.extend(
                self._tool_registry.project(orphan_tool, artifacts, state, False)
            )
        return events

    def _project_tool_history(
        self, bundle: ReplayFactBundle, state: EventResult
    ) -> list[ProjectedReplayEvent]:
        events: list[ProjectedReplayEvent] = []
        artifacts_by_tool = self._group_artifacts(bundle.artifacts)
        for invocation in self._sort_tool_invocations(bundle.tool_invocations):
            if invocation is None:
                continue
            artifacts = artifacts_by_tool.get(invocation.id or -1, [])
            events.extend(
                self._tool_registry.project(invocation, artifacts, state, False)
            )
        return events

    def _append_linked_tool_events(
        self,
        events: list[ProjectedReplayEvent],
        linked_tools: Sequence[ToolInvocationView],
        artifacts_by_tool: Mapping[int, list[ArtifactView]],
        state: EventResult,
    ) -> None:
        if not linked_tools:
            return
        for tool_invocation in linked_tools:
            if tool_invocation is None:
                continue
            artifacts = artifacts_by_tool.get(tool_invocation.id or -1, [])
            events.extend(
                self._tool_registry.project(tool_invocation, artifacts, state, True)
            )

    # ---------------------------------------------------------------- predicates

    @staticmethod
    def _should_skip_internal_llm_replay(invocation: LlmInvocationView | None) -> bool:
        if invocation is None:
            return True
        return invocation.call_kind in (
            consts.CALL_KIND_INTERNAL_DIGITAL_EMPLOYEE,
            consts.CALL_KIND_INTERNAL_COMPACT,
        )

    @staticmethod
    def _is_subagent_llm(invocation: LlmInvocationView | None) -> bool:
        if invocation is None:
            return False
        agent_name = invocation.agent_name
        return _is_not_blank(agent_name) and (agent_name or "").startswith(_SUBAGENT_PREFIX)

    @staticmethod
    def _should_project_response_text_as_process(
        invocation: LlmInvocationView | None,
    ) -> bool:
        if invocation is None:
            return False
        agent_name = invocation.agent_name
        if agent_name in ("planning", "summary"):
            return True
        if agent_name == "executor" and invocation.tool_call_count == 0:
            return True
        return invocation.tool_call_count is not None and invocation.tool_call_count > 0

    @staticmethod
    def _resolve_llm_message_type(invocation: LlmInvocationView | None) -> str:
        agent_name = None if invocation is None else invocation.agent_name
        if agent_name == "planning":
            return "plan_thought"
        if agent_name == "summary":
            return "result"
        if (
            agent_name == "executor"
            and invocation is not None
            and invocation.tool_call_count == 0
        ):
            return "task_summary"
        return "tool_thought"

    # ------------------------------------------------------------------- build

    def _build_llm_replay_event(
        self,
        bundle: ReplayFactBundle,
        state: EventResult,
        invocation: LlmInvocationView,
        message_type: str,
        planner_round_id: str | None,
        parent_tool_use_id: str | None,
    ) -> ProjectedReplayEvent:
        self._sync_planner_round_state(state, message_type, planner_round_id)
        artifact_refs: list[dict[str, Any]] | None = None
        if message_type == "result":
            resolved = resolve_summary(invocation.response_text)
            artifact_refs = resolved.artifact_refs or None
        task_id = state.task_id
        return ProjectedReplayEvent(
            task_id=task_id,
            task_order=state.task_order,
            message_id=self._resolve_llm_message_id(invocation, message_type),
            message_type=self._resolve_outer_message_type(message_type),
            message_order=state.get_and_incr_order(task_id + ":" + message_type),
            result_map=self._build_llm_response(
                bundle, invocation, message_type, planner_round_id, parent_tool_use_id
            ),
            artifact_refs=artifact_refs,
        )

    def _build_llm_response(
        self,
        bundle: ReplayFactBundle,
        invocation: LlmInvocationView,
        message_type: str,
        planner_round_id: str | None,
        parent_tool_use_id: str | None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {}
        response["requestId"] = None if bundle.run is None else bundle.run.request_id
        response["messageId"] = self._resolve_llm_message_id(invocation, message_type)
        response["messageType"] = message_type
        response["messageTime"] = epoch_millis_string(invocation.finished_at)
        response["isFinal"] = True
        response["finish"] = message_type == "result"
        if message_type == "plan_thought":
            response["planThought"] = invocation.response_text
            if _is_not_blank(planner_round_id):
                response["plannerRoundId"] = planner_round_id
        elif message_type == "llm_reasoning":
            response["reasoningContent"] = invocation.reasoning_content
        elif message_type == "tool_thought":
            response["toolThought"] = invocation.response_text
        elif message_type == "task_summary":
            response["taskSummary"] = invocation.response_text
            response["resultMap"] = {}
        elif message_type == "result":
            resolved = resolve_summary(invocation.response_text)
            response["result"] = resolved.summary_text
            response["taskSummary"] = resolved.summary_text
            if resolved.file_list:
                response["fileList"] = resolved.file_list
            if resolved.artifact_keys:
                response["artifactKeys"] = resolved.artifact_keys
        else:
            response["result"] = invocation.response_text
            response["taskSummary"] = invocation.response_text
        self._append_subagent_llm_nesting(response, invocation, parent_tool_use_id)
        return response

    def _append_subagent_llm_nesting(
        self,
        response: dict[str, Any],
        invocation: LlmInvocationView,
        parent_tool_use_id: str | None,
    ) -> None:
        if response is None or _is_blank(parent_tool_use_id):
            return
        response["parentToolUseId"] = parent_tool_use_id
        sub_type = self._subagent_type_from_agent_name(invocation.agent_name)
        if _is_not_blank(sub_type):
            response["subAgentType"] = sub_type
        existing = response.get("resultMap")
        nested: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
        nested["parentToolUseId"] = parent_tool_use_id
        if _is_not_blank(sub_type):
            nested["subAgentType"] = sub_type
        response["resultMap"] = nested

    def _append_run_summary_fallback(
        self,
        events: list[ProjectedReplayEvent],
        bundle: ReplayFactBundle,
        state: EventResult,
    ) -> None:
        if bundle.run is None or self._has_result_event(events):
            return
        run = bundle.run
        if _is_blank(run.final_summary_text):
            return

        resolved = resolve_summary(run.final_summary_text)
        result_map: dict[str, Any] = {}
        result_map["requestId"] = run.request_id
        result_map["messageId"] = f"{run.request_id}:summary"
        result_map["messageTime"] = self._resolve_run_message_time(run)
        result_map["messageType"] = "result"
        result_map["isFinal"] = True
        result_map["finish"] = run.status is not None and run.status != consts.STATUS_RUNNING
        result_map["result"] = resolved.summary_text
        result_map["taskSummary"] = resolved.summary_text
        if resolved.file_list:
            result_map["fileList"] = resolved.file_list
        if resolved.artifact_keys:
            result_map["artifactKeys"] = resolved.artifact_keys

        task_id = state.task_id
        events.append(
            ProjectedReplayEvent(
                task_id=task_id,
                task_order=state.task_order,
                message_id=f"{run.request_id}:summary",
                message_type="task",
                message_order=state.get_and_incr_order(task_id + ":result"),
                result_map=result_map,
                artifact_refs=resolved.artifact_refs or None,
            )
        )

    @staticmethod
    def _has_result_event(events: Sequence[ProjectedReplayEvent]) -> bool:
        for event in events:
            result_map = event.result_map
            if not isinstance(result_map, Mapping):
                continue
            message_type = result_map.get("messageType")
            if message_type not in ("result", "task_summary"):
                continue
            if _has_nested_subagent_parent(result_map):
                continue
            return True
        return False

    @staticmethod
    def _resolve_run_message_time(run: Any) -> str:
        if run is None:
            return epoch_millis_string(None)
        finished: datetime | None = getattr(run, "finished_at", None)
        if finished is not None:
            return epoch_millis_string(finished)
        started: datetime | None = getattr(run, "started_at", None)
        if started is not None:
            return epoch_millis_string(started)
        return epoch_millis_string(None)

    @staticmethod
    def _resolve_llm_message_id(
        invocation: LlmInvocationView, message_type: str
    ) -> str:
        base_name = invocation.agent_name or "llm"
        if _is_blank(invocation.agent_name):
            base_name = "llm"
        base = f"{base_name}:{invocation.invocation_seq}"
        if message_type == "llm_reasoning":
            return base + ":reasoning"
        return base

    @staticmethod
    def _resolve_outer_message_type(logical: str) -> str:
        return _OUTER_TYPE_PLAN if logical == _OUTER_TYPE_PLAN else "task"

    @staticmethod
    def _sync_planner_round_state(
        state: EventResult, message_type: str, planner_round_id: str | None
    ) -> None:
        if message_type == "plan_thought":
            state.set_planner_round_id(planner_round_id)

    @staticmethod
    def _resolve_planner_round_id(
        message_type: str, linked_tools: Sequence[ToolInvocationView]
    ) -> str | None:
        if message_type != "plan_thought" or not linked_tools:
            return None
        for linked_tool in linked_tools:
            if (
                linked_tool is not None
                and linked_tool.tool_name == "planning"
                and linked_tool.id is not None
            ):
                return str(linked_tool.id)
        return None

    # ------------------------------------------------------------------- frame

    @staticmethod
    def _to_frame(
        request_id: str | None, event: ProjectedReplayEvent
    ) -> dict[str, Any]:
        """``GptProcessResult`` builder serialization — key order is contract."""
        event_data: dict[str, Any] = {
            "taskId": event.task_id,
            "taskOrder": event.task_order,
            "messageType": event.message_type,
            "messageOrder": event.message_order,
            "messageId": event.message_id,
        }
        if event.artifact_refs is not None:
            event_data["artifactRefs"] = event.artifact_refs
        event_data["resultMap"] = event.result_map
        result_map: dict[str, Any] = {
            "agentType": "history",
            "multiAgent": {},
            "eventData": event_data,
        }
        return {
            "status": "success",
            "response": None,
            "responseAll": None,
            "finished": True,
            "useTimes": 0,
            "useTokens": 0,
            "resultMap": result_map,
            "responseType": None,
            "traceId": None,
            "reqId": request_id,
            "encrypted": False,
            "query": None,
            "messages": None,
            "packageType": None,
            "errorMsg": None,
            "eventSeq": 0,
            "retryMs": None,
        }

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _group_artifacts(
        artifacts: Sequence[ArtifactView],
    ) -> dict[int, list[ArtifactView]]:
        grouped: dict[int, list[ArtifactView]] = {}
        for artifact in artifacts or []:
            if artifact is None or artifact.tool_invocation_id is None:
                continue
            grouped.setdefault(artifact.tool_invocation_id, []).append(artifact)
        return grouped

    @staticmethod
    def _group_tools_by_llm_invocation_id(
        tools: Sequence[ToolInvocationView],
    ) -> dict[int, list[ToolInvocationView]]:
        grouped: dict[int, list[ToolInvocationView]] = {}
        for invocation in ReplayProjector._sort_tool_invocations(tools):
            if invocation is None or invocation.llm_invocation_id is None:
                continue
            grouped.setdefault(invocation.llm_invocation_id, []).append(invocation)
        return grouped

    @staticmethod
    def _sort_llm_invocations(
        invocations: Sequence[LlmInvocationView],
    ) -> list[LlmInvocationView]:
        items = [item for item in (invocations or []) if item is not None]
        return sorted(
            items,
            key=lambda item: (
                item.invocation_seq is None,
                item.invocation_seq if item.invocation_seq is not None else 0,
                item.id is None,
                item.id if item.id is not None else 0,
            ),
        )

    @staticmethod
    def _sort_tool_invocations(
        invocations: Sequence[ToolInvocationView],
    ) -> list[ToolInvocationView]:
        items = [item for item in (invocations or []) if item is not None]
        return sorted(
            items,
            key=lambda item: (
                item.dispatch_index is None,
                item.dispatch_index if item.dispatch_index is not None else 0,
                item.started_at is None,
                item.started_at.isoformat() if item.started_at is not None else "",
                item.id is None,
                item.id if item.id is not None else 0,
            ),
        )

    @staticmethod
    def _subagent_type_from_agent_name(agent_name: str | None) -> str | None:
        if _is_blank(agent_name) or not (agent_name or "").startswith(_SUBAGENT_PREFIX):
            return None
        sub_type = (agent_name or "")[len(_SUBAGENT_PREFIX) :].strip()
        return sub_type or None

    def _resolve_subagent_parent_tool_use_id(
        self,
        invocation: LlmInvocationView,
        linked_tools: Sequence[ToolInvocationView],
        all_tools: Sequence[ToolInvocationView],
    ) -> str | None:
        from_linked = _first_parent_tool_call_id(linked_tools)
        if _is_not_blank(from_linked):
            return from_linked
        sub_type = self._subagent_type_from_agent_name(
            None if invocation is None else invocation.agent_name
        )
        for tool in all_tools or []:
            if tool is None or _is_blank(tool.parent_tool_call_id):
                continue
            if _is_not_blank(sub_type) and (
                sub_type or ""
            ).lower() == (tool.sub_agent_type or "").lower():
                return tool.parent_tool_call_id
        for tool in all_tools or []:
            if tool is not None and _is_not_blank(tool.parent_tool_call_id):
                return tool.parent_tool_call_id
        return None


def _first_parent_tool_call_id(tools: Sequence[ToolInvocationView]) -> str | None:
    for tool in tools or []:
        if tool is not None and _is_not_blank(tool.parent_tool_call_id):
            return tool.parent_tool_call_id
    return None


def _has_nested_subagent_parent(result_map: Mapping[str, Any]) -> bool:
    if not result_map:
        return False
    if _is_not_blank(_string_or_none(result_map.get("parentToolUseId"))):
        return True
    nested = result_map.get("resultMap")
    if isinstance(nested, Mapping):
        return _is_not_blank(_string_or_none(nested.get("parentToolUseId")))
    return False
