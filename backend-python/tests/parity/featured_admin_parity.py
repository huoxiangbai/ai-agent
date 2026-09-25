"""Cloned-database Java / Python parity for the featured-admin write slice.

Runs one identical admin request sequence against Java and against Python, on two
databases cloned from a single snapshot, and diffs (1) every HTTP response and
(2) the full contents of every affected table. Exit 0 only when both diffs are
empty.

The single-writer rule forbids Java and Python writing one database at the same
time, so this script refuses to start unless ``--java-db-url`` and
``--python-db-url`` name **different** databases. Writes go to Java first, then
to Python; each side only ever talks to its own database.

Three comparison modes, because not every body is deterministic:

``exact``
    Status, the recorded header set and the JSON body with key order preserved.
    Nondeterminism is removed only by naming JSON Pointers per case (the
    ``BasicErrorController`` clock, and the ``updatedAt``/``publishedAt`` stamps
    the run itself writes). There is no global ignore list.

``featured_ids``
    Status and headers, plus the **set** of ``featuredId`` values in the body.
    Used for the public-read effect witnesses, whose row order depends on
    ``id DESC`` tiebreaks inside snapshot data.

``shape``
    Status and headers, plus ``data.total`` and ``data.list`` length. Used for
    unfiltered admin lists, whose *identity* is snapshot-dependent but whose
    count and page width are not.

On top of the mode, each case may assert ``must_contain`` / ``must_absent``
substrings and ``expect_list_length`` on **both** sides — that is how "the write
is visible through the read path" is witnessed rather than merely inferred from
table state.

Tables are diffed on business keys, not row ids: ``featured_id`` for
``ai_agent_featured_conversation``, ``session_id`` for
``ai_agent_dialogue_session``. ``id``/``create_time``/``update_time`` are
engine-driven and dropped from the cross-side diff; ``published_at``/``updated_at``
are application wall-clocks stamped by this run and are compared by shape
(null-ness) plus a tolerance window, never by exact value. The same pair of
tables is also diffed pre-vs-post per side with ``update_time`` **kept**, which
is the witness that ``create`` only ever *reads* ``ai_agent_dialogue_session``.

Credentials stay in the process environment and the argv of the caller; the
report records database *names* only (R-34).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from reactor_backend.contracts.normalize import normalize_json

RECORDED_HEADERS: tuple[str, ...] = (
    "content-type",
    "server",
    "allow",
    "location",
    "x-accel-buffering",
    "vary",
)

# Engine-driven: ``AUTO_INCREMENT``, ``DEFAULT CURRENT_TIMESTAMP``,
# ``ON UPDATE CURRENT_TIMESTAMP``. Never comparable across two clones.
ENGINE_COLUMNS = frozenset({"id", "create_time", "update_time"})

# Application wall-clocks stamped by this very run. Compared by null-ness and by
# a tolerance window on the raw values, never byte-for-byte.
STAMP_COLUMNS = frozenset({"published_at", "updated_at"})

TABLES: tuple[tuple[str, str], ...] = (
    ("ai_agent_featured_conversation", "featured_id"),
    ("ai_agent_dialogue_session", "session_id"),
)

STAMP_POINTERS: tuple[str, ...] = (
    "/data/list/*/publishedAt",
    "/data/list/*/updatedAt",
)


@dataclass(frozen=True)
class Case:
    id: str
    method: str
    path: str
    mode: str = "exact"
    query: Mapping[str, str] = field(default_factory=dict)
    json_body: Any = None
    has_body: bool = True
    ignore_pointers: tuple[str, ...] = ()
    must_contain: tuple[str, ...] = ()
    must_absent: tuple[str, ...] = ()
    expect_list_length: int | None = None
    expect_data_total: int | None = None


def build_cases(run_id: str) -> tuple[Case, ...]:
    """The full admin sequence, keyed by a per-invocation ``run_id``.

    Every ``sessionId`` embeds ``run_id`` so replaying against the same pair of
    databases cannot collide on either UNIQUE key — a replay adds its own rows
    rather than fighting this one. Within a run the sequence deliberately sends
    the same ``sessionId`` twice so the ``ON DUPLICATE KEY UPDATE`` branch is part
    of what gets compared.
    """

    s1 = f"{run_id}-s1"
    s2 = f"{run_id}-s2"
    s3 = f"{run_id}-s3"
    s1_fid = f"featured_{s1}"
    s2_fid = f"featured_{s2}"
    missing_fid = f"featured_{run_id}-missing"
    title_tag = f"parity {run_id}"

    error_pointers = ("/timestamp",)

    return (
        # ---- writes ----------------------------------------------------
        Case(
            id="create-s1",
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={
                "sessionId": s1,
                "title": f"{title_tag} s1 v1",
                "summary": f"摘要 {run_id} v1",
                "coverResourceKey": "res-key-1",
                "coverUrl": "https://example.invalid/cover-1.png",
                "tags": ["甲", "b", None],
                "sortOrder": 3,
                "operator": "parity-op",
            },
        ),
        Case(
            id="create-s1-duplicate",
            # Same sessionId again: the generated featuredId hits both UNIQUE
            # keys on the same row, so the ON DUPLICATE branch fires and must
            # leave status / published_by / published_at / session_id /
            # featured_id untouched.
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={
                "sessionId": s1,
                "title": f"{title_tag} s1 v2",
                "summary": f"摘要 {run_id} v2",
                "coverResourceKey": None,
                "coverUrl": None,
                "tags": [],
                "sortOrder": 4,
                "operator": "parity-op-dup",
            },
        ),
        Case(
            id="create-s2",
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={
                "sessionId": s2,
                "title": f"{title_tag} s2 v1",
                "summary": None,
                "coverResourceKey": None,
                "coverUrl": None,
                "tags": None,
                "sortOrder": 2,
                "operator": "parity-op",
            },
        ),
        Case(
            id="update-s1",
            method="PUT",
            path="/api/v1/admin/featured-conversations/update",
            json_body={
                "featuredId": s1_fid,
                "title": f"{title_tag} s1 v3",
                "summary": None,
                "tags": None,
                "sortOrder": None,
                "operator": "parity-op-upd",
            },
        ),
        Case(
            id="online-s1",
            method="POST",
            path=f"/api/v1/admin/featured-conversations/online/{s1_fid}",
            query={"operator": "parity-op-online"},
            has_body=False,
        ),
        # ---- effects of the writes, through the already-cut-over reads ---
        Case(
            id="effect-public-list-online",
            method="GET",
            path="/api/agent/featured-conversations",
            mode="featured_ids",
            query={"pageNo": "1", "pageSize": "1000"},
            has_body=False,
            must_contain=(s1_fid,),
            must_absent=(s2_fid,),
        ),
        Case(
            id="effect-public-home-online",
            method="GET",
            path="/api/agent/featured-conversations/home",
            mode="featured_ids",
            query={"limit": "1000"},
            has_body=False,
            must_contain=(s1_fid,),
            must_absent=(s2_fid,),
        ),
        # ---- admin reads of the same state ------------------------------
        Case(
            id="query-list-s1",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            query={},
            json_body={"sessionId": s1},
            ignore_pointers=STAMP_POINTERS,
            must_contain=(s1_fid,),
        ),
        Case(
            id="query-list-status-online-s1",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            json_body={"status": "ONLINE", "sessionId": s1},
            ignore_pointers=STAMP_POINTERS,
            expect_list_length=1,
            expect_data_total=1,
        ),
        Case(
            id="query-list-status-online-s2",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            json_body={"status": "ONLINE", "sessionId": s2},
            expect_list_length=0,
            expect_data_total=0,
        ),
        Case(
            id="query-list-lombok-defaults",
            # Absent pageNo/pageSize: Jackson binds through the no-arg constructor,
            # which installs the Lombok defaults 1/10 — so this pages at width 10.
            # Shape mode is the witness (a Python that paged at width 1 disagreed
            # with Java's length here). Deliberately no expect_list_length: replay
            # adds rows, so an unfiltered page width is not a stable absolute.
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            mode="shape",
            json_body={},
        ),
        Case(
            id="query-list-page-size-null",
            # The other half of the split: a *present* JSON null reaches the setter
            # and lands on 0, so Math.max(1, 0) clamps the page to width 1. This
            # absolute pin is replay-stable — the limit is 1 however many rows the
            # snapshot has grown to.
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            mode="shape",
            json_body={"pageSize": None},
            expect_list_length=1,
        ),
        Case(
            id="query-list-whitespace-title",
            # MyBatis' ``!= ''`` guard is a strict empty-string check, so a
            # whitespace-only filter IS applied. Mode "shape" because matching
            # rows come from the snapshot; the cross-side total is the witness
            # that both implementations agree on whether the filter applies.
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            mode="shape",
            json_body={"title": "   "},
        ),
        Case(
            id="offline-s1",
            method="POST",
            path=f"/api/v1/admin/featured-conversations/offline/{s1_fid}",
            query={"operator": "parity-op-offline"},
            has_body=False,
        ),
        Case(
            id="effect-public-home-after-offline",
            method="GET",
            path="/api/agent/featured-conversations/home",
            mode="featured_ids",
            query={"limit": "1000"},
            has_body=False,
            must_absent=(s1_fid,),
        ),
        Case(
            id="query-list-s1-after-offline",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            json_body={"sessionId": s1},
            ignore_pointers=STAMP_POINTERS,
            must_contain=(s1_fid, "OFFLINE"),
        ),
        Case(
            id="online-empty-operator-s2",
            # ``?operator=`` is present, so Spring binds the empty string and
            # accepts it. Only a *missing* parameter is a 400.
            method="POST",
            path=f"/api/v1/admin/featured-conversations/online/{s2_fid}",
            query={"operator": ""},
            has_body=False,
        ),
        Case(
            id="query-list-s2",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            json_body={"sessionId": s2},
            ignore_pointers=STAMP_POINTERS,
            must_contain=(s2_fid, "ONLINE"),
        ),
        # ---- unique-key shape: update retargets sessionId onto s1's row ---
        # ``featuredId`` exists (so update's existence pre-check passes) but
        # ``sessionId`` names a *different* row. Both UNIQUE keys can match;
        # whichever row MySQL picks, the identical SQL must pick the same one on
        # both sides — and neither ``featured_id`` nor ``session_id`` is in the
        # ON DUPLICATE UPDATE clause, so the keys of both rows must survive.
        Case(
            id="update-session-retarget",
            method="PUT",
            path="/api/v1/admin/featured-conversations/update",
            json_body={
                "featuredId": s1_fid,
                "sessionId": s2,
                "title": f"{title_tag} retarget",
                "sortOrder": 9,
                "operator": "parity-op-col",
            },
        ),
        Case(
            id="query-list-s1-final",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            json_body={"sessionId": s1},
            ignore_pointers=STAMP_POINTERS,
            must_contain=(s1_fid,),
        ),
        Case(
            id="query-list-s2-final",
            method="POST",
            path="/api/v1/admin/featured-conversations/query-list",
            json_body={"sessionId": s2},
            ignore_pointers=STAMP_POINTERS,
            must_contain=(s2_fid,),
        ),
        # ---- error shapes (must leave no state behind) -------------------
        Case(
            id="create-missing-body",
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            has_body=False,
            ignore_pointers=error_pointers,
        ),
        Case(
            id="create-blank-session",
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={"sessionId": "   "},
            ignore_pointers=error_pointers,
        ),
        Case(
            id="create-unknown-session",
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={"sessionId": f"{run_id}-nope", "title": "t", "operator": "p"},
            ignore_pointers=error_pointers,
        ),
        Case(
            id="create-null-title",
            # ``title`` is NOT NULL: the single INSERT statement fails and must
            # leave no row. This is the statement-atomicity pin, standing in for
            # a transaction rollback (the Java service has no @Transactional).
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={"sessionId": s3, "title": None, "operator": "parity-op"},
            ignore_pointers=error_pointers,
        ),
        Case(
            id="create-bad-field-type",
            method="POST",
            path="/api/v1/admin/featured-conversations/create",
            json_body={"sessionId": s1, "sortOrder": "not-a-number"},
            ignore_pointers=error_pointers,
        ),
        Case(
            id="update-missing-featured-id",
            method="PUT",
            path="/api/v1/admin/featured-conversations/update",
            json_body={"title": "t"},
            ignore_pointers=error_pointers,
        ),
        Case(
            id="update-unknown-featured-id",
            method="PUT",
            path="/api/v1/admin/featured-conversations/update",
            json_body={"featuredId": missing_fid, "title": "t", "operator": "p"},
            ignore_pointers=error_pointers,
        ),
        Case(
            id="online-unknown-row",
            method="POST",
            path=f"/api/v1/admin/featured-conversations/online/{missing_fid}",
            query={"operator": "parity"},
            has_body=False,
        ),
        Case(
            id="offline-unknown-row",
            method="POST",
            path=f"/api/v1/admin/featured-conversations/offline/{missing_fid}",
            query={"operator": "parity"},
            has_body=False,
        ),
        Case(
            id="online-missing-operator",
            method="POST",
            path=f"/api/v1/admin/featured-conversations/online/{missing_fid}",
            has_body=False,
            ignore_pointers=error_pointers,
        ),
        Case(
            id="offline-missing-operator",
            method="POST",
            path=f"/api/v1/admin/featured-conversations/offline/{missing_fid}",
            has_body=False,
            ignore_pointers=error_pointers,
        ),
    )


# ---------------------------------------------------------------------------
# HTTP side
# ---------------------------------------------------------------------------


def _header_tokens(response: httpx.Response, name: str) -> list[str]:
    tokens: list[str] = []
    for value in response.headers.get_list(name):
        tokens.extend(part.strip() for part in value.split(",") if part.strip())
    return sorted(tokens)


def extract_featured_ids(payload: Any) -> list[str]:
    """Every ``featuredId`` in a public/admin read payload, order discarded."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            value = node.get("featuredId")
            if isinstance(value, str):
                found.append(value)
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return sorted(found)


