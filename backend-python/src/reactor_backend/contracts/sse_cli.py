from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from reactor_backend.contracts.models import JsonValue
from reactor_backend.contracts.sse import capture_sse, compare_sse_capture


async def _run(arguments: argparse.Namespace, body: JsonValue) -> tuple[dict[str, object], int]:
    timeout = httpx.Timeout(arguments.timeout + 5, connect=5.0)
    headers = dict(item.split(":", 1) for item in arguments.header)
    java_url = os.environ.get("JAVA_BASE_URL", "http://127.0.0.1:8100")
    python_url = os.environ.get("PYTHON_BASE_URL", "http://127.0.0.1:8200")
    async with (
        httpx.AsyncClient(base_url=java_url, timeout=timeout, headers=headers) as java,
        httpx.AsyncClient(base_url=python_url, timeout=timeout, headers=headers) as python,
    ):
        java_capture, python_capture = await asyncio.gather(
            capture_sse(
                java,
                arguments.method,
                arguments.path,
                json_body=body,
                timeout_seconds=arguments.timeout,
                max_bytes=arguments.max_bytes,
            ),
            capture_sse(
                python,
                arguments.method,
                arguments.path,
                json_body=body,
                timeout_seconds=arguments.timeout,
                max_bytes=arguments.max_bytes,
            ),
        )
    differences = compare_sse_capture(
        java_capture,
        python_capture,
        ignored_json_pointers=tuple(arguments.ignore_pointer),
    )
    report: dict[str, object] = {
        "path": arguments.path,
        "matched": not differences,
        "java": java_capture.as_dict(),
        "python": python_capture.as_dict(),
        "differences": [item.as_dict() for item in differences],
    }
    return report, 1 if differences else 0


def _json_body(path: Path | None) -> JsonValue:
    if path is None:
        return None
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if value is None or isinstance(value, (bool, int, float, str, list, dict)):
        return value
    raise ValueError("request body must be JSON")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare one Java/Python SSE exchange")
    parser.add_argument("path")
    parser.add_argument("--method", default="POST")
    parser.add_argument("--body", type=Path)
    parser.add_argument("--header", action="append", default=[], metavar="NAME:VALUE")
    parser.add_argument("--ignore-pointer", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--output", type=Path, default=Path("sse-contract-report.json"))
    arguments = parser.parse_args()
    report, exit_code = asyncio.run(_run(arguments, _json_body(arguments.body)))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    raise SystemExit(exit_code)
