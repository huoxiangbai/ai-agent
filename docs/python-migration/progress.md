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
- [x] Record initial goldens from a running Java service using deterministic database fixtures. *(done 2026-09-23 — `tests/contract/golden/java-initial.json`, 7/7 cases, `skipped: []`. See the Phase 2 verification log below.)*
- [x] Compare a Python response against a stored Java golden offline (phase 2 scope; does not require phase 3 routes). *(done 2026-09-23 — `--golden` + `--response` runs with no server contacted at all. The Python side is a recorded capture document; see the self-verification note below.)*
- [x] Add the missing `tests/contract/fixtures/fake-agent-request.json` and `tests/contract/golden/`. *(done 2026-09-23 — plus `fixtures/contract-seed.sql` and a pinned `fixtures/skills/` tree.)*
- [ ] Execute initial Java/Python comparisons after the corresponding phase 3 routes are implemented. *(unchanged — **gated on phase 3**. Python has no business routes yet, so there is nothing honest to compare end to end.)*

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
