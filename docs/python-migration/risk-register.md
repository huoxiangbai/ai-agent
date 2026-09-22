# Migration risk register

Last updated: 2026-09-22

| ID | Risk | Evidence/impact | Mitigation and exit condition | Phase |
|---|---|---|---|---|
| R-01 | Java tests were configured to skip | parent POM hard-coded `<skipTests>true</skipTests>` | **fixed in the working tree but UNCOMMITTED** (`M pom.xml`, `M Reactor-agent-app/pom.xml`, `M Reactor-agent-domain/pom.xml`). Default is now false and the legacy app suite is visible. Exit condition: the fix is committed and no longer depends on a dirty tree | 0/1 |
| R-02 | Java application test baseline is red | real run: app module executed 469 tests with 12 failures and 53 errors; most involve missing ignored configs, path assumptions and stale fixtures | keep stable modules as the blocking CI gate; run the full legacy baseline visibly and retire categories deliberately | 0/1 |
| R-03 | SSE is richer than a basic text stream | frontend merges by event IDs, orders and nested tool IDs; disconnect is not terminal | golden SSE recorder plus lifecycle/cancellation tests before route cutover | 2/5 |
| R-04 | Active run state is partly in memory | stop/inject/follow and pending registries require backend affinity | stable visitor-cookie cohort; all run-control routes use the same upstream; restart tests | 5/9 |
| R-05 | Cross-runtime shared writes can corrupt state | 33 tables include CAS workflows and start/finish ledgers | table/operation ownership matrix, exact-path cutover, no dual write | all |
| R-06 | MyBatis semantics may differ from ORM defaults | generated keys, conditional updates, null handling and dynamic filters | async SQLAlchemy Core with SQL-equivalence tests; defer ORM refactors | 3/4 |
| R-07 | Timezone/serialization drift | JDBC explicitly uses `Asia/Shanghai`; Java date serialization may differ | boundary fixtures for naive/aware times, nulls and JSON output | 2-4 |
| R-08 | External tests may spend money or leak credentials | model/image/search/MCP calls are runtime-configured | local fakes and sanitized recordings in automation; explicit manual real-provider suite | all |
| R-09 | Generic retries can duplicate side effects | tools create files, ledger rows and remote jobs | retry only idempotent operations; add idempotency keys where already supported | 5-8 |
| R-10 | Workspace escape or command injection | Skill and shell tools execute in per-session workspaces | realpath containment, symlink and traversal tests, bounded subprocess API | 6 |
| R-11 | Java executor behavior is not equivalent to unbounded asyncio | production LLM concurrency reaches 128 and rejects excess work | explicit semaphores/queues, busy response, TaskGroup cancellation and metrics | 5-8 |
| R-12 | Memory/replay can duplicate or lose semantic events | compaction protects messages; replay rebuilds UI tool outputs | recorded-session parity, tool call/result pairing and replay idempotency tests | 7/8 |
| R-13 | Data Agent has additional datastores and SQL dialects | ES7, Qdrant, ClickHouse/JDBC and Calcite utilities | migrate last, with service-specific fixtures and query safety tests | 8 |
| R-14 | No repository CI workflow was found | regressions relied on local execution | **added in the working tree but UNCOMMITTED** (`.github/workflows/python-backend.yml`, `.github/workflows/java-baseline.yml` are untracked). Exit condition: the workflows are committed and green on a clean checkout | 1 |
| R-15 | Existing user changes could be overwritten | `reactor-tool/uv.lock` is modified and `INTERVIEW_STUDY_GUIDE.md` is untracked | never edit/revert these files; review `git status` at every stage gate | all |
| R-16 | Nginx percentage routing can split related run-control calls | a run and its follow/stop/inject must share in-memory owner | hash the existing visitor cookie and route the whole Agent control family together | 9 |
| R-17 | **New regressions in `Reactor-agent-app` never block CI** | `java-baseline.yml` gates only `mvn -pl Reactor-agent-case -am` (api/domain/infrastructure/types/trigger, not app); the app suite runs in `legacy-application-baseline` with `continue-on-error: true`. The 65 known failures are visible, but so is any new regression | accepted for now (decision 2026-09-22): documented as a known blind spot. Exit condition: either a baseline-snapshot gate that blocks only on new failures, or the app suite becomes green | 0/1 |
| R-18 | **The Java app baseline is structurally irreproducible** | `.gitignore` excludes `/Reactor-agent-app/src/main/resources/application-test.yml` while `application.yml` and `application-prod.yml` are tracked. A fresh clone can never make the legacy suite green, and the 65 failures cannot be independently reproduced | tracked as an open risk. Do not widen the ignore. Exit condition: a sanitized `application-test.yml` template is committed, or the failure list is captured as a reproducible baseline fixture | 0/1 |
| R-19 | **Production Java source is excluded from version control** | `.gitignore` excludes `…/domain/agent/service/execute/auto/step/` and `…/auto1/step/` ("自执行旧目录仅保留本地"). Clean checkouts silently lose that code and cannot reproduce local builds | tracked as an open risk. Exit condition: the directories are either committed or their removal is an explicit approved decision | 0/1 |
| R-20 | Frontend calls three routes with no implementation | `ui/src/services/agent.ts` calls `/web/api/login`, `/web/api/getWhiteList`, `/web/api/reactor/apply`; no controller/mapper/config implements them | pending determination (dead UI code vs undocumented external surface). UI is out of migration scope. Listed in the deferred registry | open |
| R-21 | Legacy `/1/web/...` path can issue cookies on a 404 | `VisitorIdentityFilter` matches `/1/web/api/v1/gpt/queryAgentStreamIncr` but no controller maps `/1/` | recorded, not deleted. Exit condition: an explicit decision to keep or drop the alias, then a filter/controller change in one approved task | open |
| R-22 | Single-writer rule has no technical enforcement | both backends share the read-write MySQL account `reactor`; no read-only account exists | provision a read-only account for phase-3 reads and per-writer credentials before any Python writer ships | 3-4 |
| R-23 | Docs claimed a schema tool that does not exist | `AGENTS.md` and `database-ownership.md` required Alembic; no Alembic config/dependency exists. Actual practice is `db/migrations/*.sql` | corrected in both documents on 2026-09-22. Exit condition: a schema change either introduces Alembic in its own approved task or explicitly approves reviewed plain-SQL migrations | all |
| R-24 | Frontend consumer tests have no CI enforcement | `ui/package.json` has `vitest run` (~85 test files) but neither workflow runs it, while `PLANS.md` lists consumer tests as acceptance evidence | document the gap; add a UI job only in an approved CI task | all |
| R-25 | **The documented Java "stable baseline" never compiles the HTTP layer** | `mvn -B -pl Reactor-agent-case -am` builds only parent/api/types/domain/case. `Reactor-agent-trigger` (all 108 routes) and `Reactor-agent-infrastructure` (all mappers) are not dependencies of `case`, so a compile or type error there is invisible to the blocking gate. Verified 2026-09-22 | widen the blocking gate to also build `Reactor-agent-trigger` and `Reactor-agent-infrastructure` (compile-only is enough) in an approved CI task | 0/1 |

