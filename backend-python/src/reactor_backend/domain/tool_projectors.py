"""Tool-invocation history replay projectors.

Ported from ``org.wwz.ai.domain.agent.ledger.replay.projector.impl.*`` and
``org.wwz.ai.domain.agent.ledger.replay.ArtifactRelativePath``. The registry picks
a specialized projector by ``tool_name`` and falls back to the default
``tool_result`` projector. Shared envelope / artifact-ref / file-ref merging lives
in :class:`AbstractToolInvocationProjector`.

Payload maps are ``dict`` (insertion-ordered) so emitted JSON key order matches
Java's ``LinkedHashMap``. ``dict`` assignment overwrites in place, matching
``Map.put``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from reactor_backend.domain import gen_ui_schema
from reactor_backend.domain.ledger_types import (
    ArtifactView,
    EventResult,
    ProjectedReplayEvent,
    ToolInvocationView,
)
from reactor_backend.domain.time_format import epoch_millis_string

_ARTIFACT_NOT_FOUND = "artifact_not_found"
_WORKSPACE_PREFIX = "workspace:"


# --------------------------------------------------------------------------
# commons-lang3 string helpers (null/blank semantics matter for key emission)
# --------------------------------------------------------------------------


def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _is_not_blank(value: str | None) -> bool:
    return not _is_blank(value)


def _default_string(value: str | None) -> str:
    """``StringUtils.defaultString(str)`` — null → ``""``."""
    return "" if value is None else value


def _default_string_or(value: str | None, fallback: str | None) -> str | None:
    """``StringUtils.defaultString(str, default)`` — replaces **null only**."""
    return fallback if value is None else value


def _default_if_blank(value: str | None, fallback: str | None) -> str | None:
    """``StringUtils.defaultIfBlank(str, default)`` — blank wins over empty."""
    return fallback if _is_blank(value) else value


def _java_string_value_of(value: Any) -> str:
    """``String.valueOf(Object)`` — null becomes the literal ``"null"``."""
    return "null" if value is None else str(value)


def _map_value_as_java_string(info: Mapping[str, Any], key: str) -> str:
    """``String.valueOf(map.getOrDefault(key, ""))``."""
    if key not in info:
        return ""
    return _java_string_value_of(info[key])


def read_map(text: str | None) -> dict[str, Any]:
    """Jackson object parse: blank or unparsable → ``{}``.

    Mirrors ``AbstractToolInvocationProjector.readMap``.
    """
    if _is_blank(text):
        return {}
    try:
        parsed = json.loads(text or "")
    except (ValueError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _parse_json_object(text: str | None) -> dict[str, Any] | None:
    """``JSON.parseObject`` for metadata / GenUI recovery — invalid → ``None``."""
    if _is_blank(text):
        return None
    try:
        parsed = json.loads(text or "")
    except (ValueError, TypeError):
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _meta_string(obj: Mapping[str, Any], key: str) -> str | None:
    """fastjson ``JSONObject.getString``: null in → null out, else ``String.valueOf``."""
    if key not in obj:
        return None
    value = obj[key]
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


# --------------------------------------------------------------------------
# workspace path + artifact relative path
# --------------------------------------------------------------------------


def _normalize_workspace_path(raw: str | None) -> str:
    """``ToolArtifactFormatter.normalizeWorkspacePath`` — blank → ``""``."""
    if _is_blank(raw):
        return ""
    path = (raw or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    while path.startswith("/"):
        path = path[1:]
    return path


def _read_metadata_path(metadata_json: str | None) -> str | None:
    """``ArtifactRelativePath.readMetadataPath`` — raw value or null (unnormalized)."""
    obj = _parse_json_object(metadata_json)
    if obj is None:
        return None
    relative_path = _meta_string(obj, "relativePath")
    if _is_not_blank(relative_path):
        return relative_path
    origin_file_name = _meta_string(obj, "originFileName")
    if _is_not_blank(origin_file_name) and (
        "/" in (origin_file_name or "") or "\\" in (origin_file_name or "")
    ):
        return origin_file_name
    description = _meta_string(obj, "description")
    if description is not None and description.startswith(_WORKSPACE_PREFIX):
        return description[len(_WORKSPACE_PREFIX) :]
    return None


def _resolve_artifact_relative_path(artifact: ArtifactView) -> str:
    """``ArtifactRelativePath.resolve`` — blank metadata falls back to fileName."""
    if artifact is None:
        return ""
    from_meta = _read_metadata_path(artifact.metadata_json)
    if _is_not_blank(from_meta):
        return _normalize_workspace_path(from_meta)
    return _normalize_workspace_path(artifact.file_name)


def _put_relative_path(target: dict[str, Any], artifact: ArtifactView) -> None:
    """``ArtifactRelativePath.putOn`` — putIfAbsent pair, skipped when blank."""
    if target is None:
        return
    relative_path = _resolve_artifact_relative_path(artifact)
    if _is_blank(relative_path):
        return
    target.setdefault("relativePath", relative_path)
    target.setdefault("originFileName", relative_path)


# --------------------------------------------------------------------------
# artifact / file-ref shapes
# --------------------------------------------------------------------------


def build_artifact_refs(
    artifacts: Sequence[ArtifactView] | None,
) -> list[dict[str, Any]]:
    """``AbstractToolInvocationProjector.buildArtifactRefs``."""
    if not artifacts:
        return []
    refs: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact is None:
            continue
        ref: dict[str, Any] = {
            "resourceKey": _default_if_blank(artifact.storage_key, artifact.file_name),
            "name": artifact.file_name,
            "previewUrl": artifact.preview_url,
            "downloadUrl": artifact.download_url,
            "fileName": artifact.file_name,
        }
        _put_relative_path(ref, artifact)
        ref["mimeType"] = artifact.mime_type
        ref["size"] = artifact.file_size
        ref["missing"] = False
        refs.append(ref)
    return refs


def _to_tool_file_info(file_ref: Mapping[str, Any]) -> dict[str, Any]:
    """``toToolFileInfo`` — ``ToolFileRef`` → map (no ``mimeType``, matching Java)."""
    info: dict[str, Any] = {"fileName": _default_string(_as_str(file_ref.get("fileName")))}
    relative_path = _normalize_workspace_path(_as_str(file_ref.get("relativePath")))
    if _is_not_blank(relative_path):
        info["relativePath"] = relative_path
        info["originFileName"] = relative_path
    for key in ("downloadUrl", "previewUrl", "ossUrl", "domainUrl"):
        value = _as_str(file_ref.get(key))
        if _is_not_blank(value):
            info[key] = value
    info["missing"] = False
    if file_ref.get("fileSize") is not None:
        info["fileSize"] = file_ref.get("fileSize")
    return info


def _to_artifact_info(artifact: ArtifactView) -> dict[str, Any]:
    """``toArtifactInfo`` — raw ``fileName``/URLs (may be null), no ``mimeType``."""
    info: dict[str, Any] = {
        "fileName": artifact.file_name,
        "downloadUrl": artifact.download_url,
        "previewUrl": artifact.preview_url,
        "ossUrl": artifact.download_url,
        "domainUrl": artifact.preview_url,
        "missing": False,
    }
    _put_relative_path(info, artifact)
    if artifact.file_size is not None:
        info["fileSize"] = artifact.file_size
    return info


def _enrich_from_artifacts(
    merged: list[dict[str, Any]], artifacts: Sequence[ArtifactView]
) -> None:
    for info in merged:
        # Java compares String.valueOf(getOrDefault("fileName","")) — a JSON null
        # becomes the literal "null" and therefore never matches a real fileName.
        file_name = _map_value_as_java_string(info, "fileName")
        matched = next(
            (
                artifact
                for artifact in artifacts
                if artifact is not None and file_name == artifact.file_name
            ),
            None,
        )
        if matched is None:
            continue
        info.setdefault("downloadUrl", matched.download_url)
        info.setdefault("previewUrl", matched.preview_url)
        info.setdefault("ossUrl", matched.download_url)
        info.setdefault("domainUrl", matched.preview_url)
        info.setdefault("missing", False)
        _put_relative_path(info, matched)
        if matched.file_size is not None:
            info.setdefault("fileSize", matched.file_size)


def _mark_missing_links(merged: list[dict[str, Any]]) -> None:
    for info in merged:
        # JSON-null counts as "has URL" (String.valueOf → "null" is not blank).
        has_preview = _is_not_blank(_map_value_as_java_string(info, "previewUrl"))
        has_download = _is_not_blank(_map_value_as_java_string(info, "downloadUrl"))
        if not has_preview and not has_download:
            info["missing"] = True
            info.setdefault("missingReason", _ARTIFACT_NOT_FOUND)
        else:
            info.setdefault("missing", False)


def merge_file_refs(
    file_refs: Sequence[Mapping[str, Any] | None] | None,
    artifacts: Sequence[ArtifactView] | None,
) -> list[dict[str, Any]]:
    """``mergeFileRefs`` — three-branch pipeline; ``markMissingLinks`` only in the
    both-non-empty branch (Java returns early otherwise)."""
    merged = [
        _to_tool_file_info(item) for item in (file_refs or []) if item is not None
    ]
    if not artifacts:
        return merged
    if not merged:
        return [_to_artifact_info(a) for a in artifacts if a is not None]
    _enrich_from_artifacts(merged, artifacts)
    _mark_missing_links(merged)
    return merged


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else (None if value is None else str(value))


# --------------------------------------------------------------------------
# AskUserQuestion persisted-state port (optional; Java default is null repo)
# --------------------------------------------------------------------------


@dataclass
class UserQuestionRecord:
    question_id: str | None = None
    tool_invocation_id: int | None = None
    tool_call_id: str | None = None
    questions: Any = None
    answers: Any = None
    status: str | None = None


class UserQuestionReader(Protocol):
    def find_by_question_id(self, question_id: str) -> UserQuestionRecord | None: ...

    def list_open_by_session_id(
        self, session_id: str
    ) -> Sequence[UserQuestionRecord | None]: ...


def _to_client_status(status: str | None) -> str:
    """``AskUserQuestionObservationSupport.toClientStatus``."""
    if status in ("ANSWERED", "RESUMING", "RESUME_PENDING"):
        return "answered"
    if status == "TIMEOUT":
        return "timeout"
    if status in ("CANCELLED", "FAILED"):
        return "cancelled"
    return "pending"


# --------------------------------------------------------------------------
# projector base
# --------------------------------------------------------------------------


class ToolInvocationProjector(Protocol):
    def supports(self, tool_name: str | None) -> bool: ...

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]: ...


class AbstractToolInvocationProjector:
    def supports(self, tool_name: str | None) -> bool:
        raise NotImplementedError

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        raise NotImplementedError

    def build_task_event(
        self,
        state: EventResult,
        invocation: ToolInvocationView,
        logical_message_type: str,
        response_payload: dict[str, Any],
        artifact_refs: list[dict[str, Any]],
    ) -> ProjectedReplayEvent:
        task_id = state.task_id
        return ProjectedReplayEvent(
            task_id=task_id,
            task_order=state.task_order,
            message_id=self.resolve_message_id(invocation, logical_message_type),
            message_type="task",
            message_order=state.get_and_incr_order(task_id + ":" + logical_message_type),
            result_map=response_payload,
            artifact_refs=artifact_refs or None,
        )

    def build_structured_tool_response(
        self,
        invocation: ToolInvocationView,
        logical_message_type: str,
        result_map: dict[str, Any],
    ) -> dict[str, Any]:
        self._decorate_tool_payload(result_map, invocation)
        response = self._new_tool_replay_envelope(invocation, logical_message_type)
        response["resultMap"] = result_map
        self._append_subagent_nesting_tags(response, invocation)
        return response

    def build_tool_result_response(
        self,
        invocation: ToolInvocationView,
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        self.put_tool_binding_if_present(tool_result, invocation)
        response = self._new_tool_replay_envelope(invocation, "tool_result")
        response["toolResult"] = tool_result
        self._append_subagent_nesting_tags(response, invocation)
        if invocation is not None and _is_not_blank(invocation.parent_tool_call_id):
            nested: dict[str, Any] = {}
            self._decorate_tool_payload(nested, invocation)
            response["resultMap"] = nested
        return response

    def _new_tool_replay_envelope(
        self, invocation: ToolInvocationView | None, message_type: str
    ) -> dict[str, Any]:
        return {
            "requestId": None if invocation is None else invocation.request_id,
            "messageId": self.resolve_message_id(invocation, message_type),
            "messageTime": self.resolve_message_time(invocation),
            "messageType": message_type,
            "isFinal": True,
            "finish": False,
        }

    def _decorate_tool_payload(
        self, target: dict[str, Any], invocation: ToolInvocationView | None
    ) -> None:
        self.put_tool_binding_if_present(target, invocation)
        self._append_subagent_nesting_tags(target, invocation)

    def put_tool_binding_if_present(
        self, result_map: dict[str, Any], invocation: ToolInvocationView | None
    ) -> None:
        if result_map is None or invocation is None:
            return
        if _is_not_blank(invocation.tool_call_id):
            result_map["toolCallId"] = invocation.tool_call_id
        if _is_not_blank(invocation.tool_name):
            result_map["toolName"] = invocation.tool_name

    def _append_subagent_nesting_tags(
        self, target: dict[str, Any], invocation: ToolInvocationView | None
    ) -> None:
        if target is None or invocation is None:
            return
        if _is_not_blank(invocation.parent_tool_call_id):
            target["parentToolUseId"] = invocation.parent_tool_call_id
        if _is_not_blank(invocation.sub_agent_id):
            target["subAgentId"] = invocation.sub_agent_id
        sub_agent_type = invocation.sub_agent_type
        if _is_blank(sub_agent_type) and (invocation.agent_name or "").startswith(
            "subagent:"
        ):
            sub_agent_type = (invocation.agent_name or "")[len("subagent:") :]
        if _is_not_blank(sub_agent_type):
            target["subAgentType"] = sub_agent_type
        if _is_not_blank(invocation.sub_agent_description):
            target["subAgentDescription"] = invocation.sub_agent_description

    @staticmethod
    def resolve_message_id(
        invocation: ToolInvocationView | None, suffix: str | None
    ) -> str:
        base = "history-tool"
        if invocation is not None and _is_not_blank(invocation.tool_call_id):
            base = invocation.tool_call_id or base
        elif invocation is not None and _is_not_blank(invocation.tool_name):
            base = invocation.tool_name or base
        return base if _is_blank(suffix) else f"{base}:{suffix}"

    @staticmethod
    def resolve_message_time(invocation: ToolInvocationView | None) -> str:
        if invocation is not None and invocation.finished_at is not None:
            return epoch_millis_string(invocation.finished_at)
        if invocation is not None and invocation.started_at is not None:
            return epoch_millis_string(invocation.started_at)
        return epoch_millis_string(None)


def _structured_output(
    invocation: ToolInvocationView | None,
) -> Mapping[str, Any] | None:
    if invocation is None:
        return None
    output = invocation.structured_output
    return output if isinstance(output, Mapping) else None


def _file_refs_of(output: Mapping[str, Any] | None) -> list[Mapping[str, Any]] | None:
    if output is None:
        return None
    refs = output.get("fileRefs")
    return list(refs) if isinstance(refs, list) else None


# --------------------------------------------------------------------------
# specialized projectors
# --------------------------------------------------------------------------


class DefaultToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return False

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        text = (
            ""
            if invocation is None
            else _default_if_blank(invocation.llm_observation, invocation.error_msg)
        )
        tool_result: dict[str, Any] = {
            "toolName": None if invocation is None else invocation.tool_name,
            "toolParam": {} if invocation is None else read_map(invocation.input_json),
            "toolResult": text,
        }
        return [
            self.build_task_event(
                state,
                invocation,
                "tool_result",
                self.build_tool_result_response(invocation, tool_result),
                build_artifact_refs(artifacts),
            )
        ]


class CodeInterpreterToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "code_interpreter"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        code_output = (
            ""
            if output is None
            else _default_string(_as_str(output.get("codeOutput")))
        )
        if _is_blank(code_output) and invocation is not None:
            code_output = _default_string(invocation.llm_observation)
        result_map: dict[str, Any] = {
            "isFinal": True,
            "codeOutput": code_output,
            "data": code_output,
        }
        content = _as_str(output.get("content")) if output is not None else None
        if _is_not_blank(content):
            result_map["content"] = content
        code = _as_str(output.get("code")) if output is not None else None
        if _is_not_blank(code):
            result_map["code"] = code
        explain = _as_str(output.get("explain")) if output is not None else None
        if _is_not_blank(explain):
            result_map["explain"] = explain
        result_map["fileInfo"] = merge_file_refs(_file_refs_of(output), artifacts)
        return [
            self.build_task_event(
                state,
                invocation,
                "code",
                self.build_structured_tool_response(invocation, "code", result_map),
                build_artifact_refs(artifacts),
            )
        ]


class CanvasPublishToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "canvas_publish"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        result_map: dict[str, Any] = {
            "isFinal": True,
            "fileType": "html",
            "command": "发布画布",
        }
        title = _as_str(output.get("title")) if output is not None else None
        if _is_not_blank(title):
            result_map["title"] = title
        primary = _as_str(output.get("primaryFileName")) if output is not None else None
        if _is_not_blank(primary):
            result_map["primaryFileName"] = primary
        preview = _as_str(output.get("previewUrl")) if output is not None else None
        if _is_not_blank(preview):
            result_map["previewUrl"] = preview
        download = _as_str(output.get("downloadUrl")) if output is not None else None
        if _is_not_blank(download):
            result_map["downloadUrl"] = download
        result_map["fileInfo"] = merge_file_refs(_file_refs_of(output), artifacts)
        return [
            self.build_task_event(
                state,
                invocation,
                "html",
                self.build_structured_tool_response(invocation, "html", result_map),
                build_artifact_refs(artifacts),
            )
        ]


class DataAnalysisToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "data_analysis"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        data = (
            ""
            if output is None
            else _default_string(_as_str(output.get("content")))
        )
        if _is_blank(data) and invocation is not None:
            data = _default_string(invocation.llm_observation)
        task = (
            ""
            if output is None
            else _default_string(_as_str(output.get("task")))
        )
        result_map: dict[str, Any] = {
            "isFinal": True,
            "task": task,
            "data": data,
            "fileInfo": merge_file_refs(_file_refs_of(output), artifacts),
        }
        return [
            self.build_task_event(
                state,
                invocation,
                "data_analysis",
                self.build_structured_tool_response(
                    invocation, "data_analysis", result_map
                ),
                build_artifact_refs(artifacts),
            )
        ]


class MultiModalToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "multimodalagent_tool"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        markdown = (
            ""
            if output is None
            else _default_string(_as_str(output.get("markdownContent")))
        )
        if _is_blank(markdown) and invocation is not None:
            markdown = _default_string(invocation.llm_observation)
        result_map: dict[str, Any] = {
            "isFinal": True,
            "data": markdown,
            "fileInfo": merge_file_refs(_file_refs_of(output), artifacts),
        }
        summary = _as_str(output.get("summary")) if output is not None else None
        if _is_not_blank(summary):
            result_map["summary"] = summary
        return [
            self.build_task_event(
                state,
                invocation,
                "markdown",
                self.build_structured_tool_response(invocation, "markdown", result_map),
                build_artifact_refs(artifacts),
            )
        ]


class ImageGenerationToolInvocationProjector(AbstractToolInvocationProjector):
    """Two frames: ``file`` (only when merged fileInfo is non-empty) then
    ``tool_result`` (always) with empty ``artifactRefs``."""

    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "image_generation_tool"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        events: list[ProjectedReplayEvent] = []
        merged_file_info = merge_file_refs(_file_refs_of(output), artifacts)
        if merged_file_info:
            file_result: dict[str, Any] = {
                "command": "生成图片",
                "fileInfo": merged_file_info,
            }
            self.put_tool_binding_if_present(file_result, invocation)
            events.append(
                self.build_task_event(
                    state,
                    invocation,
                    "file",
                    self.build_structured_tool_response(
                        invocation, "file", file_result
                    ),
                    build_artifact_refs(artifacts),
                )
            )

        summary = (
            ""
            if output is None
            else _default_string(_as_str(output.get("summary")))
        )
        if _is_blank(summary) and invocation is not None:
            summary = _default_string(invocation.llm_observation)
        tool_result: dict[str, Any] = {
            "toolName": None if invocation is None else invocation.tool_name,
            "toolParam": {} if invocation is None else read_map(invocation.input_json),
            "toolResult": summary,
        }
        if invocation is not None and _is_not_blank(invocation.tool_call_id):
            tool_result["toolCallId"] = invocation.tool_call_id
        events.append(
            self.build_task_event(
                state,
                invocation,
                "tool_result",
                self.build_tool_result_response(invocation, tool_result),
                [],
            )
        )
        return events


class AskUserQuestionToolInvocationProjector(AbstractToolInvocationProjector):
    """Reads ``input_json`` + ``llm_observation`` maps — never ``structured_output``."""

    def __init__(
        self, user_question_reader: UserQuestionReader | None = None
    ) -> None:
        self._user_question_reader = user_question_reader

    def supports(self, tool_name: str | None) -> bool:
        return (tool_name or "").lower() == "askuserquestion"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        input_map = read_map(None if invocation is None else invocation.input_json)
        observation = read_map(
            None if invocation is None else invocation.llm_observation
        )
        payload: dict[str, Any] = {"messageType": "ask_user_question"}

        question_id = self._string_value(observation.get("questionId"))
        persisted = self._find_persisted_question(question_id, invocation)
        resolved_question_id = _default_if_blank(
            question_id,
            None if persisted is None else persisted.question_id,
        )

        questions = None if persisted is None else persisted.questions
        if questions is None:
            questions = observation.get("questions")
        if questions is None:
            questions = input_map.get("questions")
        if questions is not None:
            payload["questions"] = questions
        payload["input"] = input_map

        answers = None if persisted is None else persisted.answers
        if answers is None:
            answers = observation.get("answers")
        answered = isinstance(answers, Mapping)
        if answered:
            payload["answers"] = answers
        status = (
            self._to_pending_status(answered)
            if persisted is None
            else _to_client_status(persisted.status)
        )
        payload["status"] = status
        if persisted is not None and _is_not_blank(persisted.status):
            payload["persistenceStatus"] = persisted.status
        if _is_not_blank(resolved_question_id):
            payload["questionId"] = resolved_question_id

        return [
            self.build_task_event(
                state,
                invocation,
                "ask_user_question",
                self.build_structured_tool_response(
                    invocation, "ask_user_question", payload
                ),
                build_artifact_refs(artifacts),
            )
        ]

    @staticmethod
    def _to_pending_status(answered: bool) -> str:
        return "answered" if answered else "pending"

    @staticmethod
    def _string_value(value: Any) -> str | None:
        return None if value is None else str(value)

    def _find_persisted_question(
        self, question_id: str | None, invocation: ToolInvocationView | None
    ) -> UserQuestionRecord | None:
        if self._user_question_reader is None:
            return None
        try:
            if _is_not_blank(question_id):
                by_id = self._user_question_reader.find_by_question_id(
                    question_id or ""
                )
                if by_id is not None:
                    return by_id
            if invocation is None or _is_blank(invocation.session_id):
                return None
            for record in self._user_question_reader.list_open_by_session_id(
                invocation.session_id or ""
            ):
                if record is None:
                    continue
                if (
                    invocation.id is not None
                    and invocation.id == record.tool_invocation_id
                ):
                    return record
                if _is_not_blank(invocation.tool_call_id) and (
                    invocation.tool_call_id == record.tool_call_id
                ):
                    return record
            return None
        except Exception:  # noqa: BLE001 - replay must not die on question lookup
            return None


class DeepSearchToolInvocationProjector(AbstractToolInvocationProjector):
    """deep_search: four distinct stage shapes; missing/empty stages ⇒ zero frames
    (never falls back to the default projector)."""

    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "deep_search"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        stages = None if output is None else output.get("stages")
        if output is None or stages is None or not stages:
            return []
        events: list[ProjectedReplayEvent] = []
        for stage in stages:
            if not isinstance(stage, Mapping):
                continue
            stage_type = _as_str(stage.get("stage"))
            if _is_blank(stage_type):
                continue
            builder = {
                "extend": self._build_extend_result,
                "search": self._build_search_result,
                "chapter_summary": self._build_chapter_summary_result,
                "report": self._build_report_result,
            }.get(stage_type or "")
            if builder is None:
                continue
            result_map = builder(output, stage)
            if not result_map:
                continue
            events.append(
                self.build_task_event(
                    state,
                    invocation,
                    "deep_search",
                    self.build_structured_tool_response(
                        invocation, "deep_search", result_map
                    ),
                    self._resolve_stage_artifact_refs(stage_type, artifacts),
                )
            )
        return events

    @staticmethod
    def _resolve_stage_artifact_refs(
        stage_type: str | None, artifacts: Sequence[ArtifactView] | None
    ) -> list[dict[str, Any]]:
        if stage_type != "report" or not artifacts:
            return []
        final_artifacts = [
            artifact
            for artifact in artifacts
            if artifact is not None
            and _is_not_blank(artifact.file_name)
            and not (artifact.file_name or "").lower().endswith("_search_result.txt")
        ]
        return build_artifact_refs(final_artifacts)

    @staticmethod
    def _build_extend_result(
        output: Mapping[str, Any], stage: Mapping[str, Any]
    ) -> dict[str, Any]:
        queries = stage.get("queries")
        search_result = {
            "query": list(queries) if queries is not None else [],
            "docs": [],
            "chapters": _build_chapter_metadata(output),
        }
        return {
            "messageType": "extend",
            "isFinal": True,
            "searchFinish": False,
            "query": output.get("query"),
            "searchResult": search_result,
        }

    @staticmethod
    def _build_search_result(
        output: Mapping[str, Any], stage: Mapping[str, Any]
    ) -> dict[str, Any]:
        queries: list[Any] = []
        docs: list[list[dict[str, Any]]] = []
        for item in stage.get("results") or []:
            if not isinstance(item, Mapping):
                continue
            queries.append(_default_string(_as_str(item.get("query"))))
            docs.append(_doc_list(item))
        search_result = {
            "query": queries,
            "docs": docs,
            "chapters": _build_chapter_metadata(output),
        }
        return {
            "messageType": "search",
            "isFinal": True,
            "searchFinish": True,
            "query": output.get("query"),
            "searchResult": search_result,
        }

    @staticmethod
    def _build_chapter_summary_result(
        output: Mapping[str, Any], stage: Mapping[str, Any]
    ) -> dict[str, Any]:
        queries = stage.get("queries")
        query_list: list[Any] = list(queries) if queries is not None else []
        docs: list[list[dict[str, Any]]] = []
        for item in stage.get("results") or []:
            if not isinstance(item, Mapping):
                continue
            item_query = _default_string(_as_str(item.get("query")))
            if item_query not in query_list:
                query_list.append(item_query)
            docs.append(_doc_list(item))
        chapter_summary = _default_string(_as_str(stage.get("chapterSummary")))
        return {
            "messageType": "chapter_summary",
            "isFinal": True,
            "searchFinish": True,
            "query": output.get("query"),
            "chapterId": _default_string(_as_str(stage.get("chapterId"))),
            "chapterTitle": _default_string(_as_str(stage.get("chapterTitle"))),
            # defaultString(str, default) replaces null only — not blank.
            "chapterContent": _default_string_or(
                _as_str(stage.get("chapterContent")),
                _as_str(stage.get("chapterTitle")),
            ),
            "chapterOrder": stage.get("chapterOrder"),
            "chapterSummary": chapter_summary,
            "answer": chapter_summary,
            "searchResult": {"query": query_list, "docs": docs},
        }

    @staticmethod
    def _build_report_result(
        output: Mapping[str, Any], stage: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "messageType": "report",
            "isFinal": True,
            "query": output.get("query"),
            "answer": _default_string(_as_str(stage.get("answer"))),
        }


def _doc_list(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    doc_list: list[dict[str, Any]] = []
    for doc in item.get("docs") or []:
        if not isinstance(doc, Mapping):
            continue
        summary = _as_str(doc.get("summary"))
        doc_map: dict[str, Any] = {
            "title": _default_string(_as_str(doc.get("title"))),
            "link": _default_string(_as_str(doc.get("link"))),
        }
        if _is_not_blank(summary):
            doc_map["content"] = summary
        doc_list.append(doc_map)
    return doc_list


def _build_chapter_metadata(output: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """``buildChapterMetadata`` — reads ``output.chapters`` (never the stage)."""
    if output is None or output.get("chapters") is None:
        return []
    chapters: list[dict[str, Any]] = []
    for chapter in output.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        queries = chapter.get("queries")
        chapters.append(
            {
                "chapterId": chapter.get("chapterId"),
                "chapterTitle": chapter.get("title"),
                "chapterContent": chapter.get("content"),
                "chapterOrder": chapter.get("order"),
                "queries": list(queries) if queries is not None else [],
            }
        )
    return chapters


class GenUiTreeToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "emit_ui_tree"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        tree = None if output is None else output.get("tree")
        canvas_id = None if output is None else _as_str(output.get("canvasId"))
        if tree is None and invocation is not None:
            tree = _recover_tree(invocation.input_json)

        result_map: dict[str, Any] = {"isFinal": True}
        if tree is not None:
            result_map["tree"] = tree
        if _is_not_blank(canvas_id):
            result_map["canvas_id"] = canvas_id
        self.put_tool_binding_if_present(result_map, invocation)

        return [
            self.build_task_event(
                state,
                invocation,
                "ui_tree",
                self.build_structured_tool_response(invocation, "ui_tree", result_map),
                build_artifact_refs(artifacts),
            )
        ]


class GenUiPatchToolInvocationProjector(AbstractToolInvocationProjector):
    def supports(self, tool_name: str | None) -> bool:
        return tool_name == "emit_ui_patch"

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
    ) -> list[ProjectedReplayEvent]:
        output = _structured_output(invocation)
        patches = None if output is None else output.get("patches")
        canvas_id = None if output is None else _as_str(output.get("canvasId"))
        seq = None if output is None else output.get("seq")
        if (patches is None or not patches) and invocation is not None:
            recovered = _recover_patch(invocation.input_json)
            if recovered is not None:
                patches = recovered.get("patches")
                if canvas_id is None and recovered.get("canvas_id") is not None:
                    canvas_id = str(recovered.get("canvas_id"))
                recovered_seq = recovered.get("seq")
                if seq is None and isinstance(recovered_seq, (int, float)):
                    seq = int(recovered_seq)

        result_map: dict[str, Any] = {"isFinal": True}
        if patches is not None:
            result_map["patches"] = patches
        if _is_not_blank(canvas_id):
            result_map["canvas_id"] = canvas_id
        if seq is not None:
            result_map["seq"] = seq
        self.put_tool_binding_if_present(result_map, invocation)

        return [
            self.build_task_event(
                state,
                invocation,
                "ui_patch",
                self.build_structured_tool_response(invocation, "ui_patch", result_map),
                build_artifact_refs(artifacts),
            )
        ]


def _recover_tree(input_json: str | None) -> Any | None:
    """``GenUiTreeToolInvocationProjector.recoverTree`` — invalid ⇒ null."""
    if _is_blank(input_json):
        return None
    parsed = _parse_json_object(input_json)
    if parsed is None:
        return None
    tree = parsed.get("tree")
    if tree is None:
        tree = parsed
    try:
        return gen_ui_schema.validate_ui_tree(tree)
    except gen_ui_schema.GenUiSchemaError:
        return None


def _recover_patch(input_json: str | None) -> dict[str, Any] | None:
    """``GenUiPatchToolInvocationProjector.recoverPatch`` — validates the whole
    ``input_json`` object as a patch payload; invalid ⇒ null."""
    if _is_blank(input_json):
        return None
    parsed = _parse_json_object(input_json)
    if parsed is None:
        return None
    try:
        return gen_ui_schema.validate_ui_patch(parsed)
    except gen_ui_schema.GenUiSchemaError:
        return None


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


class ToolInvocationProjectorRegistry:
    def __init__(
        self,
        projectors: Sequence[AbstractToolInvocationProjector] | None = None,
        default_projector: AbstractToolInvocationProjector | None = None,
        user_question_reader: UserQuestionReader | None = None,
    ) -> None:
        self._projectors = list(
            projectors or _default_projectors(user_question_reader)
        )
        self._default_projector = default_projector or DefaultToolInvocationProjector()

    def project(
        self,
        invocation: ToolInvocationView,
        artifacts: Sequence[ArtifactView],
        state: EventResult,
        reuse_current_task_group: bool = False,
    ) -> list[ProjectedReplayEvent]:
        tool_name = None if invocation is None else invocation.tool_name
        if not reuse_current_task_group and not self._supports_planner_task_grouping(
            invocation
        ):
            state.renew_task_id()
        for projector in self._projectors:
            if projector.supports(tool_name):
                return projector.project(invocation, artifacts, state)
        return self._default_projector.project(invocation, artifacts, state)

    @staticmethod
    def _supports_planner_task_grouping(
        invocation: ToolInvocationView | None,
    ) -> bool:
        return invocation is not None and invocation.tool_name == "planning"


def _default_projectors(
    user_question_reader: UserQuestionReader | None = None,
) -> list[AbstractToolInvocationProjector]:
    return [
        AskUserQuestionToolInvocationProjector(user_question_reader),
        CanvasPublishToolInvocationProjector(),
        CodeInterpreterToolInvocationProjector(),
        DataAnalysisToolInvocationProjector(),
        DeepSearchToolInvocationProjector(),
        GenUiTreeToolInvocationProjector(),
        GenUiPatchToolInvocationProjector(),
        ImageGenerationToolInvocationProjector(),
        MultiModalToolInvocationProjector(),
    ]


__all__ = [
    "AbstractToolInvocationProjector",
    "AskUserQuestionToolInvocationProjector",
    "CanvasPublishToolInvocationProjector",
    "CodeInterpreterToolInvocationProjector",
    "DataAnalysisToolInvocationProjector",
    "DeepSearchToolInvocationProjector",
    "DefaultToolInvocationProjector",
    "GenUiPatchToolInvocationProjector",
    "GenUiTreeToolInvocationProjector",
    "ImageGenerationToolInvocationProjector",
    "MultiModalToolInvocationProjector",
    "ToolInvocationProjectorRegistry",
    "UserQuestionReader",
    "UserQuestionRecord",
    "build_artifact_refs",
    "merge_file_refs",
    "read_map",
]
