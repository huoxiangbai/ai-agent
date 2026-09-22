from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from reactor_backend.contracts.http import capture_http, compare_http
from reactor_backend.contracts.manifest import load_cases


async def _record_java(manifest: Path, output: Path) -> int:
    java_url = os.environ.get("JAVA_BASE_URL", "http://127.0.0.1:8100")
    cases, skipped = load_cases(manifest)
    report: dict[str, object] = {
        "mode": "java-baseline",
        "base_url": java_url,
        "cases": [],
        "skipped": skipped,
    }
    failures = 0
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(
        base_url=java_url, timeout=timeout, follow_redirects=False
    ) as java:
        for case in cases:
            case_result: dict[str, object] = {"name": case.name}
            try:
                snapshot = await capture_http(java, case)
                case_result["snapshot"] = snapshot.as_dict()
            except Exception as exc:  # a connection failure belongs in the report
                case_result["error"] = f"{type(exc).__name__}: {exc}"
                failures += 1
            _append_case(report, case_result)
    await asyncio.to_thread(_write_report, output, report)
    return 1 if failures else 0


async def _compare_both(manifest: Path, output: Path) -> int:
    java_url = os.environ.get("JAVA_BASE_URL", "http://127.0.0.1:8100")
    python_url = os.environ.get("PYTHON_BASE_URL", "http://127.0.0.1:8200")
    cases, skipped = load_cases(manifest)
    report: dict[str, object] = {"mode": "comparison", "cases": [], "skipped": skipped}
    failures = 0
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with (
        httpx.AsyncClient(base_url=java_url, timeout=timeout, follow_redirects=False) as java,
        httpx.AsyncClient(base_url=python_url, timeout=timeout, follow_redirects=False) as python,
    ):
        for case in cases:
            case_result: dict[str, object] = {"name": case.name}
            try:
                java_snapshot, python_snapshot = await asyncio.gather(
                    capture_http(java, case), capture_http(python, case)
                )
                differences = compare_http(java_snapshot, python_snapshot)
                case_result.update(
                    {
                        "matched": not differences,
                        "java": java_snapshot.as_dict(),
                        "python": python_snapshot.as_dict(),
                        "differences": [difference.as_dict() for difference in differences],
                    }
                )
                failures += bool(differences)
            except Exception as exc:  # a connection failure belongs in the report
                case_result.update({"matched": False, "error": f"{type(exc).__name__}: {exc}"})
                failures += 1
            _append_case(report, case_result)
    await asyncio.to_thread(_write_report, output, report)
    return 1 if failures else 0


def _append_case(report: dict[str, object], case_result: dict[str, object]) -> None:
    case_entries = report["cases"]
    if isinstance(case_entries, list):
        case_entries.append(case_result)


def _write_report(output: Path, report: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Java and Python API contracts")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("contract-report.json"))
    parser.add_argument(
        "--record-java",
        action="store_true",
        help="capture a sanitized Java-only golden baseline without contacting Python",
    )
    arguments = parser.parse_args()
    runner = _record_java if arguments.record_java else _compare_both
    raise SystemExit(asyncio.run(runner(arguments.manifest, arguments.output)))