## Test classification (blocking gate / known baseline debt / live-paid / uncovered)

This four-way split is required by the phase 0/1 constraints and was missing until 2026-09-22. Nothing here may be moved to a weaker bucket to make a run look green.

### Blocking gate (must pass; a failure stops the migration)

- Python: `uv run ruff check .`, `uv run mypy src`, `uv run pytest -m "not integration"` in `backend-python/`.
- Java stable baseline: `mvn -B -pl Reactor-agent-case -am -DskipTests=false test` (api/domain/infrastructure/types/trigger/case).
- `docker compose config --quiet` with test-only passwords.
- Contract diffs once a slice produces them: zero unexplained differences.

### Known baseline debt (visible, currently non-blocking, never a parity excuse)

- `Reactor-agent-app`: 469 tests executed, 12 failed, 53 errored (2026-09-18 run). Dominant classes: missing/ignored `application-test.yml` and datasource fixtures, working-directory assumptions, blank Qdrant config, stale replay/deep-search/Skill/workspace/session-memory/projector assertions.
- `Reactor-agent-domain`: 178 tests passed — not debt.
- **Non-blocking exemption boundary.** `PLANS.md` forbids "把红色测试标成非阻塞". The `continue-on-error: true` on `legacy-application-baseline` is allowed **only** as baseline-debt visibility for the already-recorded 65 failures. It is not equivalence evidence, and it must never be used to absorb a migration-introduced regression. Any new failure class is a regression and blocks. See R-17 for the residual blind spot.
- No per-test inventory of the 65 exists yet — only failure categories. "Retire categories deliberately" therefore has no tracker.

