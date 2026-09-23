"""Read-only execution-ledger repository.

SQL text mirrors ``dialogue_{session,run}_ledger_mapper.xml``,
``llm_invocation_ledger_mapper.xml``, ``tool_invocation_ledger_mapper.xml`` and
``artifact_ledger_mapper.xml``. All statements are SELECT-only.

Rich tool output is hydrated from the eight ``ai_agent_tool_output_*`` tables by
``tool_invocation_id`` (``ToolOutputReaderImpl.readByInvocationId`` primary-key
path). The row is projected into the camelCase mapping the replay projectors
read; file refs are re-attached from the run's output artifacts.
"""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from reactor_backend.domain.ledger_types import (
    ArtifactView,
    DialogueRunView,
    DialogueSessionView,
    ExecutionRunDetail,
    LlmInvocationView,
    ToolInvocationView,
)

_SQL_SESSION = text(
    """
    SELECT *
    FROM ai_agent_dialogue_session
    WHERE session_id = :session_id
      AND deleted = 0
    LIMIT 1
    """
)

_SQL_RUNS_BY_SESSION = text(
    """
    SELECT *
    FROM ai_agent_dialogue_run
    WHERE session_id = :session_id
      AND deleted = 0
    ORDER BY create_time ASC, id ASC
    """
)

_SQL_RUN_BY_REQUEST_ID = text(
    """
    SELECT *
    FROM ai_agent_dialogue_run
    WHERE request_id = :request_id
      AND deleted = 0
    LIMIT 1
    """
)

_SQL_LLM_BY_RUN_ID = text(
    """
    SELECT *
    FROM ai_agent_llm_invocation
    WHERE run_id = :run_id
      AND deleted = 0
    ORDER BY invocation_seq ASC, id ASC
    """
)

_SQL_TOOL_BY_RUN_ID = text(
    """
    SELECT *
    FROM ai_agent_tool_invocation
    WHERE run_id = :run_id
      AND deleted = 0
    ORDER BY llm_invocation_id ASC, dispatch_index ASC, id ASC
    """
)

_SQL_ARTIFACT_BY_RUN_ID = text(
    """
    SELECT *
    FROM ai_agent_artifact
    WHERE run_id = :run_id
      AND deleted = 0
    ORDER BY create_time ASC, id ASC
    """
)

# tool_name → (table, camelCase field map). Mirrors ToolOutputReaderImpl's
# primary-key switch; legacy file_tool/report_tool/script_runner/planning are
# deliberately absent (retired output tables are no longer read).
_TOOL_OUTPUT_TABLES: dict[str, tuple[str, dict[str, str]]] = {
    "deep_search": (
        "ai_agent_tool_output_deep_search",
        {"query": "query", "answer_summary": "answerSummary", "stages_json": "stagesJson"},
    ),
    "code_interpreter": (
        "ai_agent_tool_output_code_interpreter",
        {
            "code_output": "codeOutput",
            "content": "content",
            "code": "code",
            "explain": "explain",
        },
    ),
    "data_analysis": (
        "ai_agent_tool_output_data_analysis",
        {"task": "task", "summary": "summary", "content": "content"},
    ),
    "multimodalagent_tool": (
        "ai_agent_tool_output_multimodal_agent",
        {"summary": "summary", "markdown_content": "markdownContent"},
    ),
    "image_generation_tool": (
        "ai_agent_tool_output_image_generation",
        {
            "prompt": "prompt",
            "mode": "mode",
            "summary": "summary",
            "size": "size",
            "batch_count": "batchCount",
            "source_image_count": "sourceImageCount",
            "mask_image_count": "maskImageCount",
            "used_fallback": "usedFallback",
        },
    ),
    "canvas_publish": (
        "ai_agent_tool_output_canvas_publish",
        {
            "title": "title",
            "mode": "mode",
            "primary_file_name": "primaryFileName",
            "preview_url": "previewUrl",
            "download_url": "downloadUrl",
            "open_in_panel": "openInPanel",
            "salvaged": "salvaged",
        },
    ),
    "emit_ui_tree": (
        "ai_agent_tool_output_emit_ui_tree",
        {"canvas_id": "canvasId", "salvaged": "salvaged", "tree_json": "treeJson"},
    ),
    "emit_ui_patch": (
        "ai_agent_tool_output_emit_ui_patch",
        {"canvas_id": "canvasId", "seq": "seq", "patches_json": "patchesJson"},
    ),
}


