# Java → Python migration progress

Last updated: 2026-09-18

| Phase | Status | Evidence | Exit gate |
|---|---|---|---|
| 0. Audit and baseline | Complete | inventory, API contract, ownership matrix, risk register and real Java test results recorded | passed: all discovered surfaces assigned; unknowns are risks |
| 1. Python skeleton | Complete | image built; MySQL 8.4 initialized 33 tables; live/ready 200; 15 unit tests, Ruff and mypy pass | passed: Python service and database are healthy; full-stack build is a repeatable coexistence check |
| 2. Contract harness | In progress | reusable HTTP/SSE capture, endpoint allowlists, sanitized Java recording, diff CLI and initial manifest | record initial Java goldens and run first live dual comparison after phase 3 routes exist |
| 3. Read-only APIs | Not started | — | unit/integration/contract parity and exact-path rollback |
| 4. CRUD/auth | Not started | — | exclusive write ownership and concurrency/rollback tests |
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
- [x] Unit tests, Ruff and mypy pass (`6 passed`, `1` optional MySQL test deselected).
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
- [ ] Record initial goldens from a running Java service using deterministic database fixtures.
- [ ] Execute initial Java/Python comparisons after the corresponding phase 3 routes are implemented.