### Live / paid (explicit manual suite only — never unattended CI)

Registered from the `Reactor-agent-app/pom.xml` surefire excludes (commit `4bda2a39c`, 2026-04). Those excludes **predate the migration docs and are not a migration-era ignore expansion**. 15 classes: `ElkBlacklistDataTest`, `domain/AgentTest`, `domain/AutoAgentTest`, `domain/FlowAgentExecuteTest`, `prompt/DynamicAutoAgentTest`, `prompt/TraePromptTest`, and `spring/ai/AiAgentMCPESTest`, `spring/ai/AiAgentStepTest`, `spring/ai/AiAgentTest`, `spring/ai/AiSearchMCPTest`, `spring/ai/AutoAgentTest`, `spring/ai/DynamicRateLimitQueryTest`, `spring/ai/FlowAgentMCPTest`, `spring/ai/FlowAgentTest`, `spring/ai/OpenAiTest`. POM comment: "默认回归仅执行可离线复现的测试，以下用例依赖外部模型、MCP 或独立服务环境".

This closes former blocker 2 — those tests are now classified. They stay excluded from default runs and require an explicitly invoked, auditable manual suite. Also live/manual: `POST /api/v1/admin/ai-client-model/test/{modelId}` and `/test-by-id/{id}` (external model calls), and the browser-side direct call to `${baseUrl}/v1/chat/completions` in `ui/src/services/imageGeneration.ts`.

### Uncovered / deferred

- 101 of 108 method routes have no endpoint-specific verification case; they are listed in the `api-contracts.md` deferred registry with an owner phase. Silence is not coverage.
- Multipart, binary ZIP/PDF/DOCX and the SSE corpus have no comparison capability yet.
- Contract fixtures and goldens are absent: `tests/contract/fixtures/fake-agent-request.json` (referenced by `tests/contract/README.md`) and `tests/contract/golden/` do not exist.
- MySQL integration tests and a real Compose smoke are not exercised by CI (no MySQL service container, no integration job, no docker build/contract job).
- Runtime capabilities and external systems have phase/verification/rollback entries in `inventory.md`, but every verification marked *deferred* has no case.

## Current blockers

1. The Java application test suite has 65 known failing/erroring tests; it cannot yet be used as an all-green migration gate. *(unchanged)*
2. ~~External-service tests need classification before they can be enabled in unattended CI.~~ **Closed 2026-09-22** — see the live/paid section above.
3. Production credentials and provider availability are intentionally not validated during automated migration work. *(unchanged)*
4. Initial Java HTTP goldens require the full Java/tool stack and deterministic fixture identities to be running. *(unchanged; phase 2 scope)*
5. R-01/R-14 fixes live only in an uncommitted working tree — the migration must not depend on a dirty tree.
6. R-17: new `Reactor-agent-app` regressions cannot block CI.
7. R-25: the blocking Java gate does not compile `Reactor-agent-trigger` or `Reactor-agent-infrastructure`.
