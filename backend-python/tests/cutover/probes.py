"""Fixed probe set for the featured-public cutover drill.

Sends one request per probe at the drill nginx and records status, a small
header set and the body. Two things are checked:

* **Routing attribution** — parsed from nginx's ``$upstream_addr`` access-log
  field. The three featured URIs are contract-identical on both backends by
  design, so no body-level test can tell which upstream answered; the access log
  is the only reliable witness. Every other probe is also attributed so a
  swallowed near-miss would show up as ``python`` where ``java`` is required.
* **Body stability** — the ``pre`` phase (all-Java) is the reference. Every later
  phase must reproduce the reference bodies after removing only the leaves listed
  in ``NORMALIZED_POINTERS``. That is the cutover-regression check; the
  contract-grade evidence lives in ``tests/contract/cases/phase3-featured*.json``,
  which declares the same leaves per case.

Normalization follows the contract lab's rule exactly: a nondeterministic value
may only be removed by naming its JSON Pointer, and there is no global ignore
list. ``normalize_json`` is reused so the two cannot drift apart.

Every httpx client is built with ``trust_env=False`` (R-26): a machine-level
proxy on this host hijacks ``127.0.0.1`` and silently kills local calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from reactor_backend.contracts.normalize import normalize_json

# ``java`` = the request must be answered by reactor_backend (the Java upstream).
# ``python`` = the request must be answered by reactor_backend_python.
#
# Near-misses (trailing slash / multi-segment) are pinned to ``java`` on purpose:
# the detail regex is single-segment so those keep Java's Spring error body.
PROBES: tuple[dict[str, Any], ...] = (
    {
        "id": "ui-home",
        "method": "GET",
        "path": "/api/agent/featured-conversations/home",
        "query": {"limit": "6"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "ui-list",
        "method": "GET",
        "path": "/api/agent/featured-conversations",
        "query": {"pageNo": "1", "pageSize": "20"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "ui-detail",
        "method": "GET",
        "path": "/api/agent/featured-conversations/fixture-featured",
        "upstream_after_cutover": "python",
    },
    {
        "id": "control-web-health",
        "method": "GET",
        "path": "/web/health",
        "upstream_after_cutover": "java",
    },
    {
        "id": "control-session-capabilities",
        "method": "GET",
        "path": "/api/agent/session/fixture-session/capabilities",
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-trailing-slash",
        "method": "GET",
        "path": "/api/agent/featured-conversations/",
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-multi-segment",
        "method": "GET",
        "path": "/api/agent/featured-conversations/a/b",
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-home-trailing-slash",
        "method": "GET",
        "path": "/api/agent/featured-conversations/home/",
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-home-extra-segment",
        "method": "GET",
        "path": "/api/agent/featured-conversations/home/extra",
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-detail-trailing-slash",
        "method": "GET",
        "path": "/api/agent/featured-conversations/fixture-featured/",
        "upstream_after_cutover": "java",
    },
    {
        "id": "method-home-post",
        "method": "POST",
        "path": "/api/agent/featured-conversations/home",
        "upstream_after_cutover": "python",
    },
    {
        "id": "method-list-post",
        "method": "POST",
        "path": "/api/agent/featured-conversations",
        "upstream_after_cutover": "python",
    },
    {
        "id": "coercion-home-bad-limit",
        "method": "GET",
        "path": "/api/agent/featured-conversations/home",
        "query": {"limit": "abc"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "coercion-list-bad-page-no",
        "method": "GET",
        "path": "/api/agent/featured-conversations",
        "query": {"pageNo": "x"},
        "upstream_after_cutover": "python",
    },
)

# Recorded per response and compared across phases. An absent header is recorded
# as an empty token list, so "Java sends no Server header" and "Python sends
# Server: uvicorn" are an ordinary, hard-failing mismatch rather than a silent
# pass. ``vary`` is included because Java's global CorsFilter stamps three of
# them on every response and a shared cache in front of these public GETs keys
# on it.
RECORDED_HEADERS: tuple[str, ...] = (
    "content-type",
    "server",
    "allow",
    "location",
    "x-accel-buffering",
    "vary",
)


def _header_tokens(response: httpx.Response, name: str) -> list[str]:
    """List-valued headers compared as sorted comma-tokens.

    Java's ``Vary`` arrives as three separate header lines; nginx and httpx may
    surface that as one comma-joined value or several. Splitting on commas and
    sorting makes the two representations compare equal without being lenient
    about *which* tokens are present.
    """
    tokens: list[str] = []
    for value in response.headers.get_list(name):
        tokens.extend(part.strip() for part in value.split(",") if part.strip())
    return sorted(tokens)

# Leaves that are nondeterministic per response and may therefore differ between
# two otherwise-identical phases. Rooted at the raw HTTP body — the contract
# manifests root at the capture document instead, so their ``/body/...`` pointer
# is the same leaf with that prefix removed.
#
# Per probe, not global, for two reasons. The contract lab declares its
# allowlist per case; and ``normalize_json`` deliberately raises on a mistyped
# pointer, so a single list cannot address both shapes of ``data`` (a list on
# ``/home``, an object on ``/{id}``). A missing *final* key is a no-op, which is
# why the base list is safe on every body.
#
# Nothing else is normalized. A changed ``publishedAt``, a dropped ``null`` or a
# reordered key is a real difference and must fail the phase.
BASE_POINTERS: tuple[str, ...] = (
    # Spring BasicErrorController's clock. Declared per-case as /body/timestamp
    # in tests/contract/cases/phase3-featured-errors.json.
    "/timestamp",
)

EXTRA_POINTERS: dict[str, tuple[str, ...]] = {
    # Java generates a random UUID here on every call. Declared per-case in
    # tests/contract/cases/phase3-featured.json (featured-detail-fixture).
    "ui-detail": (
        "/data/historyDetail/runs/*/replayFrames/*/resultMap/eventData/taskId",
    ),
}


def _pointers_for(probe_id: str) -> tuple[str, ...]:
    return BASE_POINTERS + EXTRA_POINTERS.get(probe_id, ())


def normalized_body(probe_id: str, raw: str) -> str:
    """JSON-semantics compare that preserves key order.

    Bodies that are not JSON (``/web/health`` answers ``ok``) are compared
    verbatim. JSON bodies are parsed, ``normalize_json`` is applied to the
    allowlisted leaves above, and the result is re-dumped with insertion order
    intact — so key order is still compared, while insignificant whitespace is
    not.
    """
    try:
        parsed: Any = json.loads(raw)
    except ValueError:
        return raw
    return json.dumps(
        normalize_json(parsed, _pointers_for(probe_id)), ensure_ascii=False
    )


@dataclass(frozen=True)
class ProbeResult:
    id: str
    method: str
    path: str
    query: dict[str, str]
    status_code: int
    headers: dict[str, list[str]]
    body: str
    elapsed_ms: float
    upstream: str | None
    expected_upstream_after_cutover: str

    def normalized_body(self) -> str:
        return normalized_body(self.id, self.body)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "path": self.path,
            "query": self.query,
            "status_code": self.status_code,
            "headers": self.headers,
            "body": self.body,
            "normalized_body": self.normalized_body(),
            "elapsed_ms": round(self.elapsed_ms, 2),
            "upstream": self.upstream,
            "expected_upstream_after_cutover": self.expected_upstream_after_cutover,
        }


def _request_line(probe: dict[str, Any]) -> str:
    """``$request`` as nginx logs it, for access-log correlation."""
    path = probe["path"]
    query = probe.get("query") or {}
    if query:
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        path = f"{path}?{qs}"
    return f"{probe['method']} {path} HTTP/1.1"


def parse_upstream_attribution(access_log: Path) -> dict[str, str]:
    """Map each probe's request line to the upstream that served its last hit.

    nginx's ``cutover`` log format quotes the request line and then prints
    ``upstream="..."``. An empty upstream means nginx answered without proxying
    (no matching location) — recorded as ``none``.
    """
    pattern = re.compile(r'"(?P<req>[^"]+)" \d+ \d+ upstream="(?P<up>[^"]*)"')
    if not access_log.exists():
        return {}
    latest: dict[str, str] = {}
    for line in access_log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        upstream = match.group("up") or "none"
        # ``127.0.0.1:8200`` -> python; ``127.0.0.1:8100`` -> java; keep raw too.
        latest[match.group("req")] = upstream
    return latest


def label_upstream(raw: str | None) -> str | None:
    if raw is None or raw == "none":
        return raw
    if raw.endswith(":8200") or raw.endswith(":8100"):
        return "python" if raw.endswith(":8200") else "java"
    return raw


def run_probes(base_url: str, access_log: Path | None) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    with httpx.Client(base_url=base_url, trust_env=False, timeout=30.0) as client:
        for probe in PROBES:
            started = time.perf_counter()
            response = client.request(
                probe["method"],
                probe["path"],
                params=probe.get("query") or None,
            )
            elapsed = (time.perf_counter() - started) * 1000
            headers = {name: _header_tokens(response, name) for name in RECORDED_HEADERS}
            results.append(
                ProbeResult(
                    id=probe["id"],
                    method=probe["method"],
                    path=probe["path"],
                    query=dict(probe.get("query") or {}),
                    status_code=response.status_code,
                    headers=headers,
                    body=response.text,
                    elapsed_ms=elapsed,
                    upstream=None,
                    expected_upstream_after_cutover=probe["upstream_after_cutover"],
                )
            )
    if access_log is not None:
        attribution = parse_upstream_attribution(access_log)
        annotated: list[ProbeResult] = []
        for result in results:
            raw = attribution.get(_request_line(_probe_by_id(result.id)))
            annotated.append(
                ProbeResult(
                    id=result.id,
                    method=result.method,
                    path=result.path,
                    query=result.query,
                    status_code=result.status_code,
                    headers=result.headers,
                    body=result.body,
                    elapsed_ms=result.elapsed_ms,
                    upstream=label_upstream(raw),
                    expected_upstream_after_cutover=result.expected_upstream_after_cutover,
                )
            )
        results = annotated
    return results


def _probe_by_id(probe_id: str) -> dict[str, Any]:
    for probe in PROBES:
        if probe["id"] == probe_id:
            return probe
    raise KeyError(probe_id)


def summarize(results: list[ProbeResult]) -> dict[str, Any]:
    server_5xx = [r.id for r in results if r.status_code >= 500]
    return {
        "count": len(results),
        "status_codes": {r.id: r.status_code for r in results},
        "server_5xx": server_5xx,
        "server_5xx_count": len(server_5xx),
        "upstreams": {r.id: r.upstream for r in results},
    }


def compare_to_reference(
    reference: list[ProbeResult], candidate: list[ProbeResult]
) -> list[dict[str, Any]]:
    """Differences between two phases.

    Compares status code, the recorded headers and the *normalized* body. The
    only tolerated nondeterminism is what ``NORMALIZED_POINTERS`` names (an
    error-body clock and one generated UUID); anything else — a new header, a
    changed status, a changed error shape — is a difference and must not be
    waved through.
    """
    differences: list[dict[str, Any]] = []
    ref_by_id = {r.id: r for r in reference}
    for cand in candidate:
        ref = ref_by_id.get(cand.id)
        if ref is None:
            differences.append({"id": cand.id, "reason": "probe missing from reference"})
            continue
        if ref.status_code != cand.status_code:
            differences.append(
                {
                    "id": cand.id,
                    "reason": "status mismatch",
                    "reference": ref.status_code,
                    "candidate": cand.status_code,
                }
            )
        if ref.headers != cand.headers:
            differences.append(
                {
                    "id": cand.id,
                    "reason": "header mismatch",
                    "reference": ref.headers,
                    "candidate": cand.headers,
                }
            )
        if ref.normalized_body() != cand.normalized_body():
            differences.append(
                {
                    "id": cand.id,
                    "reason": "body mismatch",
                    "reference": ref.normalized_body(),
                    "candidate": cand.normalized_body(),
                }
            )
    return differences


def routing_violations(
    results: list[ProbeResult], *, expect_cutover: bool
) -> list[dict[str, Any]]:
    """Probes whose observed upstream is not the one this phase requires."""
    violations: list[dict[str, Any]] = []
    for result in results:
        if result.upstream is None:
            violations.append({"id": result.id, "reason": "upstream not found in access log"})
            continue
        wanted = result.expected_upstream_after_cutover if expect_cutover else "java"
        if result.upstream != wanted:
            violations.append(
                {
                    "id": result.id,
                    "reason": "upstream mismatch",
                    "expected": wanted,
                    "observed": result.upstream,
                }
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--access-log", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expect-cutover",
        action="store_true",
        help="assert the post-cutover upstream map (default: everything on Java)",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="previous phase's report; body/status/headers are compared against it",
    )
    args = parser.parse_args()

    results = run_probes(args.base_url, args.access_log)
    report: dict[str, Any] = {
        "phase": args.phase,
        "base_url": args.base_url,
        "expect_cutover": args.expect_cutover,
        "summary": summarize(results),
        "probes": [r.as_dict() for r in results],
        "routing_violations": routing_violations(results, expect_cutover=args.expect_cutover),
        "differences_vs_reference": [],
    }
    if args.reference is not None:
        reference_doc = json.loads(args.reference.read_text(encoding="utf-8"))
        reference = [
            ProbeResult(
                id=p["id"],
                method=p["method"],
                path=p["path"],
                query=p["query"],
                status_code=p["status_code"],
                headers=p["headers"],
                body=p["body"],
                elapsed_ms=p["elapsed_ms"],
                upstream=p["upstream"],
                expected_upstream_after_cutover=p["expected_upstream_after_cutover"],
            )
            for p in reference_doc["probes"]
        ]
        report["differences_vs_reference"] = compare_to_reference(reference, results)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(
        f"phase={args.phase} probes={summary['count']} "
        f"5xx={summary['server_5xx_count']} "
        f"routing_violations={len(report['routing_violations'])} "
        f"diffs_vs_reference={len(report['differences_vs_reference'])}"
    )
    failed = bool(
        summary["server_5xx_count"]
        or report["routing_violations"]
        or report["differences_vs_reference"]
    )
    if failed:
        print(json.dumps(report["routing_violations"], ensure_ascii=False, indent=2))
        print(json.dumps(report["differences_vs_reference"], ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
