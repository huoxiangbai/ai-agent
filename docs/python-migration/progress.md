# Java → Python migration progress

Last updated: 2026-09-25

| Phase | Status | Evidence | Exit gate |
|---|---|---|---|
| 0. Audit and baseline | Complete (re-verified 2026-09-22) | inventory, API contract, ownership matrix, risk register, real Java test results, and the governance matrix with stage/verification/rollback owner per capability | passed: all discovered surfaces assigned (108 routes, 33 tables, 10 runtime capabilities, 9 external systems); unknowns are risks |
| 1. Python skeleton | Complete (re-verified 2026-09-22) | image built; MySQL 8.4 initialized 33 tables; live/ready 200; **15 unit tests**, Ruff and mypy pass | passed: Python service and database are healthy; full-stack build is a repeatable coexistence check |
| 2. Contract harness | In progress | reusable HTTP/SSE capture, endpoint allowlists, sanitized Java recording, diff CLI and initial manifest; deferred registry now explicit | one documented command records the first sanitized goldens, and the runner can compare a Python response against a stored Java golden offline. **This is phase-2 scope and does not wait for phase 3 routes** (aligned with `staged-prompts.md` phase 2 Done when). The first live dual comparison follows once phase 3 routes exist |
| 3. Read-only APIs | **3A + 3B implemented (2026-09-23)** | 3 public featured GETs in `backend-python/`, now **live behind Nginx** on exactly those three paths; 185 non-integration tests; 50 tool-projector key-order tests; Java characterization 13/13; contract **7/7** zero diffs (`phase3-featured.json` 3/3 + `phase3-featured-errors.json` 4/4, both `skipped: []`); cutover/rollback drill green in all four phases with `$upstream_addr` attribution. 3B log below | 3A done when: unit/integration/contract parity + the three routes serve under a read-only MySQL account + ExecPlan holds cutover/rollback. 3B done when: three paths hit Python, everything else hits Java, UI-shaped requests + contract + frontend green before/after, 5xx not increased, rollback actually performed and verified then re-applied, syntax check + rollback timing recorded. **Both met.** Residual: the collation probe row in `api-contracts.md` is still unprobed (reassigned to phase 4). Scope remains the three public featured GETs only |
| 4. CRUD/auth | **First slice done (2026-09-25): `featured-admin`**; visitor identity writes, capability write, and the other admin CRUD families **not started** | the 5 admin routes on `/api/v1/admin/featured-conversations` serve from Python behind an exact-path Nginx fragment; **256** non-integration tests, **47** integration tests; ruff + mypy clean; contract **15/15** `skipped: []` byte-identical on re-record; cloned-DB parity `differences=0` over 32 cases with all four affected-table groups equal; drill green in `pre`/`on-python`/`on-java` (17 probes each, `routing_violations=0`, `diffs_vs_reference=0`), cutover **0.087s**, rollback **0.084s** apply + **0.512s** verified; two-layer writer fence observed live (`owner=java` → four writes `200 + 0001` with zero SQL). Log below | exclusive write ownership and concurrency/rollback tests **met for this slice**: one writer account scoped to one table, a fail-closed owner flag, `create`/`update` transaction-rollback tests, duplicate/unique-key, idempotent and concurrent-race tests, and both switch directions drilled. Not met for the phase: visitor identity writes, capability write, and the remaining admin families still have no owner fence. Also owns the other filter-protected GETs. The collation probe row in `api-contracts.md` is still unprobed (owner phase 4, not closed by this slice) |
| 5. SSE/run control | Not started | — | lifecycle/cancellation parity with no leaked tasks |
| 6. Tool/Skill/MCP | Not started | — | fake-backed compatibility and workspace security tests |
| 7. Core Agent Runtime | Not started | — | recorded state/event/ledger parity |
| 8. Advanced runtime | Not started | — | restart/fault/idempotency parity per capability |
| 9. Rollout/retirement | Not started | — | 14-day full-Python window, Java stop, second 14-day window |

## Baseline verification log

### 2026-09-18: `mvn -DskipTests=false test`

- Result: failed before reaching domain tests.
- `Reactor-agent-api` and `Reactor-agent-types` compiled, but Surefire still printed `Tests are skipped` because the parent POM hard-codes the plugin option.
- Dependency resolution then tried to update `~/.m2/repository/org/bouncycastle/bcpkix-jdk18on/resolver-status.properties` and failed with `Operation not permitted` in the managed sandbox.
- This is an environment/configuration failure, not a passing or failing application-test baseline.