class _Connectable(Protocol):
    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]: ...


def _get(row: Any, name: str) -> Any:
    try:
        return getattr(row, name)
    except Exception:  # noqa: BLE001 - columns vary across schema snapshots
        return None


def _session_view(row: Any) -> DialogueSessionView:
    return DialogueSessionView(
        id=_get(row, "id"),
        session_id=_get(row, "session_id"),
        visitor_id=_get(row, "visitor_id"),
        title=_get(row, "title"),
        status=_get(row, "status"),
        latest_request_id=_get(row, "latest_request_id"),
        latest_query_text=_get(row, "latest_query_text"),
        latest_summary_text=_get(row, "latest_summary_text"),
        run_count=_get(row, "run_count") or 0,
        finished_run_count=_get(row, "finished_run_count") or 0,
        failed_run_count=_get(row, "failed_run_count") or 0,
        started_at=_get(row, "started_at"),
        last_active_at=_get(row, "last_active_at"),
    )


def _run_view(row: Any) -> DialogueRunView:
    return DialogueRunView(
        id=_get(row, "id"),
        run_uid=_get(row, "run_uid"),
        request_id=_get(row, "request_id"),
        session_id=_get(row, "session_id"),
        visitor_id=_get(row, "visitor_id"),
        entry_agent=_get(row, "entry_agent"),
        status=_get(row, "status"),
        query_text=_get(row, "query_text"),
        final_summary_text=_get(row, "final_summary_text"),
        started_at=_get(row, "started_at"),
        finished_at=_get(row, "finished_at"),
    )


def _llm_view(row: Any) -> LlmInvocationView:
    return LlmInvocationView(
        id=_get(row, "id"),
        run_id=_get(row, "run_id"),
        invocation_seq=_get(row, "invocation_seq"),
        agent_name=_get(row, "agent_name"),
        step_no=_get(row, "step_no"),
        call_kind=_get(row, "call_kind"),
        streaming=_get(row, "streaming"),
        model_name=_get(row, "model_name"),
        response_text=_get(row, "response_text"),
        reasoning_content=_get(row, "reasoning_content"),
        tool_call_count=_get(row, "tool_call_count"),
        prompt_tokens=_get(row, "prompt_tokens"),
        completion_tokens=_get(row, "completion_tokens"),
        total_tokens=_get(row, "total_tokens"),
        est_system_tokens=_get(row, "est_system_tokens"),
        est_tool_tokens=_get(row, "est_tool_tokens"),
        est_message_tokens=_get(row, "est_message_tokens"),
        est_total_tokens=_get(row, "est_total_tokens"),
        status=_get(row, "status"),
        started_at=_get(row, "started_at"),
        finished_at=_get(row, "finished_at"),
    )


def _tool_view(row: Any) -> ToolInvocationView:
    # Column name is ``llm_oberserve`` (schema typo, preserved by MyBatis).
    return ToolInvocationView(
        id=_get(row, "id"),
        run_id=_get(row, "run_id"),
        llm_invocation_id=_get(row, "llm_invocation_id"),
        tool_call_id=_get(row, "tool_call_id"),
        parent_tool_call_id=_get(row, "parent_tool_call_id"),
        tool_name=_get(row, "tool_name"),
        tool_provider=_get(row, "tool_provider"),
        agent_name=_get(row, "agent_name"),
        sub_agent_id=_get(row, "sub_agent_id"),
        sub_agent_type=_get(row, "sub_agent_type"),
        sub_agent_description=_get(row, "sub_agent_description"),
        dispatch_index=_get(row, "dispatch_index"),
        input_json=_get(row, "input_json"),
        llm_observation=_get(row, "llm_oberserve"),
        error_msg=_get(row, "error_msg"),
        status=_get(row, "status"),
        started_at=_get(row, "started_at"),
        finished_at=_get(row, "finished_at"),
    )