def _payload_at(payload: Any, path: Sequence[str]) -> Any:
    node = payload
    for key in path:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node


def _list_length(payload: Any) -> int | None:
    listing = _payload_at(payload, ("data", "list"))
    if listing is None and isinstance(payload, dict):
        listing = payload.get("data") if isinstance(payload.get("data"), list) else None
    return len(listing) if isinstance(listing, list) else None


def run_sequence(base_url: str, cases: Sequence[Case]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url, trust_env=False, timeout=30.0) as client:
        for case in cases:
            content: bytes | None = None
            headers: dict[str, str] = {}
            if case.has_body:
                content = json.dumps(case.json_body, ensure_ascii=False).encode("utf-8")
                headers["content-type"] = "application/json"
            response = client.request(
                case.method,
                case.path,
                params=dict(case.query) or None,
                content=content,
                headers=headers,
            )
            results.append(
                {
                    "id": case.id,
                    "status_code": response.status_code,
                    "headers": {
                        name: _header_tokens(response, name) for name in RECORDED_HEADERS
                    },
                    "body": response.text,
                }
            )
    return results


def compare_responses(
    cases: Sequence[Case],
    java: Sequence[dict[str, Any]],
    python: Sequence[dict[str, Any]],
    ignore_headers: frozenset[str],
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for case, j, p in zip(cases, java, python, strict=True):
        if j["status_code"] != p["status_code"]:
            differences.append(
                {
                    "case": case.id,
                    "reason": "status mismatch",
                    "java": j["status_code"],
                    "python": p["status_code"],
                }
            )
        j_headers = {k: v for k, v in j["headers"].items() if k not in ignore_headers}
        p_headers = {k: v for k, v in p["headers"].items() if k not in ignore_headers}
        if j_headers != p_headers:
            differences.append(
                {
                    "case": case.id,
                    "reason": "header mismatch",
                    "java": j_headers,
                    "python": p_headers,
                }
            )

        try:
            j_body = json.loads(j["body"])
        except ValueError:
            j_body = None
        try:
            p_body = json.loads(p["body"])
        except ValueError:
            p_body = None

        if case.mode == "exact":
            j_norm = _normalized(j_body, j["body"], case.ignore_pointers)
            p_norm = _normalized(p_body, p["body"], case.ignore_pointers)
            if j_norm != p_norm:
                differences.append(
                    {
                        "case": case.id,
                        "reason": "body mismatch",
                        "java": j_norm,
                        "python": p_norm,
                    }
                )
        elif case.mode == "featured_ids":
            j_ids = extract_featured_ids(j_body if j_body is not None else j["body"])
            p_ids = extract_featured_ids(p_body if p_body is not None else p["body"])
            if j_ids != p_ids:
                differences.append(
                    {
                        "case": case.id,
                        "reason": "featuredId set mismatch",
                        "java": j_ids,
                        "python": p_ids,
                    }
                )
        elif case.mode == "shape":
            j_shape = {
                "total": _payload_at(j_body, ("data", "total")),
                "length": _list_length(j_body),
            }
            p_shape = {
                "total": _payload_at(p_body, ("data", "total")),
                "length": _list_length(p_body),
            }
            if j_shape != p_shape:
                differences.append(
                    {
                        "case": case.id,
                        "reason": "shape mismatch",
                        "java": j_shape,
                        "python": p_shape,
                    }
                )
        else:  # pragma: no cover - modes are a closed set
            raise ValueError(f"unknown mode {case.mode!r}")

        for needle in case.must_contain:
            for side, body in (("java", j["body"]), ("python", p["body"])):
                if needle not in body:
                    differences.append(
                        {
                            "case": case.id,
                            "reason": f"must_contain {needle!r} missing on {side}",
                        }
                    )
        for needle in case.must_absent:
            for side, body in (("java", j["body"]), ("python", p["body"])):
                if needle in body:
                    differences.append(
                        {
                            "case": case.id,
                            "reason": f"must_absent {needle!r} present on {side}",
                        }
                    )
        if case.expect_list_length is not None:
            for side, body in (("java", j_body), ("python", p_body)):
                got = _list_length(body)
                if got != case.expect_list_length:
                    differences.append(
                        {
                            "case": case.id,
                            "reason": f"expect_list_length on {side}",
                            "expected": case.expect_list_length,
                            "observed": got,
                        }
                    )
        if case.expect_data_total is not None:
            for side, body in (("java", j_body), ("python", p_body)):
                got = _payload_at(body, ("data", "total"))
                if got != case.expect_data_total:
                    differences.append(
                        {
                            "case": case.id,
                            "reason": f"expect_data_total on {side}",
                            "expected": case.expect_data_total,
                            "observed": got,
                        }
                    )
    return differences


def _normalized(parsed: Any, raw: str, pointers: tuple[str, ...]) -> Any:
    if parsed is None:
        return raw
    return json.dumps(normalize_json(parsed, pointers), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Table side
# ---------------------------------------------------------------------------


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, str | int):
        return value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


async def dump_table(engine: Any, table: str) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(text(f"SELECT * FROM {table}"))  # noqa: S608
        columns = list(result.keys())
        return [dict(zip(columns, (_cell(v) for v in row), strict=True)) for row in result.all()]


def project_cross(row: Mapping[str, Any]) -> dict[str, Any]:
    """Cross-side projection: drop engine columns, shape the run stamps."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in ENGINE_COLUMNS:
            continue
        out[key] = "<stamped>" if key in STAMP_COLUMNS and value is not None else value
    return out


def project_untouched(row: Mapping[str, Any]) -> dict[str, Any]:
    """Pre-vs-post projection: keep ``update_time`` as the write witness."""
    return {k: v for k, v in row.items() if k not in {"id", "create_time"}}


def _by_key(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        index[str(row.get(key))] = dict(row)
    return index


def diff_tables(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    key: str,
    projector: Any,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    l_index = _by_key(left, key)
    r_index = _by_key(right, key)
    for missing in sorted(set(l_index) - set(r_index)):
        differences.append({"key": missing, "reason": "row only on left"})
    for extra in sorted(set(r_index) - set(l_index)):
        differences.append({"key": extra, "reason": "row only on right"})
    for shared in sorted(set(l_index) & set(r_index)):
        l_row = projector(l_index[shared])
        r_row = projector(r_index[shared])
        for column in sorted(set(l_row) | set(r_row)):
            if l_row.get(column) != r_row.get(column):
                differences.append(
                    {
                        "key": shared,
                        "column": column,
                        "reason": "value mismatch",
                        "left": l_row.get(column),
                        "right": r_row.get(column),
                    }
                )
    return differences


def stamp_tolerance_differences(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    key: str,
    tolerance_seconds: float,
) -> list[dict[str, Any]]:
    """Both sides non-null on a stamp column must fall within the tolerance window."""
    differences: list[dict[str, Any]] = []
    l_index = _by_key(left, key)
    r_index = _by_key(right, key)
    for shared in sorted(set(l_index) & set(r_index)):
        for column in sorted(STAMP_COLUMNS):
            l_raw = l_index[shared].get(column)
            r_raw = r_index[shared].get(column)
            if not isinstance(l_raw, str) or not isinstance(r_raw, str):
                # Null-ness is already compared exactly by the projector.
                continue
            try:
                l_dt = datetime.fromisoformat(l_raw)
                r_dt = datetime.fromisoformat(r_raw)
            except ValueError:  # pragma: no cover - _cell always emits isoformat
                continue
            delta = abs((l_dt - r_dt).total_seconds())
            if delta > tolerance_seconds:
                differences.append(
                    {
                        "key": shared,
                        "column": column,
                        "reason": "stamp outside tolerance window",
                        "left": l_raw,
                        "right": r_raw,
                        "delta_seconds": delta,
                        "tolerance_seconds": tolerance_seconds,
                    }
                )
    return differences


def check_sorted_order_guard(
    rows: Sequence[Mapping[str, Any]], ceiling: int
) -> list[dict[str, Any]]:
    """Fail loud if the snapshot could outrank anything this sequence writes.

    Only relevant to unfiltered lists, which are compared in ``shape`` mode
    anyway; this is a cheap tripwire so a surprising fixture shows up as a named
    finding instead of a mysterious ``shape`` mismatch.
    """
    offenders = [
        {"key": str(row.get("featured_id")), "sort_order": row.get("sort_order")}
        for row in rows
        if isinstance(row.get("sort_order"), int) and row["sort_order"] >= ceiling
    ]
    return [{"reason": "snapshot sort_order at or above ceiling", **o} for o in offenders]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def seed_sessions() -> list[dict[str, Any]]:
    """Identical ``ai_agent_dialogue_session`` rows for both sides.

    ``create`` only *reads* this table (session existence), so the rows are part
    of the fixture rather than the thing under test. Non-engine columns are
    pinned so the untouched-check has something exact to hold on to.
    """
    started = datetime(2026, 1, 2, 3, 4, 5, 6000)
    active = datetime(2026, 1, 2, 3, 5, 6, 7000)
    return [
        {
            "session_id": suffix,
            "visitor_id": "parity-visitor",
            "title": f"parity session {suffix}",
            "status": 0,
            "latest_request_id": None,
            "latest_query_text": None,
            "latest_summary_text": None,
            "run_count": 1,
            "finished_run_count": 1,
            "failed_run_count": 0,
            "started_at": started,
            "last_active_at": active,
            "deleted": 0,
        }
        for suffix in ("{run_id}-s1", "{run_id}-s2", "{run_id}-s3")
    ]


async def seed(engine: Any, run_id: str) -> None:
    columns = (
        "session_id, visitor_id, title, status, latest_request_id, latest_query_text, "
        "latest_summary_text, run_count, finished_run_count, failed_run_count, "
        "started_at, last_active_at, deleted"
    )
    placeholders = ", ".join(f":{name}" for name in columns.replace(" ", "").split(","))
    statement = text(
        f"INSERT INTO ai_agent_dialogue_session ({columns}) VALUES ({placeholders})"  # noqa: S608
    )
    async with engine.begin() as connection:
        for template in seed_sessions():
            row = {
                k: (v.replace("{run_id}", run_id) if isinstance(v, str) else v)
                for k, v in template.items()
            }
            await connection.execute(statement, row)


def database_name(url: str) -> str:
    path = urlsplit(url).path
    return path.lstrip("/").split("?")[0]


async def main_async(args: argparse.Namespace) -> int:
    java_db = database_name(args.java_db_url)
    python_db = database_name(args.python_db_url)
    if not java_db or not python_db:
        print("ERROR: both --*-db-url values must name a database", file=sys.stderr)
        return 2
    if java_db == python_db:
        # Single-writer rule: never two application writers on one database.
        print(
            f"ERROR: both sides point at database {java_db!r}. "
            "Clone the snapshot twice — refusing to run two writers on one database.",
            file=sys.stderr,
        )
        return 2

    cases = build_cases(args.run_id)
    extra: dict[str, list[str]] = {}
    for spec in args.ignore_pointer:
        if "=" not in spec:
            print(f"ERROR: --ignore-pointer wants CASE=POINTER, got {spec!r}", file=sys.stderr)
            return 2
        case_id, pointer = spec.split("=", 1)
        if case_id not in {c.id for c in cases}:
            print(f"ERROR: --ignore-pointer names unknown case {case_id!r}", file=sys.stderr)
            return 2
        extra.setdefault(case_id, []).append(pointer)

    resolved = [
        replace(case, ignore_pointers=case.ignore_pointers + tuple(extra[case.id]))
        if case.id in extra
        else case
        for case in cases
    ]

    java_engine = create_async_engine(args.java_db_url, pool_pre_ping=True)
    python_engine = create_async_engine(args.python_db_url, pool_pre_ping=True)
    try:
        await seed(java_engine, args.run_id)
        await seed(python_engine, args.run_id)

        pre: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for table, _ in TABLES:
            pre[table] = {
                "java": await dump_table(java_engine, table),
                "python": await dump_table(python_engine, table),
            }

        # Tripwire: the Lombok-defaults page is compared in shape mode, but a
        # fixture that could outrank this sequence is worth naming explicitly.
        sort_guard = check_sorted_order_guard(
            pre["ai_agent_featured_conversation"]["java"], ceiling=2_000_000_000
        )

        java_responses = run_sequence(args.java_base_url, resolved)
        java_post = {
            table: await dump_table(java_engine, table) for table, _ in TABLES
        }
        python_responses = run_sequence(args.python_base_url, resolved)
        python_post = {
            table: await dump_table(python_engine, table) for table, _ in TABLES
        }
    finally:
        await java_engine.dispose()
        await python_engine.dispose()

    response_diffs = compare_responses(
        resolved, java_responses, python_responses, frozenset(args.ignore_header)
    )

    table_diffs: dict[str, list[dict[str, Any]]] = {}
    stamp_diffs: dict[str, list[dict[str, Any]]] = {}
    for table, key in TABLES:
        table_diffs[table] = diff_tables(
            java_post[table], python_post[table], key, project_cross
        )
        stamp_diffs[table] = stamp_tolerance_differences(
            java_post[table], python_post[table], key, args.timestamp_tolerance_seconds
        )

    # ``ai_agent_dialogue_session`` must be identical to its pre-state on both
    # sides: that is the proof ``create`` only *reads* it. ``update_time`` is
    # deliberately kept here (it is dropped from the cross-side diff) so a
    # sneaky write cannot hide behind the engine-column drop. ``create_time``
    # and ``id`` cannot change on an UPDATE and still come out equal across the
    # two clones' seeds, so they stay dropped.
    untouched_diffs: dict[str, list[dict[str, Any]]] = {}
    for side in ("java", "python"):
        diffs = diff_tables(
            pre["ai_agent_dialogue_session"][side],
            python_post["ai_agent_dialogue_session"]
            if side == "python"
            else java_post["ai_agent_dialogue_session"],
            "session_id",
            project_untouched,
        )
        if diffs:
            untouched_diffs[side] = diffs

    failures = {
        "responses": response_diffs,
        "tables": {t: d for t, d in table_diffs.items() if d},
        "stamps": {t: d for t, d in stamp_diffs.items() if d},
        "untouched": untouched_diffs,
    }
    total = sum(
        len(v) if isinstance(v, list) else sum(len(x) for x in v.values())
        for v in failures.values()
    )

    report = {
        "run_id": args.run_id,
        "java": {"base_url": args.java_base_url, "database": java_db},
        "python": {"base_url": args.python_base_url, "database": python_db},
        "cases": [
            {
                "id": c.id,
                "mode": c.mode,
                "method": c.method,
                "path": c.path,
                "ignore_pointers": list(c.ignore_pointers),
            }
            for c in resolved
        ],
        "java_responses": java_responses,
        "python_responses": python_responses,
        "warnings": {"sort_order_guard": sort_guard},
        "failures": failures,
        "difference_count": total,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"parity run={args.run_id} cases={len(resolved)} "
        f"java_db={java_db} python_db={python_db} differences={total}"
    )
    if sort_guard:
        print(json.dumps({"warnings": {"sort_order_guard": sort_guard}}, indent=2))
    if total:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--python-base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--java-db-url", required=True)
    parser.add_argument("--python-db-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--run-id",
        default=uuid.uuid4().hex[:12],
        help="scopes every sessionId; identical for both sides of one invocation",
    )
    parser.add_argument(
        "--ignore-pointer",
        action="append",
        default=[],
        metavar="CASE=POINTER",
        help="remove one JSON Pointer from one case's body compare (repeatable)",
    )
    parser.add_argument(
        "--ignore-header",
        action="append",
        default=[],
        help="drop one recorded header from the compare (repeatable)",
    )
    parser.add_argument("--timestamp-tolerance-seconds", type=float, default=300.0)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