### 2026-09-18: real Java baseline after enabling Surefire

- The hard-coded test skip was replaced by a default-off `skipTests` Maven property; command-line overrides still work.
- A Logback ABI collision was exposed because `xfg-wrench-starter-design-framework` embeds an older Logback API. Dependency order was corrected without changing runtime behavior, and the previously failing `PlanApprovalResumeApplicationServiceTest` then passed.
- `Reactor-agent-domain`: 178 tests passed.
- `Reactor-agent-case`, `Reactor-agent-infrastructure`, and `Reactor-agent-trigger`: passed in the full reactor run.
- `Reactor-agent-app`: 469 tests executed; 12 failed, 53 errored, 0 skipped. Failures are now visible instead of globally hidden.
- Dominant legacy failure classes: ignored/missing `application-test.yml` and datasource fixtures; working-directory/path assumptions; blank Qdrant test configuration; and stale replay, deep-search, Skill, workspace, session-memory and projector assertions.
- These failures are recorded baseline debt. They are not treated as migration regressions and are not hidden by re-enabling global skip.

### 2026-09-18: Python skeleton and Compose verification

- `uv sync --all-groups` completed with CPython 3.11.12.
- `.venv/bin/pytest -m 'not integration'`: 15 passed, 1 optional MySQL test deselected.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/mypy src`: passed for 29 source files.
- `docker compose config --quiet`: passed with explicit test-only passwords.
- `reactor-backend-python` image built successfully.
- Compose MySQL 8.4 became healthy and initialized all 33 schema tables.
- `GET /internal/health/live`: HTTP 200 without dependency access.
- `GET /internal/health/ready`: HTTP 200 after MySQL became available; its initial 503 during database startup verifies fail-closed readiness behavior.
- The full Java/frontend/reactor-tool build was started separately to validate all-service coexistence; it does not make model requests.

### 2026-09-22: phase 0/1 governance and coexistence re-audit

Scope: documentation and test-governance reconciliation only. No business routes, no Nginx change, no schema change, no writes.

- `cd backend-python && uv sync --all-groups`: ok (40 packages).
- `uv run ruff check .`: `All checks passed!`
- `uv run mypy src`: `Success: no issues found in 29 source files`.
- `uv run pytest -m "not integration"`: **15 passed, 1 deselected** in 0.66s. This settles the 15-vs-6 contradiction — `15` is correct and the Phase 1 checklist figure of `6` was stale.
- Counts verified against code: 20 controllers, 108 method routes, 33 tables all match the docs. `produces=text/event-stream` appears on 6 handlers, of which **5 are real `SseEmitter` streams** (`/web/health` is not).
- Mappers: 29 MyBatis mapper XMLs + 1 `mybatis-config.xml` (the earlier "30 XML mappers" counted the config file).
- Dual-write check: the Python backend executes no DML (`SELECT 1` only). All 33 tables are Java-written. **No live dual-write path exists.**
- Governance gaps found and closed in this pass: `docs/python-migration/execplans/` did not exist; the four-way test classification never existed; 108/108 routes had no migration owner and 0/108 had a rollback owner; only 7/108 routes had a verification case and the rest were not even deferred.
- Live/paid tests classified from the pre-existing `Reactor-agent-app/pom.xml` surefire excludes (15 classes, commit `4bda2a39c`). This closes risk-register blocker 2.
- `mvn -B -pl Reactor-agent-case -am -DskipTests=false test`: **BUILD SUCCESS**. `Reactor-agent-domain` 178 tests / 0 failures / 0 errors / 0 skipped (matches the 2026-09-18 figure); `Reactor-agent-case` 2 tests / 0 failures (includes `PlanApprovalResumeApplicationServiceTest`, previously failing). `Reactor-agent-api` and `Reactor-agent-types` compile but contain no tests.
- **Gate coverage finding.** That command builds only 5 modules (parent, api, types, domain, case). It does **not** compile `Reactor-agent-trigger` (which holds all 108 HTTP routes) or `Reactor-agent-infrastructure` (which holds all mappers). The documented "stable baseline" therefore cannot catch a type or compile error in the HTTP layer. Recorded as a gap; the 2026-09-18 note about infrastructure/trigger passing refers to a *full reactor* run, not this command.
- Not run in this pass: MySQL integration (`TEST_MYSQL_URL` needs a dedicated test database), full Compose smoke (needs the tool-stack env file and image build), full Java app suite (already recorded as 12 failed / 53 errored — re-running would not change the classification and must not be used to hide anything).

### 2026-09-18: contract harness verification

- HTTP snapshots compare status, media type, selected headers, JSON field/type/null/value behavior, pagination payloads and Cookie attributes.
- Cookie values are never persisted: they are fingerprinted or replaced only by an endpoint-level allowlist.
- JSON nondeterminism uses per-case JSON pointers with wildcard support; there is no global ignore list.
- SSE captures compare HTTP status, media type, ordered events, comments/heartbeats, JSON data, UTF-8, EOF, timeout, HTTP error, transport error and size-limit termination.
- `reactor-contract --record-java` can persist sanitized Java-only goldens before a Python implementation exists.
- Initial safe manifest covers visitor bootstrap, featured home/list/detail, conversation list/detail and session capabilities. Fixture-bound cases skip explicitly when fixture environment variables are absent.

## Phase 1 acceptance checklist

- [x] Python 3.11 FastAPI service exists at `backend-python/` and uses `uv`.
- [x] Package boundaries are `api`, `application`, `domain`, `runtime`, `infrastructure`, and `shared`.
- [x] Configuration contains no checked-in secrets.
- [x] Structured logs redact credentials and include Request ID.
- [x] `/internal/health/live` does not access dependencies.
- [x] `/internal/health/ready` checks MySQL with a bounded timeout.
- [x] Startup creates one async SQLAlchemy engine and shutdown disposes it.
- [x] Docker service `reactor-backend-python` listens on 8200 and coexists in Compose with Java and `reactor-tool`.
- [x] Unit tests, Ruff and mypy pass (`15 passed`, `1` optional MySQL test deselected — re-verified 2026-09-22; the earlier `6` figure was stale).
- [x] Java test skipping is made visible/default-off without changing business behavior.
- [x] Existing user changes remain untouched.
- [x] Build the Python image and verify readiness against the Compose MySQL service.

## Phase 2 acceptance checklist

- [x] Uses `JAVA_BASE_URL` and `PYTHON_BASE_URL` with bounded timeouts.
- [x] Produces machine-readable, path-specific, sanitized difference reports.
- [x] Supports Java-only golden recording without contacting Python.
- [x] HTTP comparison includes status, content type, JSON, null/type behavior, errors, pagination, selected headers and Cookie attributes.
- [x] SSE comparison includes ordered events, heartbeats, UTF-8 and normal/abnormal termination.
- [x] Nondeterministic fields are endpoint-local allowlists.
- [x] Local unit tests do not invoke paid LLMs or external providers.
- [x] Every route is covered or explicitly deferred (`api-contracts.md` deferred registry, added 2026-09-22).
- [x] Record initial goldens from a running Java service using deterministic database fixtures. *(done 2026-09-23 — `tests/contract/golden/java-initial.json`, 7/7 cases, `skipped: []`. See the Phase 2 verification log below.)*
- [x] Compare a Python response against a stored Java golden offline (phase 2 scope; does not require phase 3 routes). *(done 2026-09-23 — `--golden` + `--response` runs with no server contacted at all. The Python side is a recorded capture document; see the self-verification note below.)*
- [x] Add the missing `tests/contract/fixtures/fake-agent-request.json` and `tests/contract/golden/`. *(done 2026-09-23 — plus `fixtures/contract-seed.sql` and a pinned `fixtures/skills/` tree.)*
- [ ] Execute initial Java/Python comparisons after the corresponding phase 3 routes are implemented. *(partially done 2026-09-23 — the three featured GETs now exist in `backend-python/` and an offline comparison reports 3/3 `matched: true` with zero differences against `tests/contract/golden/java-featured.json`. Still open: a **live** record-and-compare against a running Python under `reactor_py_ro`, blocked on the operator-supplied secret (R-34). Not claimed complete.)*

### Phase 2 verification log (2026-09-23)

Real commands, real results. Nothing below is inferred.

**Recording — one command once Java and the throwaway MySQL are up:**

```bash
cd backend-python
JAVA_BASE_URL=http://127.0.0.1:8100 \
CONTRACT_VISITOR_TOKEN=fixture-raw-token \
CONTRACT_SESSION_ID=fixture-session \
CONTRACT_FEATURED_ID=fixture-featured \
uv run reactor-contract tests/contract/cases/initial.json \
  --record-java --output tests/contract/golden/java-initial.json