def _artifact_view(row: Any) -> ArtifactView:
    return ArtifactView(
        id=_get(row, "id"),
        run_id=_get(row, "run_id"),
        tool_invocation_id=_get(row, "tool_invocation_id"),
        request_id=_get(row, "request_id"),
        tool_call_id=_get(row, "tool_call_id"),
        artifact_role=_get(row, "artifact_role"),
        visibility=_get(row, "visibility"),
        source_type=_get(row, "source_type"),
        storage_key=_get(row, "storage_key"),
        file_name=_get(row, "file_name"),
        mime_type=_get(row, "mime_type"),
        file_size=_get(row, "file_size"),
        preview_url=_get(row, "preview_url"),
        download_url=_get(row, "download_url"),
        metadata_json=_get(row, "metadata_json"),
    )


def _output_file_refs(
    artifacts: list[ArtifactView], tool_invocation_id: int | None
) -> list[dict[str, Any]]:
    """``ToolOutputReaderImpl.resolveFileRefs``: output-role artifacts re-attached
    from the artifact ledger (never embedded in the tool-output JSON).

    Mirrors ``queryOutputArtifactsByToolInvocationId``'s
    ``artifact_role='output' AND visibility='visible'`` predicate. The projected
    ``ToolFileRef`` carries **no** ``relativePath`` (Java's builder never sets it).
    """
    refs: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact is None or tool_invocation_id is None:
            continue
        if artifact.tool_invocation_id != tool_invocation_id:
            continue
        if artifact.artifact_role != "output":
            continue
        if artifact.visibility != "visible":
            continue
        refs.append(
            {
                "fileName": artifact.file_name,
                "downloadUrl": artifact.download_url,
                "previewUrl": artifact.preview_url,
                "ossUrl": artifact.download_url,
                "domainUrl": artifact.preview_url,
                "fileSize": artifact.file_size,
                "mimeType": artifact.mime_type,
            }
        )
    return refs


def _read_json_map(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    text_value = raw if isinstance(raw, str) else str(raw)
    if text_value.strip() == "":
        return None
    try:
        parsed = json.loads(text_value)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(k): v for k, v in parsed.items()}


