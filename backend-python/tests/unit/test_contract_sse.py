from __future__ import annotations

import asyncio

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


def test_compare_sse_additive_field_policy_matches_http() -> None:
    golden = [SseEvent(kind="event", event="done", data={"a": 1})]
    added = [SseEvent(kind="event", event="done", data={"a": 1, "extra": 2})]
    removed = [SseEvent(kind="event", event="done", data={"a": 1})]
    removed_golden = [SseEvent(kind="event", event="done", data={"a": 1, "gone": 2})]

    assert compare_sse(golden, added)[0].reason == "field mismatch"
    assert compare_sse(golden, added, ignored_json_pointers=("/extra",)) == []
    assert compare_sse(removed_golden, removed, ignored_json_pointers=("/gone",))[0].reason == (
        "field mismatch"
    )


def test_sse_compare_reports_status_drift() -> None:
    event = SseEvent(kind="event", event="done", data={"ok": True})
    java = SseCapture(200, "text/event-stream", (event,), "eof")
    python = SseCapture(503, "text/event-stream", (event,), "http-error", "HTTPStatusError")

    differences = compare_sse_capture(java, python)

    assert differences[0].path == "/status_code"
    assert differences[0].reason == "value mismatch"


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


@pytest.mark.asyncio
async def test_capture_sse_times_out_and_records_termination() -> None:
    """A real capture against a server that never ends the stream."""

    finished = asyncio.Event()
    writers: list[asyncio.StreamWriter] = []

    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        del reader
        writers.append(writer)
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"\r\n"
            b"data: partial\n\n"
        )
        await writer.drain()
        await finished.wait()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    assert server.sockets is not None
    host, port = server.sockets[0].getsockname()[:2]
    try:
        async with httpx.AsyncClient(
            base_url=f"http://{host}:{port}",
            timeout=5.0,
            # Real socket: trust_env would route 127.0.0.1 via the system proxy.
            trust_env=False,
        ) as client:
            captured = await capture_sse(client, "GET", "/stream", timeout_seconds=0.5)
    finally:
        finished.set()
        for writer in writers:
            writer.close()
        server.close()
        await server.wait_closed()

    assert captured.status_code == 200
    assert captured.termination == "timeout"
    assert captured.error_type == "TimeoutError"


@pytest.mark.asyncio
async def test_capture_sse_records_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        captured = await capture_sse(client, "GET", "/stream")

    assert captured.status_code is None
    assert captured.termination == "transport-error"
    assert captured.error_type == "ConnectError"
    assert captured.events == ()


@pytest.mark.asyncio
async def test_capture_sse_records_http_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="boom")
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        captured = await capture_sse(client, "GET", "/stream")

    assert captured.status_code == 500
    assert captured.termination == "http-error"
    assert captured.error_type is None


@pytest.mark.asyncio
async def test_capture_sse_records_size_limit() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text='data: {"pad":"' + "x" * 200 + '"}\n\n',
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        captured = await capture_sse(client, "GET", "/stream", max_bytes=16)

    assert captured.termination == "size-limit"
    assert captured.error_type is None