```

Result: 7/7 cases captured, `skipped: []`, 15613 bytes. Secret scan over the golden
reported **0 hits** for raw cookies, API keys, full user prompts and provider
responses; 7 leaves carry the `"<contract-ignored>"` sentinel.

Recording runtime: a throwaway `mysqld` on port 3307 with its own datadir under
`build/contract-recording/` (`--no-defaults` plus an explicit `--datadir` on every
invocation, because the Homebrew `my.cnf` and the compiled-in default both point
at `/usr/local/var/mysql`, which this slice must not touch), seeded from
`tests/contract/fixtures/contract-seed.sql`; Java started with
`--spring.profiles.active=prod` and test-only `spring.datasource.mysql.*`
overrides. Full command sequence is in
`docs/python-migration/execplans/contract-lab.md` and
`backend-python/tests/contract/README.md`.

**Repeatability self-check:** re-seeding the fixture and re-recording produced a
**byte-identical** golden (`cmp` clean).

**Offline comparison — no server contacted:**

```bash
uv run reactor-contract tests/contract/cases/initial.json \
  --golden tests/contract/golden/java-initial.json \
  --response /tmp/golden-repeat.json \
  --output /tmp/contract-self-check.json
```

Result: 7/7 `matched: true`, 0 differences, exit 0. Report shape is
`{"mode":"comparison","cases":[{"name","matched","java","python","differences"}],"skipped":[]}`.

> **This is comparator self-verification, not Python parity.** Both sides of that
> comparison are Java recordings. It proves the offline path round-trips a golden
> and reports differences at the right paths — it does **not** prove Python
> behaves like Java, because Python has no business routes yet. The real
> Java/Python comparison is the checklist item above, gated on phase 3. Saying
> otherwise would be faking coverage.

**Adversarial self-check (six mutations of a golden copy):**

```
mutations: value, type, removal, additive, cookie-attr, allowlisted-sentinel
exit=1  (expect 1)
  DIFF  visitor-bootstrap            /cookies/0/attributes/httponly      value mismatch
  DIFF  featured-home-default        /body/data/0/title                  value mismatch
  DIFF  featured-list-first-page     /body/data/total                    type mismatch
  DIFF  featured-detail-fixture      /body/data/<keys>                   field mismatch
  DIFF  conversation-session-list    /body/data/0/<keys>                 field mismatch
  PASS  conversation-session-detail
  PASS  session-capabilities
