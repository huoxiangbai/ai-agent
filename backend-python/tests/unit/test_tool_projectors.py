"""Tool-projector frame-family tests.

Pins the **inner key order** of every ``resultMap`` / ``toolResult`` family to the
Java ``LinkedHashMap`` insertion order, plus the shared envelope, artifact-ref and
file-ref merge semantics (``ArtifactRelativePath``, ``markMissingLinks``).
JSON key order is part of the wire contract — a reordered dict is a diff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reactor_backend.domain.gen_ui_schema import (
    GenUiSchemaError,
    validate_ui_patch,
    validate_ui_tree,
)
from reactor_backend.domain.ledger_types import (
    ArtifactView,
    EventResult,
    ToolInvocationView,
)
from reactor_backend.domain.tool_projectors import (
    AskUserQuestionToolInvocationProjector,
    CanvasPublishToolInvocationProjector,
    CodeInterpreterToolInvocationProjector,
    DataAnalysisToolInvocationProjector,
    DeepSearchToolInvocationProjector,
    DefaultToolInvocationProjector,
    GenUiPatchToolInvocationProjector,
    GenUiTreeToolInvocationProjector,
    ImageGenerationToolInvocationProjector,
    MultiModalToolInvocationProjector,
    ToolInvocationProjectorRegistry,
    UserQuestionRecord,
    build_artifact_refs,
    merge_file_refs,
)


def _invocation(**overrides: Any) -> ToolInvocationView:
    base: dict[str, Any] = {
        "id": 1,
        "run_id": 101,
        "tool_call_id": "call-1",
        "tool_name": "code_interpreter",
        "input_json": '{"a":1}',
        "llm_observation": "observation text",
        "started_at": datetime(2026, 1, 1, 9, 0, 0),
        "finished_at": datetime(2026, 1, 1, 9, 0, 5),
    }
    base.update(overrides)
    return ToolInvocationView(**base)


def _artifact(**overrides: Any) -> ArtifactView:
    base: dict[str, Any] = {
        "id": 11,
        "run_id": 101,
        "tool_invocation_id": 1,
        "artifact_role": "output",
        "visibility": "visible",
        "storage_key": "storage-1",
        "file_name": "result.txt",
        "mime_type": "text/plain",
        "file_size": 42,
        "preview_url": "https://cdn/preview",
        "download_url": "https://cdn/download",
    }
    base.update(overrides)
    return ArtifactView(**base)


def _project(projector: Any, invocation: Any, artifacts: Any = ()) -> list[Any]:
    return projector.project(invocation, list(artifacts), EventResult())


# ---------------------------------------------------------------------------
# shared envelope / artifactRefs / fileRef merge
# ---------------------------------------------------------------------------


class TestSharedEnvelope:
    def test_envelope_key_order_is_java_insertion_order(self) -> None:
        events = _project(
            DefaultToolInvocationProjector(),
            _invocation(tool_name="unknown_tool", parent_tool_call_id="parent-9"),
        )
        assert len(events) == 1
        response = events[0].result_map
        assert list(response.keys()) == [
            "requestId",
            "messageId",
            "messageTime",
            "messageType",
            "isFinal",
            "finish",
            "toolResult",
            "parentToolUseId",
            "resultMap",
        ]
        assert response["messageType"] == "tool_result"
        assert response["isFinal"] is True
        assert response["finish"] is False

    def test_tool_result_map_key_order(self) -> None:
        events = _project(
            DefaultToolInvocationProjector(),
            _invocation(tool_name="unknown_tool"),
        )
        tool_result = events[0].result_map["toolResult"]
        # putToolBindingIfPresent appends toolCallId after the three literal keys
        # and overwrites toolName in place, so it stays first.
        assert list(tool_result.keys()) == [
            "toolName",
            "toolParam",
            "toolResult",
            "toolCallId",
        ]
        assert tool_result["toolResult"] == "observation text"

    def test_default_falls_back_to_error_msg_when_observation_blank(self) -> None:
        events = _project(
            DefaultToolInvocationProjector(),
            _invocation(
                tool_name="unknown_tool",
                llm_observation="   ",
                error_msg="boom",
            ),
        )
        assert events[0].result_map["toolResult"]["toolResult"] == "boom"

    def test_subagent_nesting_tags_mirror_to_inner_and_outer(self) -> None:
        events = _project(
            DefaultToolInvocationProjector(),
            _invocation(
                tool_name="unknown_tool",
                parent_tool_call_id="parent-1",
                sub_agent_id="agent-1",
                sub_agent_description="desc",
                agent_name="subagent:planner",
            ),
        )
        response = events[0].result_map
        assert list(response.keys()) == [
            "requestId",
            "messageId",
            "messageTime",
            "messageType",
            "isFinal",
            "finish",
            "toolResult",
            "parentToolUseId",
            "subAgentId",
            "subAgentType",
            "subAgentDescription",
            "resultMap",
        ]
        nested = response["resultMap"]
        assert nested["subAgentType"] == "planner"
        assert nested["parentToolUseId"] == "parent-1"


class TestArtifactRefs:
    def test_artifact_ref_key_order_including_relative_path(self) -> None:
        artifact = _artifact(metadata_json='{"relativePath":"out/result.txt"}')
        refs = build_artifact_refs([artifact])
        assert list(refs[0].keys()) == [
            "resourceKey",
            "name",
            "previewUrl",
            "downloadUrl",
            "fileName",
            "relativePath",
            "originFileName",
            "mimeType",
            "size",
            "missing",
        ]
        assert refs[0]["relativePath"] == "out/result.txt"
        assert refs[0]["originFileName"] == "out/result.txt"

    def test_origin_filename_used_only_when_it_contains_a_separator(self) -> None:
        with_sep = build_artifact_refs(
            [_artifact(metadata_json='{"originFileName":"deep/dir/f.txt"}')]
        )
        assert with_sep[0]["relativePath"] == "deep/dir/f.txt"

        # No separator ⇒ metadata source ignored, falls back to fileName.
        plain = build_artifact_refs(
            [
                _artifact(
                    file_name="real.txt",
                    metadata_json='{"originFileName":"plain.txt"}',
                )
            ]
        )
        assert plain[0]["relativePath"] == "real.txt"

    def test_description_workspace_prefix_is_stripped(self) -> None:
        artifact = _artifact(
            metadata_json='{"description":"workspace:a/b/c.md"}',
            file_name="c.md",
        )
        refs = build_artifact_refs([artifact])
        assert refs[0]["relativePath"] == "a/b/c.md"

    def test_relative_path_is_workspace_normalized(self) -> None:
        # normalizeWorkspacePath: backslash→slash, trim, strip leading "./" and
        # leading "/" — it does NOT collapse interior duplicate slashes.
        artifact = _artifact(metadata_json='{"relativePath":"  ./nested\\\\x.txt  "}')
        refs = build_artifact_refs([artifact])
        assert refs[0]["relativePath"] == "nested/x.txt"

        absolute = build_artifact_refs(
            [_artifact(metadata_json='{"relativePath":"/top/y.txt"}')]
        )
        assert absolute[0]["relativePath"] == "top/y.txt"

    def test_missing_metadata_falls_back_to_normalized_file_name(self) -> None:
        # resolve() always yields a path when fileName is non-blank, so putOn
        # emits the relativePath/originFileName pair in that case too.
        refs = build_artifact_refs([_artifact(file_name="solo.txt")])
        assert refs[0]["relativePath"] == "solo.txt"
        assert refs[0]["originFileName"] == "solo.txt"

    def test_resource_key_falls_back_to_file_name_when_storage_key_blank(self) -> None:
        artifact = _artifact(storage_key="   ", file_name="fallback.txt")
        refs = build_artifact_refs([artifact])
        assert refs[0]["resourceKey"] == "fallback.txt"

    def test_empty_artifacts_yield_empty_list(self) -> None:
        assert build_artifact_refs([]) == []
        assert build_artifact_refs(None) == []


class TestMergeFileRefs:
    def test_file_refs_only_no_missing_link_scan(self) -> None:
        merged = merge_file_refs(
            [{"fileName": "a.txt", "downloadUrl": ""}], artifacts=None
        )
        # Java returns early when artifacts are empty — no markMissingLinks.
        assert list(merged[0].keys()) == ["fileName", "missing"]
        assert merged[0]["missing"] is False
        assert "missingReason" not in merged[0]

    def test_artifacts_only_uses_artifact_info_shape(self) -> None:
        merged = merge_file_refs(None, [_artifact()])
        # toArtifactInfo puts raw (possibly null) URLs, then putOn appends the
        # relativePath pair, then fileSize.
        assert list(merged[0].keys()) == [
            "fileName",
            "downloadUrl",
            "previewUrl",
            "ossUrl",
            "domainUrl",
            "missing",
            "relativePath",
            "originFileName",
            "fileSize",
        ]
        assert merged[0]["ossUrl"] == "https://cdn/download"
        assert merged[0]["domainUrl"] == "https://cdn/preview"
        assert merged[0]["relativePath"] == "result.txt"

    def test_enrich_and_mark_missing_when_both_present(self) -> None:
        merged = merge_file_refs(
            [{"fileName": "result.txt", "downloadUrl": "https://cdn/direct"}],
            [_artifact()],
        )
        # toToolFileInfo emits fileName/URLs/missing; enrichFromArtifacts then
        # putIfAbsent-appends the rest (putIfAbsent never reorders).
        assert list(merged[0].keys()) == [
            "fileName",
            "downloadUrl",
            "missing",
            "previewUrl",
            "ossUrl",
            "domainUrl",
            "relativePath",
            "originFileName",
            "fileSize",
        ]
        # putIfAbsent keeps the direct downloadUrl and fills the rest.
        assert merged[0]["downloadUrl"] == "https://cdn/direct"
        assert merged[0]["previewUrl"] == "https://cdn/preview"
        assert merged[0]["missing"] is False

    def test_unmatched_file_name_is_marked_missing(self) -> None:
        merged = merge_file_refs(
            [{"fileName": "ghost.txt", "downloadUrl": ""}], [_artifact()]
        )
        assert merged[0]["missing"] is True
        assert merged[0]["missingReason"] == "artifact_not_found"

    def test_json_null_url_counts_as_present(self) -> None:
        # enrichFromArtifacts putIfAbsent can insert a JSON null URL from a
        # matched artifact. markMissingLinks then does
        # String.valueOf(getOrDefault(...)) → the literal "null", which
        # isNotBlank() treats as a real URL. Must NOT be flagged missing.
        merged = merge_file_refs(
            [{"fileName": "result.txt"}],
            [
                _artifact(
                    file_name="result.txt",
                    preview_url=None,
                    download_url=None,
                    file_size=None,
                )
            ],
        )
        assert merged[0]["previewUrl"] is None
        assert merged[0]["downloadUrl"] is None
        assert merged[0]["missing"] is False
        assert "missingReason" not in merged[0]

    def test_tool_file_info_key_order_drops_mime_type(self) -> None:
        merged = merge_file_refs(
            [
                {
                    "fileName": "a.png",
                    "mimeType": "image/png",
                    "relativePath": "in/a.png",
                    "downloadUrl": "https://d",
                    "previewUrl": "https://p",
                    "ossUrl": "https://o",
                    "domainUrl": "https://h",
                    "fileSize": 7,
                }
            ],
            None,
        )
        assert list(merged[0].keys()) == [
            "fileName",
            "relativePath",
            "originFileName",
            "downloadUrl",
            "previewUrl",
            "ossUrl",
            "domainUrl",
            "missing",
            "fileSize",
        ]
        assert "mimeType" not in merged[0]


# ---------------------------------------------------------------------------
# per-family resultMap key order
# ---------------------------------------------------------------------------


class TestCodeInterpreter:
    def test_result_map_key_order(self) -> None:
        events = _project(
            CodeInterpreterToolInvocationProjector(),
            _invocation(
                structured_output={
                    "codeOutput": "out",
                    "content": "c",
                    "code": "print(1)",
                    "explain": "why",
                    "fileRefs": [],
                }
            ),
            [_artifact()],
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "codeOutput",
            "data",
            "content",
            "code",
            "explain",
            "fileInfo",
            "toolCallId",
            "toolName",
        ]
        assert inner["data"] == inner["codeOutput"] == "out"

    def test_blank_code_output_falls_back_to_llm_observation(self) -> None:
        events = _project(
            CodeInterpreterToolInvocationProjector(),
            _invocation(structured_output={"codeOutput": "  "}),
        )
        inner = events[0].result_map["resultMap"]
        assert inner["codeOutput"] == "observation text"
        assert list(inner.keys()) == [
            "isFinal",
            "codeOutput",
            "data",
            "fileInfo",
            "toolCallId",
            "toolName",
        ]


class TestCanvasPublish:
    def test_result_map_key_order(self) -> None:
        events = _project(
            CanvasPublishToolInvocationProjector(),
            _invocation(
                tool_name="canvas_publish",
                structured_output={
                    "title": "T",
                    "primaryFileName": "index.html",
                    "previewUrl": "https://p",
                    "downloadUrl": "https://d",
                    "fileRefs": [],
                }
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "fileType",
            "command",
            "title",
            "primaryFileName",
            "previewUrl",
            "downloadUrl",
            "fileInfo",
            "toolCallId",
            "toolName",
        ]
        assert inner["fileType"] == "html"
        assert inner["command"] == "发布画布"
        assert events[0].result_map["messageType"] == "html"

    def test_optional_keys_omitted_when_blank(self) -> None:
        events = _project(
            CanvasPublishToolInvocationProjector(),
            _invocation(tool_name="canvas_publish", structured_output=None),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "fileType",
            "command",
            "fileInfo",
            "toolCallId",
            "toolName",
        ]


class TestDataAnalysis:
    def test_result_map_key_order_with_always_on_task_and_data(self) -> None:
        events = _project(
            DataAnalysisToolInvocationProjector(),
            _invocation(
                tool_name="data_analysis",
                structured_output={"task": "analyze", "content": "body"},
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "task",
            "data",
            "fileInfo",
            "toolCallId",
            "toolName",
        ]
        assert inner["task"] == "analyze"
        assert inner["data"] == "body"

    def test_task_and_data_never_omitted(self) -> None:
        events = _project(
            DataAnalysisToolInvocationProjector(),
            _invocation(
                tool_name="data_analysis",
                structured_output={"task": "", "content": ""},
                llm_observation="fallback body",
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert inner["task"] == ""
        assert inner["data"] == "fallback body"


class TestMultiModal:
    def test_result_map_key_order_summary_after_file_info(self) -> None:
        events = _project(
            MultiModalToolInvocationProjector(),
            _invocation(
                tool_name="multimodalagent_tool",
                structured_output={
                    "markdownContent": "# hi",
                    "summary": "sum",
                    "fileRefs": [],
                }
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "data",
            "fileInfo",
            "summary",
            "toolCallId",
            "toolName",
        ]
        assert inner["data"] == "# hi"

    def test_summary_omitted_when_blank(self) -> None:
        events = _project(
            MultiModalToolInvocationProjector(),
            _invocation(
                tool_name="multimodalagent_tool",
                structured_output={"markdownContent": "m", "summary": "  "},
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert "summary" not in inner


class TestImageGeneration:
    def test_two_frames_file_then_tool_result(self) -> None:
        events = _project(
            ImageGenerationToolInvocationProjector(),
            _invocation(
                tool_name="image_generation_tool",
                structured_output={"summary": "made one", "fileRefs": [
                    {"fileName": "a.png", "downloadUrl": "https://d", "previewUrl": "https://p"}
                ]},
            ),
            [_artifact(file_name="a.png")],
        )
        assert [e.message_id.rsplit(":", 1)[-1] for e in events] == [
            "file",
            "tool_result",
        ]
        file_inner = events[0].result_map["resultMap"]
        assert list(file_inner.keys()) == [
            "command",
            "fileInfo",
            "toolCallId",
            "toolName",
        ]
        assert file_inner["command"] == "生成图片"
        tool_result = events[1].result_map["toolResult"]
        assert list(tool_result.keys()) == [
            "toolName",
            "toolParam",
            "toolResult",
            "toolCallId",
        ]
        assert tool_result["toolResult"] == "made one"
        # Frame B carries empty artifactRefs → serialized as null.
        assert events[1].artifact_refs is None

    def test_file_frame_skipped_when_merged_file_info_empty(self) -> None:
        events = _project(
            ImageGenerationToolInvocationProjector(),
            _invocation(
                tool_name="image_generation_tool",
                structured_output={"summary": "s", "fileRefs": []},
            ),
            [],
        )
        assert len(events) == 1
        assert events[0].message_id.endswith(":tool_result")

    def test_summary_falls_back_to_llm_observation(self) -> None:
        events = _project(
            ImageGenerationToolInvocationProjector(),
            _invocation(
                tool_name="image_generation_tool",
                structured_output={"summary": ""},
                llm_observation="from llm",
            ),
            [],
        )
        assert events[0].result_map["toolResult"]["toolResult"] == "from llm"


class TestAskUserQuestion:
    def test_supports_is_case_insensitive(self) -> None:
        projector = AskUserQuestionToolInvocationProjector()
        assert projector.supports("AskUserQuestion")
        assert projector.supports("askuserquestion")
        assert not projector.supports("ask_user")

    def test_payload_key_order_without_is_final(self) -> None:
        events = _project(
            AskUserQuestionToolInvocationProjector(),
            _invocation(
                tool_name="AskUserQuestion",
                input_json='{"questions":[{"id":"q1"}]}',
                llm_observation='{"questionId":"qid-1","answers":{"q1":"yes"}}',
            ),
        )
        inner = events[0].result_map["resultMap"]
        # No isFinal — AskUserQuestion payload is a different shape.
        assert list(inner.keys()) == [
            "messageType",
            "questions",
            "input",
            "answers",
            "status",
            "questionId",
            "toolCallId",
            "toolName",
        ]
        assert inner["messageType"] == "ask_user_question"
        assert inner["status"] == "answered"
        assert inner["questionId"] == "qid-1"

    def test_reads_input_and_observation_never_structured_output(self) -> None:
        events = _project(
            AskUserQuestionToolInvocationProjector(),
            _invocation(
                tool_name="AskUserQuestion",
                input_json='{"questions":[{"id":"q1"}]}',
                llm_observation="{}",
                structured_output={"questions": [{"id": "IGNORED"}], "answer": "x"},
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert inner["questions"] == [{"id": "q1"}]
        assert inner["status"] == "pending"
        assert "answers" not in inner
        assert "isFinal" not in inner

    def test_non_map_answers_dropped_and_status_pending(self) -> None:
        events = _project(
            AskUserQuestionToolInvocationProjector(),
            _invocation(
                tool_name="AskUserQuestion",
                input_json="{}",
                llm_observation='{"answers":"not-a-map"}',
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert "answers" not in inner
        assert inner["status"] == "pending"

    def test_persisted_record_drives_status_and_persistence_status(self) -> None:
        class Stub:
            def find_by_question_id(self, question_id: str) -> UserQuestionRecord | None:
                return UserQuestionRecord(
                    question_id="qid-1",
                    questions=[{"id": "persisted"}],
                    answers={"q1": "a"},
                    status="RESUME_PENDING",
                )

            def list_open_by_session_id(self, session_id: str) -> list[Any]:
                return []

        events = _project(
            AskUserQuestionToolInvocationProjector(Stub()),
            _invocation(
                tool_name="AskUserQuestion",
                session_id="session-1",
                input_json='{"questions":[{"id":"input"}]}',
                llm_observation='{"questionId":"qid-1"}',
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "messageType",
            "questions",
            "input",
            "answers",
            "status",
            "persistenceStatus",
            "questionId",
            "toolCallId",
            "toolName",
        ]
        assert inner["questions"] == [{"id": "persisted"}]
        assert inner["status"] == "answered"
        assert inner["persistenceStatus"] == "RESUME_PENDING"


class TestDeepSearch:
    @staticmethod
    def _output(stages: list[Any], chapters: list[Any] | None = None) -> dict[str, Any]:
        return {
            "query": "main query",
            "answerSummary": "summary",
            "stages": stages,
            "chapters": chapters or [],
        }

    def test_missing_stages_yields_zero_frames(self) -> None:
        for output in (None, {"stages": []}, {"stages": None}):
            events = _project(
                DeepSearchToolInvocationProjector(),
                _invocation(tool_name="deep_search", structured_output=output),
            )
            assert events == []

    def test_unknown_or_blank_stage_skipped(self) -> None:
        events = _project(
            DeepSearchToolInvocationProjector(),
            _invocation(
                tool_name="deep_search",
                structured_output=self._output(
                    [{"stage": "mystery"}, {"stage": "  "}, {"stage": "extend", "queries": []}]
                ),
            ),
        )
        assert len(events) == 1

    def test_extend_result_key_order(self) -> None:
        events = _project(
            DeepSearchToolInvocationProjector(),
            _invocation(
                tool_name="deep_search",
                structured_output=self._output(
                    [{"stage": "extend", "queries": ["q1", "q2"]}],
                    chapters=[
                        {
                            "chapterId": "c1",
                            "title": "T",
                            "content": "C",
                            "order": 1,
                            "queries": ["q1"],
                        }
                    ],
                ),
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "messageType",
            "isFinal",
            "searchFinish",
            "query",
            "searchResult",
            "toolCallId",
            "toolName",
        ]
        assert inner["messageType"] == "extend"
        assert inner["searchFinish"] is False
        assert list(inner["searchResult"].keys()) == ["query", "docs", "chapters"]
        assert inner["searchResult"]["query"] == ["q1", "q2"]
        assert inner["searchResult"]["docs"] == []
        chapter = inner["searchResult"]["chapters"][0]
        assert list(chapter.keys()) == [
            "chapterId",
            "chapterTitle",
            "chapterContent",
            "chapterOrder",
            "queries",
        ]

    def test_search_result_key_order_and_doc_content_optional(self) -> None:
        events = _project(
            DeepSearchToolInvocationProjector(),
            _invocation(
                tool_name="deep_search",
                structured_output=self._output(
                    [
                        {
                            "stage": "search",
                            "results": [
                                {
                                    "query": "sub",
                                    "docs": [
                                        {"title": "t", "link": "l", "summary": "s"},
                                        {"title": "t2", "link": "l2", "summary": ""},
                                    ],
                                }
                            ],
                        }
                    ]
                ),
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "messageType",
            "isFinal",
            "searchFinish",
            "query",
            "searchResult",
            "toolCallId",
            "toolName",
        ]
        assert inner["searchFinish"] is True
        docs = inner["searchResult"]["docs"][0]
        assert list(docs[0].keys()) == ["title", "link", "content"]
        assert list(docs[1].keys()) == ["title", "link"]

    def test_chapter_summary_result_key_order_without_chapters(self) -> None:
        events = _project(
            DeepSearchToolInvocationProjector(),
            _invocation(
                tool_name="deep_search",
                structured_output=self._output(
                    [
                        {
                            "stage": "chapter_summary",
                            "queries": ["seed"],
                            "chapterId": "c1",
                            "chapterTitle": "T",
                            "chapterContent": None,
                            "chapterOrder": 2,
                            "chapterSummary": "CS",
                            "results": [{"query": "seed"}, {"query": "extra"}],
                        }
                    ]
                ),
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "messageType",
            "isFinal",
            "searchFinish",
            "query",
            "chapterId",
            "chapterTitle",
            "chapterContent",
            "chapterOrder",
            "chapterSummary",
            "answer",
            "searchResult",
            "toolCallId",
            "toolName",
        ]
        # defaultString(str, default) replaces null only → falls back to chapterTitle.
        assert inner["chapterContent"] == "T"
        assert inner["answer"] == "CS"
        assert list(inner["searchResult"].keys()) == ["query", "docs"]
        assert "chapters" not in inner["searchResult"]
        # queries copy + unique appends from results.
        assert inner["searchResult"]["query"] == ["seed", "extra"]

    def test_report_result_key_order_and_artifact_filter(self) -> None:
        events = _project(
            DeepSearchToolInvocationProjector(),
            _invocation(
                tool_name="deep_search",
                structured_output=self._output(
                    [{"stage": "report", "answer": "final answer"}]
                ),
            ),
            [
                _artifact(file_name="report.md"),
                _artifact(file_name="x_SEARCH_RESULT.TXT"),
                _artifact(file_name="   "),
            ],
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "messageType",
            "isFinal",
            "query",
            "answer",
            "toolCallId",
            "toolName",
        ]
        assert "searchFinish" not in inner
        assert "searchResult" not in inner
        assert inner["answer"] == "final answer"
        # Only non-blank fileName not ending _search_result.txt survives.
        assert [ref["fileName"] for ref in events[0].artifact_refs or []] == ["report.md"]

    def test_non_report_stages_carry_empty_artifact_refs(self) -> None:
        events = _project(
            DeepSearchToolInvocationProjector(),
            _invocation(
                tool_name="deep_search",
                structured_output=self._output(
                    [{"stage": "extend", "queries": []}, {"stage": "report", "answer": "a"}]
                ),
            ),
            [_artifact(file_name="report.md")],
        )
        assert events[0].artifact_refs is None
        assert events[1].artifact_refs is not None


class TestGenUi:
    def test_ui_tree_result_map_key_order(self) -> None:
        events = _project(
            GenUiTreeToolInvocationProjector(),
            _invocation(
                tool_name="emit_ui_tree",
                structured_output={
                    "tree": {"nodeId": "n1", "kind": "Card", "props": {}, "children": []},
                    "canvasId": "canvas-9",
                },
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "tree",
            "canvas_id",
            "toolCallId",
            "toolName",
        ]
        assert inner["canvas_id"] == "canvas-9"

    def test_ui_tree_recovers_from_input_json_when_output_missing(self) -> None:
        events = _project(
            GenUiTreeToolInvocationProjector(),
            _invocation(
                tool_name="emit_ui_tree",
                structured_output=None,
                input_json='{"tree":{"nodeId":"n1","kind":"Card"}}',
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == ["isFinal", "tree", "toolCallId", "toolName"]
        # canvas_id is NOT recovered from input_json.
        assert "canvas_id" not in inner
        root = inner["tree"]["root"]
        assert root["kind"] == "Card"
        assert root["nodeId"] == "n1"

    def test_ui_tree_invalid_recovery_omits_tree(self) -> None:
        events = _project(
            GenUiTreeToolInvocationProjector(),
            _invocation(
                tool_name="emit_ui_tree",
                structured_output=None,
                input_json='{"tree":{"kind":"NotAllowedKind"}}',
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == ["isFinal", "toolCallId", "toolName"]

    def test_ui_patch_result_map_key_order(self) -> None:
        events = _project(
            GenUiPatchToolInvocationProjector(),
            _invocation(
                tool_name="emit_ui_patch",
                structured_output={
                    "patches": [{"op": "remove", "path": "/a"}],
                    "canvasId": "c1",
                    "seq": 3,
                },
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert list(inner.keys()) == [
            "isFinal",
            "patches",
            "canvas_id",
            "seq",
            "toolCallId",
            "toolName",
        ]
        assert inner["seq"] == 3

    def test_ui_patch_recovers_from_input_json(self) -> None:
        events = _project(
            GenUiPatchToolInvocationProjector(),
            _invocation(
                tool_name="emit_ui_patch",
                structured_output={"patches": []},
                input_json=(
                    '{"patches":[{"op":"replace","path":"/x","value":1}],'
                    '"canvas_id":"from-input","seq":7}'
                ),
            ),
        )
        inner = events[0].result_map["resultMap"]
        assert inner["patches"] == [{"op": "replace", "path": "/x", "value": 1}]
        assert inner["canvas_id"] == "from-input"
        assert inner["seq"] == 7


class TestGenUiSchema:
    def test_normalize_node_hoists_props_and_lifts_aliases(self) -> None:
        envelope = validate_ui_tree(
            {"nodeId": "n1", "kind": "Button", "label": "Go", "href": "/home"}
        )
        root = envelope["root"]
        assert list(root.keys()) == ["nodeId", "kind", "props", "children"]
        assert root["props"]["label"] == "Go"
        assert root["props"]["value"] == "Go"
        assert root["props"]["url"] == "/home"

    def test_unknown_kind_rejected(self) -> None:
        try:
            validate_ui_tree({"kind": "Nope"})
        except GenUiSchemaError:
            return
        raise AssertionError("expected GenUiSchemaError")

    def test_patch_requires_value_unless_remove(self) -> None:
        assert validate_ui_patch({"patches": [{"op": "remove", "path": "/a"}]}) == {
            "patches": [{"op": "remove", "path": "/a"}]
        }
        try:
            validate_ui_patch({"patches": [{"op": "add", "path": "/a"}]})
        except GenUiSchemaError:
            return
        raise AssertionError("expected GenUiSchemaError")


class TestRegistry:
    def test_registry_dispatches_and_renews_task_id(self) -> None:
        registry = ToolInvocationProjectorRegistry()
        state = EventResult()
        events = registry.project(
            _invocation(tool_name="canvas_publish", structured_output=None),
            [],
            state,
        )
        assert events[0].result_map["messageType"] == "html"
        assert events[0].task_order == 1

        events2 = registry.project(
            _invocation(tool_name="unknown_tool"), [], state
        )
        # Non-planning tools renew the task id and reset taskOrder to 1.
        assert events2[0].task_order == 1
        assert events2[0].task_id != events[0].task_id

    def test_planning_tool_reuses_task_group(self) -> None:
        registry = ToolInvocationProjectorRegistry()
        state = EventResult()
        first = registry.project(_invocation(tool_name="planning"), [], state)
        second = registry.project(_invocation(tool_name="planning"), [], state)
        assert second[0].task_id == first[0].task_id
