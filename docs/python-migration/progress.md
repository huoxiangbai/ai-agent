# Java → Python migration progress

Last updated: 2026-09-22

| Phase | Status | Evidence | Exit gate |
|---|---|---|---|
| 0. Audit and baseline | Complete (re-verified 2026-09-22) | inventory, API contract, ownership matrix, risk register, real Java test results, and the governance matrix with stage/verification/rollback owner per capability | passed: all discovered surfaces assigned (108 routes, 33 tables, 10 runtime capabilities, 9 external systems); unknowns are risks |
| 1. Python skeleton | Complete (re-verified 2026-09-22) | image built; MySQL 8.4 initialized 33 tables; live/ready 200; **15 unit tests**, Ruff and mypy pass | passed: Python service and database are healthy; full-stack build is a repeatable coexistence check |
| 2. Contract harness | In progress | reusable HTTP/SSE capture, endpoint allowlists, sanitized Java recording, diff CLI and initial manifest; deferred registry now explicit | one documented command records the first sanitized goldens, and the runner can compare a Python response against a stored Java golden offline. **This is phase-2 scope and does not wait for phase 3 routes** (aligned with `staged-prompts.md` phase 2 Done when). The first live dual comparison follows once phase 3 routes exist |
| 3. Read-only APIs | Not started | — | unit/integration/contract parity and exact-path rollback. **Scope is the three public featured GETs only** (see the 2026-09-22 decision below) |
| 4. CRUD/auth | Not started | — | exclusive write ownership and concurrency/rollback tests. Also owns visitor identity writes and the other filter-protected GETs |
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
- [ ] Record initial goldens from a running Java service using deterministic database fixtures.
- [ ] Compare a Python response against a stored Java golden offline (phase 2 scope; does not require phase 3 routes).
- [ ] Add the missing `tests/contract/fixtures/fake-agent-request.json` and `tests/contract/golden/`.
- [ ] Execute initial Java/Python comparisons after the corresponding phase 3 routes are implemented.
