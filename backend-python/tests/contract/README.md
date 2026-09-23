# Java/Python contract runner

The runner sends each manifest request to a service and writes a JSON report
containing sanitized snapshots and path-specific differences. It has four modes
that all share one capture document shape, so any recorded document can feed any
comparison.

```bash
export JAVA_BASE_URL=http://127.0.0.1:8100
export PYTHON_BASE_URL=http://127.0.0.1:8200
export CONTRACT_VISITOR_TOKEN=fixture-raw-token
export CONTRACT_SESSION_ID=fixture-session
export CONTRACT_FEATURED_ID=fixture-featured
```

## Recording

Record a sanitized Java-only golden (never contacts Python):

```bash
reactor-contract tests/contract/cases/initial.json \
  --record-java --output tests/contract/golden/java-initial.json
```

Record a sanitized Python-only response document (never contacts Java) — from
phase 3 on, when Python has business routes:

```bash
reactor-contract tests/contract/cases/initial.json \
  --record-python --output build/python-responses.json
```

Both write the same document shape:

```json
{"mode": "java-baseline" | "python-capture", "base_url": "...",
 "cases": [{"name": "...", "snapshot": {...}} | {"name": "...", "error": "..."}],
 "skipped": []}
```

`base_url` is recorded for audit only and never participates in a comparison.

## Comparing

Fully offline — no server is contacted at all:

```bash
reactor-contract tests/contract/cases/initial.json \
  --golden tests/contract/golden/java-initial.json \
  --response build/python-responses.json \
  --output build/contract-report.json
```

Live Python against a stored golden:

```bash
reactor-contract tests/contract/cases/initial.json \
  --golden tests/contract/golden/java-initial.json \
  --output build/contract-report.json
```

Live dual-call (the original mode, neither `--golden` nor `--response`):

```bash
reactor-contract tests/contract/cases/initial.json --output build/contract-report.json
```

Reports always have this shape, and the exit code is 1 when any case differs or
errors — a failure is never hidden:

```json
{"mode": "comparison",
 "cases": [{"name": "...", "matched": true,
            "java": {...}, "python": {...},
            "differences": [{"path": "...", "java": ..., "python": ..., "reason": "..."}]}],
 "skipped": []}
```

## Normalization and the allowlist

Nondeterministic values may only be removed by an exact JSON Pointer declared in
that case. `*` fans out over every key of an object or every element of a list.
There is deliberately no global ignore list.

**Pointer root.** For HTTP the root is the capture document
(`HttpSnapshot.as_dict()`), so a body field is `/body/data/visitorId` and a
cookie attribute is `/cookies/*/attributes/expires` — one namespace. For SSE the
root is the event's `data` value (for example `/requestId`).

**One pointer list, two semantics.**

| When | What it does | Use it for |
|---|---|---|
| capture | `normalize_json` replaces the leaf with `"<contract-ignored>"` | a value that exists on both sides but is nondeterministic (generated IDs, clock-derived timestamps) |
| compare | `drop_additive` deletes the leaf from the **candidate only** | a field that only Python returns (an additive field) |

The asymmetry is intentional: a field present in the golden but missing from the
candidate is **always** a difference. Removal is breaking and no allowlist
suppresses it. List elements are never deleted — a longer list is a length
difference, not an additive field.

A pointer whose final object key is absent is a no-op (that is what makes the
same list work for additive declarations). A missing *intermediate* key, a
non-integer or out-of-range list index, or descending into a scalar raises
`ValueError`, so a mistyped allowlist fails loudly instead of silently ignoring
nothing.

Cookie values are never written to reports: deterministic values use a SHA-256
fingerprint and explicitly allowlisted random values use the fixed marker
`"<contract-ignored>"`. Cookie **name and attributes remain part of the
comparison** — `Path`, `Domain`, `Expires`, `Max-Age`, `SameSite`, `Secure` and
`HttpOnly` are all compared.

## SSE

SSE uses a separate runner so its termination mode, heartbeats and ordered events
remain visible. The request body must be a checked-in, non-paying local fixture:

```bash
reactor-sse-contract /local/fake-agent-stream --method POST \
  --body tests/contract/fixtures/fake-agent-request.json \
  --ignore-pointer /requestId --output build/sse-contract-report.json
```

| Covered | Capability |
|---|---|
| yes | ordered events, `id` / `event` / `retry` / multi-line `data`, comment heartbeats, UTF-8 |
| yes | termination `eof` / `http-error` / `timeout` / `transport-error` / `size-limit`, plus `status_code` / `content_type` / `error_type` |
| yes | per-event allowlist pointers rooted at the event `data` value |
| **deferred** | cross-block last-event-ID persistence (`event_id` is block-local) |
| **deferred** | unparseable `retry` silently becomes `null` |
| **deferred** | full SSE corpus: reconnect / follow / stop / inject / resume, terminal states |
| **deferred** | streaming-ZIP Zip Slip / symlink containment |

See `docs/python-migration/api-contracts.md` for the comparator capability
deferred registry.

## Fixtures and goldens

Cases whose required fixture environment is missing are reported as skipped. Use
only the dedicated throwaway test database and local service fakes. None of the
initial cases invokes an Agent run or a paid model.

- `fixtures/contract-seed.sql` — deterministic seed. Idempotent (fixed-key
  `DELETE` then `INSERT`), explicit `id` plus every `ORDER BY` column pinned, all
  timestamps fixed literals under `Asia/Shanghai`. **Never run it against a
  shared or production database**: it deletes and re-inserts fixture rows and
  empties `ai_client_tool_mcp`.
- `fixtures/skills/` — a pinned skill tree. Recording passes
  `--autobots.autoagent.skill.directories[0]=.../fixtures/skills` so `skills[]`
  does not drift with the repo's `runtime/skills/`.
- `fixtures/fake-agent-request.json` — the SSE request body. Placeholder fields
  only: no secrets, no real user prompts, no provider responses.
- `golden/java-initial.json` — the recorded Java baseline. Must never contain raw
  cookies, API keys, full user prompts or paid-provider responses.

Fixed identities used by the seed and the environment variables above:

| Variable | Value |
|---|---|
| `CONTRACT_VISITOR_TOKEN` | `fixture-raw-token` (`token_digest` is its SHA-256 hex, hard-coded in the seed) |
| — | `visitor_id` = `fixture-visitor-0001` |
| `CONTRACT_SESSION_ID` | `fixture-session` |
| `CONTRACT_FEATURED_ID` | `fixture-featured` |

## Notes for anyone reproducing a recording

- `mysqld` must be started with `--no-defaults` **and** an explicit `--datadir`:
  the Homebrew `my.cnf` and the compiled-in default both point at a datadir that
  must not be touched.
- When passing
  `--autobots.autoagent.skill.directories[0]=...` to `java`, quote the whole
  argument. zsh otherwise treats `[0]` as a glob and the launch fails with
  `no matches found`.
- Contract tooling constructs every `httpx.AsyncClient` with `trust_env=False`.
  On this machine a **system-level** proxy (visible via
  `urllib.request.getproxies()`, not via any environment variable) hijacks
  `127.0.0.1`, and recording fails with a bare disconnect. Do not drop that flag.
- Cookie `Secure` is `true` under `--spring.profiles.active=prod`. Recording
  under a different profile produces a golden that cannot be compared against
  this one.
