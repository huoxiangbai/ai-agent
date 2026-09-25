"""Fixed probe set for the featured-admin write-domain cutover drill.

Same two witnesses as the phase-3B probe set, reused through
:mod:`tests.cutover.probes`:

* **Routing attribution** from nginx's ``$upstream_addr`` access-log field. The five
  admin URIs are contract-identical on both backends by design, so no body-level
  test can tell which upstream answered — the access log is the only reliable
  witness. Near-misses are pinned to ``java`` so a swallowed path shows up as a
  hard failure rather than a silent pass.
* **Body stability** against the ``pre`` phase (all-Java), with nondeterminism
  removed only by naming exact JSON Pointers. There is no global ignore list.

The write probes are deliberately **read-shaped or failing-shaped** so the drill is
idempotent and cannot leave the throwaway database in a state the next phase
cannot reproduce: ``query-list`` is exercised for real, while ``create``/``update``/
``online``/``offline`` are exercised with inputs that the Java side rejects
(unknown ``featuredId`` / blank body fields), which is exactly the 500-four-key and
``data:false`` contract this slice has to preserve across the switch.

Every httpx client is built with ``trust_env=False`` (R-26).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from reactor_backend.contracts.normalize import normalize_json
from tests.cutover.probes import (
    RECORDED_HEADERS,
    ProbeResult,
    _header_tokens,
    compare_to_reference,
    label_upstream,
    parse_upstream_attribution,
    routing_violations,
    summarize,
)

# ``python`` = must be answered by reactor_backend_python after the cutover.
PROBES: tuple[dict[str, Any], ...] = (
    {
        "id": "admin-query-list",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/query-list",
        "json": {"pageNo": 1, "pageSize": 10},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-query-list-lombok-defaults",
        # Absent pageNo/pageSize: Jackson's no-arg construction installs the Lombok
        # defaults (1/10), so this pages at width 10 — unlike a present JSON null.
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/query-list",
        "json": {},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-create-missing-body",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/create",
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-create-blank-session",
        # IllegalArgumentException("sessionId 不能为空") escapes as 500 four-key.
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/create",
        "json": {"sessionId": "   "},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-update-missing-featured-id",
        "method": "PUT",
        "path": "/api/v1/admin/featured-conversations/update",
        "json": {"title": "t"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-update-unknown-featured-id",
        "method": "PUT",
        "path": "/api/v1/admin/featured-conversations/update",
        "json": {"featuredId": "drill-no-such-featured", "title": "t"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-online-missing-operator",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/online/drill-no-such-featured",
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-offline-missing-operator",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/offline/drill-no-such-featured",
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-online-unknown-row",
        # Missing row -> HTTP 200 + data:false, never an exception.
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/online/drill-no-such-featured",
        "query": {"operator": "drill"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-offline-unknown-row",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/offline/drill-no-such-featured",
        "query": {"operator": "drill"},
        "upstream_after_cutover": "python",
    },
    {
        "id": "admin-create-bad-field-type",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/create",
        "json": {"sessionId": "s1", "sortOrder": "not-a-number"},
        "upstream_after_cutover": "python",
    },
    # Controls and near-misses: must stay on Java so a swallowed path is visible.
    {
        "id": "control-web-health",
        "method": "GET",
        "path": "/web/health",
        "upstream_after_cutover": "java",
    },
    {
        "id": "control-other-admin-family",
        # A sibling admin CRUD family this slice must NOT touch.
        "method": "POST",
        "path": "/api/v1/admin/sub-agents/query-list",
        "json": {},
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-create-trailing-slash",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/create/",
        "json": {},
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-online-extra-segment",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/online/a/b",
        "upstream_after_cutover": "java",
    },
    {
        "id": "near-miss-unknown-sub-path",
        "method": "POST",
        "path": "/api/v1/admin/featured-conversations/purge",
        "json": {},
        "upstream_after_cutover": "java",
    },
    {
        "id": "method-create-get",
        "method": "GET",
        "path": "/api/v1/admin/featured-conversations/create",
        "upstream_after_cutover": "python",
    },
)

# Probes deliberately shaped so **Java** rejects them — a blank sessionId, a
# missing/unknown featuredId. The 500-four-key body *is* the contract this slice
# has to preserve across the switch, so a 5xx here is a pass. It is asserted
# rather than merely tolerated: a probe listed here that stops returning its
# expected status is a failure, and any 5xx outside this map is still a failure.
# phase-3B's probes.py keeps the blanket "no 5xx ever" rule; only this probe set
# has failing-shaped cases, so the exception lives here, next to them.
EXPECT_STATUS: dict[str, int] = {
    "admin-create-blank-session": 500,
    "admin-update-missing-featured-id": 500,
    "admin-update-unknown-featured-id": 500,
}

# Clock in Spring's BasicErrorController body, and the admin list's updatedAt/
# publishedAt stamps, which the write probes never set but query-list reads from
# whatever the throwaway database already holds — identical across phases only if
# the drill is read-shaped, which the probe set above guarantees.
BASE_POINTERS: tuple[str, ...] = ("/timestamp",)
EXTRA_POINTERS: dict[str, tuple[str, ...]] = {
    "admin-query-list": (
        "/data/list/*/updatedAt",
        "/data/list/*/publishedAt",
    ),
    "admin-query-list-lombok-defaults": (
        "/data/list/*/updatedAt",
        "/data/list/*/publishedAt",
    ),
}


def _pointers_for(probe_id: str) -> tuple[str, ...]:
    return BASE_POINTERS + EXTRA_POINTERS.get(probe_id, ())


def normalized_body(probe_id: str, raw: str) -> str:
    try:
        parsed: Any = json.loads(raw)
    except ValueError:
        return raw
    return json.dumps(
        normalize_json(parsed, _pointers_for(probe_id)), ensure_ascii=False
    )


def _request_body(probe: dict[str, Any]) -> tuple[bytes | None, dict[str, str]]:
    payload = probe.get("json")
    if payload is None:
        return None, {}
    return (
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        {"content-type": "application/json"},
    )


def _request_line(probe: dict[str, Any]) -> str:
    path = probe["path"]
    query = probe.get("query") or {}
    if query:
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        path = f"{path}?{qs}"
    return f"{probe['method']} {path} HTTP/1.1"


def run_probes(
    base_url: str,
    access_log: Path | None,
    *,
    java_port: int = 8100,
    python_port: int = 8200,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    with httpx.Client(base_url=base_url, trust_env=False, timeout=30.0) as client:
        for probe in PROBES:
            body, headers = _request_body(probe)
            response = client.request(
                probe["method"],
                probe["path"],
                params=probe.get("query") or None,
                content=body,
                headers=headers,
            )
            results.append(
                ProbeResult(
                    id=probe["id"],
                    method=probe["method"],
                    path=probe["path"],
                    query=dict(probe.get("query") or {}),
                    status_code=response.status_code,
                    headers={n: _header_tokens(response, n) for n in RECORDED_HEADERS},
                    body=response.text,
                    elapsed_ms=0.0,
                    upstream=None,
                    expected_upstream_after_cutover=probe["upstream_after_cutover"],
                )
            )
    if access_log is not None:
        attribution = parse_upstream_attribution(access_log)
        results = [
            ProbeResult(
                id=r.id,
                method=r.method,
                path=r.path,
                query=r.query,
                status_code=r.status_code,
                headers=r.headers,
                body=r.body,
                elapsed_ms=r.elapsed_ms,
                upstream=label_upstream(
                    attribution.get(_request_line(_probe_by_id(r.id))),
                    java_port=java_port,
                    python_port=python_port,
                ),
                expected_upstream_after_cutover=r.expected_upstream_after_cutover,
            )
            for r in results
        ]
    return results


def _probe_by_id(probe_id: str) -> dict[str, Any]:
    for probe in PROBES:
        if probe["id"] == probe_id:
            return probe
    raise KeyError(probe_id)


def _attach_normalized(results: list[ProbeResult]) -> list[dict[str, Any]]:
    docs = []
    for r in results:
        doc = r.as_dict()
        doc["normalized_body"] = normalized_body(r.id, r.body)
        docs.append(doc)
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--access-log", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-cutover", action="store_true")
    parser.add_argument("--reference", type=Path, default=None)
    parser.add_argument("--java-upstream-port", type=int, default=8100)
    parser.add_argument("--python-upstream-port", type=int, default=8200)
    args = parser.parse_args()

    results = run_probes(
        args.base_url,
        args.access_log,
        java_port=args.java_upstream_port,
        python_port=args.python_upstream_port,
    )
    report: dict[str, Any] = {
        "phase": args.phase,
        "base_url": args.base_url,
        "expect_cutover": args.expect_cutover,
        "summary": summarize(results),
        "probes": _attach_normalized(results),
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
        # ProbeResult.normalized_body would resolve probes.py's EXTRA_POINTERS,
        # not this module's — pass ours so updatedAt/publishedAt are actually
        # tolerated instead of being reported as cross-phase regressions.
        report["differences_vs_reference"] = compare_to_reference(
            reference, results, normalizer=lambda r: normalized_body(r.id, r.body)
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    observed = summary["status_codes"]
    # An unexpected 5xx is a server blow-up; a *missing* expected 5xx means the
    # rejection contract silently changed shape. Both fail.
    unexpected_5xx = [i for i in summary["server_5xx"] if i not in EXPECT_STATUS]
    broken_contract = [
        {"id": probe_id, "expected": want, "observed": observed.get(probe_id)}
        for probe_id, want in sorted(EXPECT_STATUS.items())
        if observed.get(probe_id) != want
    ]
    report["unexpected_5xx"] = unexpected_5xx
    report["broken_rejection_contract"] = broken_contract
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"phase={args.phase} probes={summary['count']} "
        f"5xx={summary['server_5xx_count']} (expected {len(EXPECT_STATUS)}) "
        f"routing_violations={len(report['routing_violations'])} "
        f"diffs_vs_reference={len(report['differences_vs_reference'])}"
    )
    failed = bool(
        unexpected_5xx
        or broken_contract
        or report["routing_violations"]
        or report["differences_vs_reference"]
    )
    if failed:
        print(json.dumps(report["routing_violations"], ensure_ascii=False, indent=2))
        print(json.dumps(report["differences_vs_reference"], ensure_ascii=False, indent=2))
        print(json.dumps({"unexpected_5xx": unexpected_5xx,
                          "broken_rejection_contract": broken_contract},
                         ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