```

Five mutation classes land on exactly the expected `(path, reason)`. The sixth —
a sentinel rewritten on a path the case's allowlist declares — correctly passes,
which is what proves the allowlist is per-case rather than a global suppressor.

**Gates:**

```
uv run ruff check .                    → All checks passed!
uv run mypy src                        → Success: no issues found in 29 source files
uv run pytest -m "not integration"     → 44 passed, 1 deselected, 2 warnings
```

Test count went from `15 passed, 1 deselected` to `44 passed, 1 deselected`.
The nine required dimensions each have a named test: status, type, null,
ordering, Cookie, UTF-8, EOF, timeout, error — plus additive policy, golden
round-trip, offline CLI and pointer hardening.

**Remaining blockers and open items:**

- The checklist item above (real Java/Python comparison) is blocked on phase 3
  routes. Not a defect of this slice.
- This slice's diff is not committed yet.
- The comparator cannot yet measure multipart bodies, binary exports (checksum /
  `Content-Disposition`), streaming-ZIP Zip Slip containment, the full SSE
  corpus, or cross-block `last-event-ID`. All five are registered in the
  *comparator capability deferred registry* in `api-contracts.md`. Uncovered is
  not reported as covered.
- Two facts the plan got wrong and measurement corrected: the nondeterministic
  field on cases 4/6 is `resultMap/eventData/taskId` (a replay-time UUID), **not**
  `useTimes`; and the visitor cookie **does** carry `Secure` under the `prod`
  profile, contrary to the `application.yml` default. Both are recorded in
  `risk-register.md` and the ExecPlan.

## Phase 3A verification log (2026-09-23)

Scope: the three public featured GETs in `backend-python/`
(`/api/agent/featured-conversations/home`, `/api/agent/featured-conversations`,
`/api/agent/featured-conversations/{featuredId}`). Read-only SQL, no identity
writes, no application-level dual write, no Nginx change, no admin writes.
ExecPlan: `docs/python-migration/execplans/featured-public-read.md`.

Real commands, real results. Blocked gates are labelled blocked and are not
reported as green.

**Python gates:**

```
uv run ruff check .                     → All checks passed!
uv run mypy src                         → Success: no issues found in 48 source files
uv run pytest -m "not integration"      → 183 passed, 23 deselected
uv run pytest tests/unit/test_tool_projectors.py → 50 passed
```

Unit count went 44 → 133 → **183** across the slice (the second jump is the
tool-projector rewrite; see below).

**Java characterization:**

```
mvn -B -pl Reactor-agent-app -am -Dtest='FeaturedConversation*' \
  -DskipTests=false -Dsurefire.failIfNoSpecifiedTests=false test
