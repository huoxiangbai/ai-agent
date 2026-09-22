from __future__ import annotations

import httpx
import pytest

from reactor_backend.contracts.models import SseCapture, SseEvent
from reactor_backend.contracts.sse import (
    capture_sse,
    compare_sse,
    compare_sse_capture,
    parse_sse_text,
)


def test_parse_sse_preserves_heartbeats_order_multiline_and_utf8() -> None:
    payload = (
        ": ping\r\n\r\n"
        "id: 7\n"
        "event: message\n"
        'data: {"text":"你好",\n'
        'data: "done":false}\n\n'
        "event: done\n"
        'data: {"requestId":"random"}\n\n'
    )

    events = parse_sse_text(payload)

    assert events == [
        SseEvent(kind="heartbeat", comment="ping"),
        SseEvent(
            kind="event",
            event="message",
            data={"text": "你好", "done": False},
            event_id="7",
        ),
        SseEvent(kind="event", event="done", data={"requestId": "random"}),
    ]


def test_compare_sse_uses_case_local_json_allowlist() -> None:
    java = [SseEvent(kind="event", event="done", data={"requestId": "java", "ok": True})]
    python = [SseEvent(kind="event", event="done", data={"requestId": "python", "ok": True})]

    assert compare_sse(java, python, ignored_json_pointers=("/requestId",)) == []
    assert compare_sse(java, python)[0].path == "/events/0/data/requestId"


@pytest.mark.asyncio
async def test_capture_sse_records_content_type_utf8_and_normal_eof() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream;charset=UTF-8"},
            text='event: answer\ndata: {"text":"中文"}\n\n',
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        captured = await capture_sse(client, "GET", "/stream")

    assert captured.status_code == 200
    assert captured.content_type == "text/event-stream"
    assert captured.termination == "eof"
    assert captured.events[0].data == {"text": "中文"}


def test_capture_comparison_includes_abnormal_termination() -> None:
    event = SseEvent(kind="event", event="error", data={"code": "MODEL_TIMEOUT"})
    java = SseCapture(200, "text/event-stream", (event,), "eof")
    python = SseCapture(200, "text/event-stream", (event,), "timeout", "TimeoutError")

    differences = compare_sse_capture(java, python)

    assert {difference.path for difference in differences} == {"/termination", "/error_type"}
