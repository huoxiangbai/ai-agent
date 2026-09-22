from __future__ import annotations

import asyncio
import json

import httpx

from reactor_backend.contracts.http import _compare
from reactor_backend.contracts.models import Difference, JsonValue, SseCapture, SseEvent
from reactor_backend.contracts.normalize import normalize_json


def parse_sse_text(payload: str) -> list[SseEvent]:
    events: list[SseEvent] = []
    normalized = payload.replace("\r\n", "\n").replace("\r", "\n")
    for block in normalized.split("\n\n"):
        if not block:
            continue
        comments: list[str] = []
        data_lines: list[str] = []
        event_name: str | None = None
        event_id: str | None = None
        retry: int | None = None
        has_field = False
        for line in block.split("\n"):
            if line.startswith(":"):
                comments.append(line[1:].lstrip())
                continue
            field, separator, raw_value = line.partition(":")
            value = raw_value[1:] if separator and raw_value.startswith(" ") else raw_value
            if field == "event":
                event_name = value
                has_field = True
            elif field == "data":
                data_lines.append(value)
                has_field = True
            elif field == "id":
                event_id = value
                has_field = True
            elif field == "retry":
                try:
                    retry = int(value)
                except ValueError:
                    retry = None
                has_field = True
        for comment in comments:
            events.append(SseEvent(kind="heartbeat", comment=comment))
        if has_field:
            data_text = "\n".join(data_lines)
            data: JsonValue
            try:
                data = json.loads(data_text) if data_text else ""
            except json.JSONDecodeError:
                data = data_text
            events.append(
                SseEvent(
                    kind="event",
                    event=event_name or "message",
                    data=data,
                    event_id=event_id,
                    retry=retry,
                )
            )
    return events


async def capture_sse(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json_body: JsonValue = None,
    timeout_seconds: float = 30.0,
    max_bytes: int = 2_000_000,
) -> SseCapture:
    chunks: list[str] = []
    byte_count = 0
    status_code: int | None = None
    content_type: str | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            async with client.stream(method, path, json=json_body) as response:
                status_code = response.status_code
                raw_content_type = response.headers.get("content-type")
                content_type = (
                    raw_content_type.split(";", 1)[0].strip().lower()
                    if raw_content_type
                    else None
                )
                async for chunk in response.aiter_text():
                    byte_count += len(chunk.encode("utf-8"))
                    if byte_count > max_bytes:
                        return SseCapture(
                            status_code,
                            content_type,
                            tuple(parse_sse_text("".join(chunks))),
                            "size-limit",
                        )
                    chunks.append(chunk)
        termination = "eof" if status_code is not None and status_code < 400 else "http-error"
        return SseCapture(
            status_code,
            content_type,
            tuple(parse_sse_text("".join(chunks))),
            termination,
        )
    except TimeoutError:
        return SseCapture(
            status_code,
            content_type,
            tuple(parse_sse_text("".join(chunks))),
            "timeout",
            "TimeoutError",
        )
    except httpx.HTTPError as exc:
        return SseCapture(
            status_code,
            content_type,
            tuple(parse_sse_text("".join(chunks))),
            "transport-error",
            type(exc).__name__,
        )


def compare_sse(
    java: list[SseEvent],
    python: list[SseEvent],
    *,
    ignored_json_pointers: tuple[str, ...] = (),
) -> list[Difference]:
    java_values = [_normalized_event(event, ignored_json_pointers) for event in java]
    python_values = [_normalized_event(event, ignored_json_pointers) for event in python]
    differences: list[Difference] = []
    _compare("/events", java_values, python_values, differences)
    return differences


def compare_sse_capture(
    java: SseCapture,
    python: SseCapture,
    *,
    ignored_json_pointers: tuple[str, ...] = (),
) -> list[Difference]:
    differences: list[Difference] = []
    _compare("/status_code", java.status_code, python.status_code, differences)
    _compare("/content_type", java.content_type, python.content_type, differences)
    _compare("/termination", java.termination, python.termination, differences)
    _compare("/error_type", java.error_type, python.error_type, differences)
    differences.extend(
        compare_sse(
            list(java.events),
            list(python.events),
            ignored_json_pointers=ignored_json_pointers,
        )
    )
    return differences


def _normalized_event(event: SseEvent, pointers: tuple[str, ...]) -> dict[str, object]:
    value = event.as_dict()
    if isinstance(event.data, (dict, list)):
        value["data"] = normalize_json(event.data, pointers)
    return value