```

Module total 28 run / 7 error — **all seven are `initializationError` on nested
stub classes**, a known surefire 2.6 quirk (R-31). Class-level results are the
signal per R-02/R-18:

```
FeaturedConversationPublicQueryApplicationServiceTest   13 run, 0 failures, 0 errors
FeaturedConversationRepositoryTest                       2 run, 0 failures, 0 errors
FeaturedConversationAdminControllerTest                  3 run, 0 failures, 0 errors
```

**Offline contract comparison (3/3):**

```bash
cd backend-python
CONTRACT_VISITOR_TOKEN=fixture-raw-token CONTRACT_SESSION_ID=fixture-session \
CONTRACT_FEATURED_ID=fixture-featured \
  uv run reactor-contract tests/contract/cases/phase3-featured.json \
    --golden tests/contract/golden/java-featured.json \
    --response build/python-responses.json \
    --output build/contract-report-offline.json
```

Result: exit 0, `cases: 3`, `skipped: []`, 3/3 `matched: true`,
`differences: []`.

> **A first run of this reported only 2 of 3 cases and still exited 0.** The
> comparator re-substitutes `${CONTRACT_*}` at *compare* time; without
> `CONTRACT_FEATURED_ID` the detail case lands in `skipped` as
> `"featured-detail-fixture: missing CONTRACT_FEATURED_ID"`. **Gate on
> `len(cases)` and `skipped == []`, never on the exit code alone** (R-32). The
> diff field is named `differences` (empty → `[]`), not `diffs`.

> **What this does and does not prove.** Both sides are stored documents:
> `tests/contract/golden/java-featured.json` (Java) vs `build/python-responses.json`
> (Python, recorded earlier in the slice). It is **not** a live re-record. The
> tool-projector rewrite landed *after* that recording, so the saved responses
> predate it. The rewrite cannot affect these three cases because
> `tests/contract/fixtures/contract-seed.sql` inserts **no**
> `ai_agent_tool_*` / `ai_agent_artifact` rows — those code paths are never
> reached. That is an inference from the seed contents, not a re-run.

**Compose:**

```
MYSQL_PASSWORD=test-only MYSQL_ROOT_PASSWORD=test-only \
REACTOR_PY_MYSQL_PASSWORD=test-only-ro docker compose config --quiet   → exit 0
```

`reactor-backend-python` now connects as `reactor_py_ro` via the dedicated
`REACTOR_PY_MYSQL_USER` / `REACTOR_PY_MYSQL_PASSWORD` variables (deliberately
not `MYSQL_USER`/`MYSQL_PASSWORD`). This closes the R-22 phase-3 half.

**Frontend consumer tests (unchanged `ui/`):** 4 files / 6 tests passed via
`npx vitest run`.

**Tool-projector rewrite (same slice, later pass).** The Decision Log's original
"tool 帧族内层形状显式 deferred" call was superseded the same day: all 10
projector families were ported byte-exact from Java source (plus
`ArtifactRelativePath`, `ToolArtifactFormatter.normalizeWorkspacePath`,
`mergeFileRefs`' three branches, `markMissingLinks`' `String.valueOf(null) ==
"null"` semantics) and pinned by 50 key-order unit tests rather than by golden.
Three real repository defects were fixed on the way: `_output_file_refs` was
missing `visibility == "visible"`; deep_search hydration exposed per-stage named
keys instead of `stages` + `_rebuild_chapters`; `fileRefs` was attached to tools
whose Java output type declares none.

**Blocked — not done, not claimed:**

- `TEST_MYSQL_URL=… uv run pytest -m integration` re-run. The previous 23-test
  run predates the repository changes, and `featured_read_edge_seed.sql`
  exercises exactly the changed paths (`_output_file_refs`, `_FILE_REF_TOOLS`).
  Needs the `reactor_py_ro` password.
- Contract re-record + R-28 repeatability re-check. Needs the same secret and a
  DB seeded with **only** `contract-seed.sql` (R-33).
- `_rebuild_chapters` has no fixture coverage — neither seed inserts
  `ai_agent_tool_output_deep_search`.
- `UserQuestionReader` is ported as a Protocol defaulting to `None` (matching
  Java's null-repo constructor path) and is not bound to a DB adapter.

The `reactor_py_ro` password is deliberately absent from the repository and must
be supplied by the operator out of band. Hunting for it in MySQL client
credential stores is prohibited (R-34).

## Phase 4 verification log (2026-09-25) — first slice: `featured-admin`

Scope: the five admin routes on `/api/v1/admin/featured-conversations` and the
single table they own, `ai_agent_featured_conversation`. ExecPlan:
`docs/python-migration/execplans/featured-admin.md`. Nothing else in phase 4
(visitor identity, capability write, other admin families) was touched.

**Gates, re-run 2026-09-25 on the final tree:**

| Command | Result |
|---|---|
| `uv run ruff check src/ tests/` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 52 source files |
| `uv run pytest -m "not integration"` | **256 passed**, 47 deselected, 1.82s |
| `set -a; . build/admin-mysql/test.env; set +a; uv run pytest -m integration` (:13307) | **47 passed**, 256 deselected |
| `reactor-contract …/phase4-featured-admin.json --record-java` then `cmp` against the committed golden | **byte-identical** |
| `reactor-contract … --golden tests/contract/golden/java-featured-admin.json` (live Python :18200) | `cases=15 skipped=[] differing=[] matched=15`, exit 0 |
| `tests/parity/featured_admin_parity.py` (two DBs cloned from one snapshot, Java then Python) | `run=d29acc404650 cases=32 differences=0`, `failures={responses:[], tables:{}, stamps:{}, untouched:{}}`, `warnings.sort_order_guard=[]` |
| `tests/cutover/admin_drill.sh` `check pre` → `cutover` → `check on-python` → `rollback` → `check on-java` | each check: 17 probes, `routing_violations=0`, `diffs_vs_reference=0`, contract 15/`skipped=[]`, 11 UI tests passed. Cutover **0.087s**; rollback apply **0.084s**, end-to-end verified **0.512s** |
| owner fence, live (`REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER=java`) | all four writes `200 + {"code":"0001"}` with **zero SQL**; `query-list` and `/internal/health/ready` still 200 |
| `cd ui && npx vitest run` (the 3 admin consumer files) | 11 passed |

**Parity — how "before/after are equivalent" was actually shown.** One snapshot
was loaded into `ai_agent_station_java` and `ai_agent_station_py` (the script
exits 2 if both URLs name the same database). The identical 32-case sequence ran
against Java first, then Python, each on its own database — never two writers on
one — and the responses, the full contents of `ai_agent_featured_conversation`,
the `ai_agent_dialogue_session` non-write witness (compared cross-side *and*
pre-vs-post with `update_time` kept), and the public read paths after
`online`/`offline` all came back equal: `differences=0`.

**A clone pair drift this run caught (worth recording).** The first parity
invocation of the day exited 1 with `differences=7`, naming a `ro-denied` row
present only on the Python side and `fixture-featured.summary='denied'`. Root
cause: *my own* earlier integration attempt had exported
`TEST_MYSQL_URL` pointing at the **writer** account on `ai_agent_station_py`,
so the read-only-denial test's `INSERT`/`UPDATE` succeeded there (its `DELETE`
and `CREATE` were denied, which is exactly why the row survived). Not a
repository defect — and precisely the class of contamination R-33 describes. The
harness did its job: it reported the drift as a named finding before any write
rather than as a mystery diff at the end. Repair was to restore the two columns
and re-run: `differences=0`.

**Blocked / not claimed:**

- Contract re-record against **production** credentials and the repository
  integration suite under `reactor_py_ro` — R-34, needs the operator's secret.
  Everything above ran against throwaway accounts on `127.0.0.1:13307`.
- Java characterization (`mvn -pl Reactor-agent-app -am -Dtest='FeaturedConversation*'`)
  was **not** re-run for this slice: the app baseline is red for unrelated
  reasons (R-02/R-18). The byte-identical `--record-java` re-record plus the
  32-case response equality are the Java-side evidence used instead.
- The `status='ONLINE'` collation probe row in `api-contracts.md` is still
  unprobed (owner phase 4, not closed by this slice).
