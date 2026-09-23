from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from reactor_backend.contracts.http import (
    capture_http,
    compare_http,
    load_capture_file,
    save_capture_file,
)
from reactor_backend.contracts.manifest import load_cases
from reactor_backend.contracts.models import CaptureCase, CaptureFile, HttpCase, HttpSnapshot

_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


async def _record_one(manifest: Path, output: Path, *, side: str) -> int:
    """Capture a sanitized single-side document (``java-baseline``/``python-capture``)."""

    if side == "java":
        base_url = os.environ.get("JAVA_BASE_URL", "http://127.0.0.1:8100")
        mode = "java-baseline"
    else:
        base_url = os.environ.get("PYTHON_BASE_URL", "http://127.0.0.1:8200")
        mode = "python-capture"
    cases, skipped = load_cases(manifest)
    entries: list[CaptureCase] = []
    failures = 0
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=_TIMEOUT,
        follow_redirects=False,
        # Contract tooling only ever talks to a local Java/Python server. Without
        # this, a system-level proxy (macOS network settings, not an env var)
        # hijacks 127.0.0.1 and the recording run fails with a bare disconnect.
        trust_env=False,
    ) as client:
        for case in cases:
            try:
                snapshot = await capture_http(client, case)
                entries.append(CaptureCase(name=case.name, snapshot=snapshot))
            except Exception as exc:  # a connection failure belongs in the report
                entries.append(
                    CaptureCase(name=case.name, error=f"{type(exc).__name__}: {exc}")
                )
                failures += 1
    document = CaptureFile(
        mode=mode,
        base_url=base_url,
        cases=tuple(entries),
        skipped=tuple(skipped),
    )
    await asyncio.to_thread(save_capture_file, output, document)
    return 1 if failures else 0


async def _compare_run(
    manifest: Path,
    output: Path,
    *,
    golden_path: Path | None,
    response_path: Path | None,
) -> int:
    """Compare a candidate side against a reference side.

    Reference is the stored ``--golden`` document when given, otherwise live
    Java. Candidate is the stored ``--response`` document when given, otherwise
    live Python. With both stored documents the run is fully offline.
    """

    cases, skipped = load_cases(manifest)
    report: dict[str, object] = {"mode": "comparison", "cases": [], "skipped": list(skipped)}
    failures = 0

    golden = load_capture_file(golden_path) if golden_path is not None else None
    response = load_capture_file(response_path) if response_path is not None else None
    golden_snapshots = golden.snapshots() if golden is not None else {}
    golden_errors = golden.errors() if golden is not None else {}
    response_snapshots = response.snapshots() if response is not None else {}
    response_errors = response.errors() if response is not None else {}

    java_url = os.environ.get("JAVA_BASE_URL", "http://127.0.0.1:8100")
    python_url = os.environ.get("PYTHON_BASE_URL", "http://127.0.0.1:8200")
    async with (
        httpx.AsyncClient(
            base_url=java_url,
            timeout=_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as java,
        httpx.AsyncClient(
            base_url=python_url,
            timeout=_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as python,
    ):
        for case in cases:
            case_result: dict[str, object] = {"name": case.name}
            try:
                java_snapshot = await _resolve_side(
                    case,
                    java,
                    golden_snapshots,
                    golden_errors,
                    golden_path,
                    "golden",
                )
                python_snapshot = await _resolve_side(
                    case,
                    python,
                    response_snapshots,
                    response_errors,
                    response_path,
                    "response",
                )
                differences = compare_http(
                    java_snapshot,
                    python_snapshot,
                    ignored_json_pointers=case.normalization.ignored_json_pointers,
                )
                case_result.update(
                    {
                        "matched": not differences,
                        "java": java_snapshot.as_dict(),
                        "python": python_snapshot.as_dict(),
                        "differences": [difference.as_dict() for difference in differences],
                    }
                )
                failures += bool(differences)
            except Exception as exc:  # a missing capture entry belongs in the report
                case_result.update({"matched": False, "error": f"{type(exc).__name__}: {exc}"})
                failures += 1
            _append_case(report, case_result)
    await asyncio.to_thread(_write_report, output, report)
    return 1 if failures else 0


async def _resolve_side(
    case: HttpCase,
    client: httpx.AsyncClient,
    snapshots: dict[str, HttpSnapshot],
    errors: dict[str, str],
    source: Path | None,
    label: str,
) -> HttpSnapshot:
    if source is None:
        return await capture_http(client, case)
    return _from_capture(case.name, snapshots, errors, source, label)


def _from_capture(
    name: str,
    snapshots: dict[str, HttpSnapshot],
    errors: dict[str, str],
    source: Path,
    label: str,
) -> HttpSnapshot:
    if name in errors:
        raise RuntimeError(f"{label} capture for {name} recorded an error: {errors[name]}")
    if name not in snapshots:
        raise KeyError(f"{label} capture {source} has no case named {name}")
    return snapshots[name]


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
    parser.add_argument(
        "--record-python",
        action="store_true",
        help="capture a sanitized Python-only response document without contacting Java",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        help="stored capture document used as the reference side (offline or live-Python compare)",
    )
    parser.add_argument(
        "--response",
        type=Path,
        help="stored capture document used as the candidate side; requires --golden",
    )
    arguments = parser.parse_args()
    _validate(parser, arguments)
    if arguments.record_java or arguments.record_python:
        side = "java" if arguments.record_java else "python"
        runner = _record_one(arguments.manifest, arguments.output, side=side)
    else:
        runner = _compare_run(
            arguments.manifest,
            arguments.output,
            golden_path=arguments.golden,
            response_path=arguments.response,
        )
    raise SystemExit(asyncio.run(runner))


def _validate(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> None:
    if arguments.record_java and arguments.record_python:
        parser.error("--record-java and --record-python are mutually exclusive")
    if (arguments.record_java or arguments.record_python) and (
        arguments.golden is not None or arguments.response is not None
    ):
        parser.error("--record-java/--record-python cannot be combined with --golden/--response")
    if arguments.response is not None and arguments.golden is None:
        parser.error("--response requires --golden")