def _read_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    text_value = raw if isinstance(raw, str) else str(raw)
    if text_value.strip() == "":
        return []
    try:
        parsed = json.loads(text_value)
    except (ValueError, TypeError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


# Java tool-output types that declare a ``fileRefs`` field. deep_search /
# emit_ui_tree / emit_ui_patch deliberately do not (ToolOutputReaderImpl never
# calls resolveFileRefs for them).
_FILE_REF_TOOLS = frozenset(
    {
        "code_interpreter",
        "data_analysis",
        "multimodalagent_tool",
        "image_generation_tool",
        "canvas_publish",
    }
)


def _rebuild_chapters(stages: list[Any]) -> list[dict[str, Any]]:
    """``ToolOutputReaderImpl.rebuildChapters`` — chapters are **rebuilt** from
    ``chapter_summary`` stages (``ai_agent_tool_output_deep_search`` has no
    chapters column). Field names follow ``DeepSearchChapter`` so
    ``buildChapterMetadata`` maps ``title/content/order`` back to
    ``chapterTitle/chapterContent/chapterOrder``."""
    chapters: list[dict[str, Any]] = []
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("stage") != "chapter_summary":
            continue
        docs: list[Any] = []
        for result in stage.get("results") or []:
            if isinstance(result, dict) and result.get("docs") is not None:
                docs.extend(result.get("docs") or [])
        queries = stage.get("queries")
        chapters.append(
            {
                "chapterId": stage.get("chapterId"),
                "title": stage.get("chapterTitle"),
                "content": stage.get("chapterContent"),
                "order": stage.get("chapterOrder"),
                "queries": list(queries) if queries is not None else [],
                "docs": docs,
                "summary": stage.get("chapterSummary"),
                "status": "completed",
            }
        )
    return chapters


class ExecutionLedgerRepository:
    def __init__(self, db: _Connectable) -> None:
        self._db = db

    async def query_session(self, session_id: str) -> DialogueSessionView | None:
        async with self._db.connect() as connection:
            result = await connection.execute(_SQL_SESSION, {"session_id": session_id})
            row = result.first()
            return None if row is None else _session_view(row)

    async def query_session_runs(self, session_id: str) -> list[DialogueRunView]:
        async with self._db.connect() as connection:
            result = await connection.execute(
                _SQL_RUNS_BY_SESSION, {"session_id": session_id}
            )
            return [_run_view(row) for row in result.all()]

    async def query_run_detail(self, request_id: str) -> ExecutionRunDetail | None:
        async with self._db.connect() as connection:
            run_result = await connection.execute(
                _SQL_RUN_BY_REQUEST_ID, {"request_id": request_id}
            )
            run_row = run_result.first()
            if run_row is None:
                return None
            run = _run_view(run_row)
            run_id = run.id
            if run_id is None:
                return ExecutionRunDetail(run=run)

            llm_result = await connection.execute(_SQL_LLM_BY_RUN_ID, {"run_id": run_id})
            tool_result = await connection.execute(_SQL_TOOL_BY_RUN_ID, {"run_id": run_id})
            artifact_result = await connection.execute(
                _SQL_ARTIFACT_BY_RUN_ID, {"run_id": run_id}
            )
            artifacts = [_artifact_view(row) for row in artifact_result.all()]
            tool_invocations = []
            for row in tool_result.all():
                tool = _tool_view(row)
                # ``ToolInvocationView`` carries request/session for the AskUser
                # projector; the tool table has neither column, so both come from
                # the owning run (mirrors ToolInvocationViewMap's join).
                tool.request_id = run.request_id
                tool.session_id = run.session_id
                tool.structured_output = await self._read_tool_output(
                    connection, tool, artifacts
                )
                tool_invocations.append(tool)
            return ExecutionRunDetail(
                run=run,
                llm_invocations=[_llm_view(row) for row in llm_result.all()],
                tool_invocations=tool_invocations,
                artifacts=artifacts,
            )

    async def _read_tool_output(
        self,
        connection: AsyncConnection,
        tool: ToolInvocationView,
        artifacts: list[ArtifactView],
    ) -> dict[str, Any] | None:
        """``ToolOutputReaderImpl.readByInvocationId`` — primary-key path only.

        Unknown tools and missing rows return ``None`` (no structured output);
        blank tool names and null ids short-circuit the same way.
        """
        table_and_fields = _TOOL_OUTPUT_TABLES.get((tool.tool_name or "").strip())
        if table_and_fields is None or tool.id is None:
            return None
        table, fields = table_and_fields
        # Identifiers come from the fixed mapping above (never request data);
        # only the value is bound. Each table lists its own columns because the
        # optional rich blobs differ per table.
        select_list = list(fields.keys())
        if tool.tool_name == "deep_search":
            select_list = ["query", "answer_summary", "stages_json"]
        elif tool.tool_name == "emit_ui_tree":
            select_list = ["canvas_id", "salvaged", "tree_json"]
        elif tool.tool_name == "emit_ui_patch":
            select_list = ["canvas_id", "seq", "patches_json"]
        # `explain` is a MySQL reserved word and needs quoting.
        columns_sql = ", ".join(f"`{name}`" for name in select_list)
        statement = text(
            f"""
            SELECT {columns_sql}
            FROM {table}
            WHERE tool_invocation_id = :tool_invocation_id
            LIMIT 1
            """
        )
        result = await connection.execute(
            statement, {"tool_invocation_id": int(tool.id)}
        )
        row = result.first()
        if row is None:
            return None
        raw = {name: _get(row, name) for name in select_list}
        output: dict[str, Any] = {}
        for source, target in fields.items():
            if source in ("stages_json", "tree_json", "patches_json"):
                continue
            value = raw.get(source)
            if value is not None:
                output[target] = value
        if tool.tool_name == "deep_search":
            # ``ToolOutputReaderImpl.toDeepSearchOutput``: stages from stages_json
            # and chapters REBUILT from ``chapter_summary`` stages (no DB column).
            stages = _read_json_list(raw.get("stages_json"))
            output["stages"] = stages
            output["chapters"] = _rebuild_chapters(stages)
        elif tool.tool_name == "emit_ui_tree":
            tree = _read_json_map(raw.get("tree_json"))
            if tree is not None:
                output["tree"] = tree
        elif tool.tool_name == "emit_ui_patch":
            output["patches"] = _read_json_list(raw.get("patches_json"))
        # Only the five Java output types that declare ``fileRefs`` get them;
        # deep_search / emit_ui_* carry none (their projectors never read them).
        if tool.tool_name in _FILE_REF_TOOLS:
            output["fileRefs"] = _output_file_refs(artifacts, tool.id)
        return output
