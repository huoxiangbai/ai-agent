# Migration risk register

Last updated: 2026-09-18

| ID | Risk | Evidence/impact | Mitigation and exit condition | Phase |
|---|---|---|---|---|
| R-01 | Java tests were configured to skip | parent POM hard-coded `<skipTests>true</skipTests>` | resolved: default is now false; stable modules gate CI and the legacy app suite remains visible | 0/1 |
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
| R-14 | No repository CI workflow was found | regressions relied on local execution | resolved: isolated Python workflow, stable Java gate and visible non-blocking legacy baseline added | 1 |
| R-15 | Existing user changes could be overwritten | `reactor-tool/uv.lock` is modified and `INTERVIEW_STUDY_GUIDE.md` is untracked | never edit/revert these files; review `git status` at every stage gate | all |
| R-16 | Nginx percentage routing can split related run-control calls | a run and its follow/stop/inject must share in-memory owner | hash the existing visitor cookie and route the whole Agent control family together | 9 |

## Current blockers

1. The Java application test suite has 65 known failing/erroring tests; it cannot yet be used as an all-green migration gate.
2. External-service tests need classification before they can be enabled in unattended CI.
3. Production credentials and provider availability are intentionally not validated during automated migration work.
4. Initial Java HTTP goldens require the full Java/tool stack and deterministic fixture identities to be running.
