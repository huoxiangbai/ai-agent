# Database ownership matrix

Last updated: 2026-09-23

Shared reads are permitted during migration. For a given operation, Java and Python must never both be active writers. No application-level dual write is allowed. Ownership is recorded at **operation** granularity where a table has more than one writer path.

Current state (verified 2026-09-23): the Python coexistence backend executes no DML at all — its only SQL is `SELECT 1` in `infrastructure/database/engine.py`. All 33 tables are written exclusively by Java today. There is **no live dual-write path**.

The phase-3 read-only account **`reactor_py_ro`** is now provisioned as a reviewed plain-SQL migration, `db/migrations/20260923_provision_phase3_readonly_account.sql`. It holds `GRANT USAGE ON *.*` and `GRANT SELECT ON \`<database>\`.*` and nothing else — every write statement is rejected with `ERROR 1142`. Verified on 2026-09-23 against a throwaway MySQL 9.3 with the real schema loaded: SELECT works through the project's own `asyncmy` driver, and INSERT/UPDATE/DELETE/TRUNCATE/DROP/ALTER/CREATE/INDEX are all denied. Re-applying the migration is idempotent and never widens a grant.

What is **not** done: nothing on the Python *connection* side — `reactor-backend-python` now connects as `reactor_py_ro` (see `docker-compose.yml` → `REACTOR_PY_MYSQL_USER: ${REACTOR_PY_MYSQL_USER:-reactor_py_ro}`, `REACTOR_PY_MYSQL_PASSWORD: ${REACTOR_PY_MYSQL_PASSWORD:?...}`), which closes the phase-3A acceptance item "Python serves the three interfaces under a read-only MySQL account". The remaining gap is on the **write** side: Java and Python would still share `reactor` for writes until phase 4 provisions per-writer credentials (see the guardrail table below). Until those land, "single writer" for writes is still only a process control.

**Caution — do not reuse the write account for the Python service.** The compose variables are deliberately *not* `MYSQL_USER`/`MYSQL_PASSWORD`; pointing `REACTOR_PY_MYSQL_USER` at `reactor` silently removes the technical enforcement that `reactor_py_ro` provides.

| Table | Current reader/writer | Transaction or concurrency behavior | Python takeover |
|---|---|---|---|
| `admin_user` | admin user controller/repository | generated ID; login query; CRUD statements are currently single-call transactions | phase 4 |
| `ai_client_api` | model-provider admin and runtime catalog | generated ID; update by numeric/business ID | phase 4 |
| `ai_client_model` | model admin, model catalog/resolver | generated ID; cache invalidated after writes; connection tests call external provider | phase 4 |
| `ai_client_tool_mcp` | MCP admin/runtime registry | generated ID; registry/cache reload after writes | phase 4 |
| `ai_agent_session_capability` | capability service | upsert per session/kind/ref; controls runtime tool visibility | phase 4 |
| `ai_agent_sub_agent_definition` | definition admin/loader | soft delete and registry reload | phase 8 |
| `chat_model_info` | Data Agent model service | MyBatis Plus; model refresh deletes/rebuilds related metadata | phase 8 |
| `chat_model_schema` | Data Agent model service | deleted/rebuilt with model info; enclosing service has `@Transactional` | phase 8 |
| `sales_data` | **seed-only — no application writer.** Production code has zero references; the only writes are the MySQL initdb seed in `db/data.sql` | sample/query data; no XML mapper | phase 8 (read-only query source) |
| `ai_agent_visitor_identity` | visitor filter/application service | insert, lookup by token digest, last-seen update, bind-name-if-absent | **phase 4 — resolve/create/refresh and naming are one identity-write domain.** There is no phase-3 "read": filter-protected GETs write this table |
| `ai_agent_dialogue_run` | run ledger and conversation replay | insert start then finish update; request ID is the logical identity | phase 7 |
| `ai_agent_dialogue_session` | session ledger/history | upsert session; visitor-scoped queries | phase 4 reads (the HTTP route is gated by the identity write above), phase 7 writes |
| `ai_agent_llm_invocation` | LLM ledger/replay | insert start then finish update | phase 7 |
| `ai_agent_tool_invocation` | tool ledger/replay | insert start then finish update | phase 7 |
| `ai_agent_user_question` | Ask User repository | insert plus CAS answer/claim/cancel/status updates; yield creation is transactional | phase 8 |
| `ai_agent_plan_approval` | Plan Approval repository | insert plus CAS decide/claim/cancel/status updates; yield creation is transactional | phase 8 |
| `ai_agent_tool_output_deep_search` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_code_interpreter` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_data_analysis` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_multimodal_agent` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_image_generation` | image service/tool/replay | batch persistence participates in explicit transaction; history pagination | **operation-granular:** write via `POST /api/agent/image-generation/generate` → phase 6; write via in-run image tool → phase 7; reads phase 6 |
| `ai_agent_tool_output_canvas_publish` | Canvas tool-output/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_emit_ui_tree` | GenUI tool-output/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_emit_ui_patch` | GenUI tool-output/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_artifact` | artifact ledger/history | batch insert; queried by run/tool/source | **operation-granular:** write via `POST /api/agent/file/upload` → phase 6; write via in-run tool → phase 7; reads phase 6 |
| `ai_agent_featured_conversation` | public/admin featured services | upsert, status update, online/admin pagination | phase 3 reads (public featured GETs — the P3 pilot), phase 4 writes |
| `ai_agent_ltm_curated_entry` | LTM service | insert, content update, soft delete, active selection | phase 8 |
| `ai_agent_working_memory_turn` | working-memory store | ordered turn allocation, insert, readiness invalidation | phase 8 |
| `ai_agent_working_memory_message` | working-memory/history/search | batch insert plus ordered/full-text/history queries | history reads stay ledger-backed until phase 8; interim behaviour needs its own parity check. Full ownership phase 8 |
| `ai_agent_working_memory_compaction` | compaction audit | append-only event | phase 8 |
| `ai_agent_ltm_fork_execution` | LTM fork audit | append-only event | phase 8 |
| `ai_agent_session_todo` | task-list persistence | sequence allocation, upsert and soft delete | phase 8 |
| `ai_agent_background_task` | background-task registry | upsert and reload; orphaned running tasks become failed after restart | phase 8 |

## Transaction boundaries to preserve

- `ChatModelInfoService` updates model and schema metadata atomically.
- `UserQuestionYieldService` persists an open question before yielding control.
- `PlanApprovalYieldService` persists an open approval before yielding control.
- `ImageGenerationBatchPersistenceServiceImpl` persists a generated batch atomically.
- Ledger start/finish pairs are deliberately separate lifecycle writes; Python must not wrap a long LLM/tool execution in one database transaction.
- Ask User and Plan Approval transitions use compare-and-set SQL. Python must use the same guarded predicates and treat a zero-row update as a conflict/idempotent repeat, not as unconditional success.
- **Cross-table mappers.** `working_memory_message_mapper.xml` and `tool_invocation_ledger_mapper.xml` each issue statements spanning three tables (including `ai_agent_dialogue_session`, `ai_agent_dialogue_run` and `ai_agent_artifact`). Cloned-DB parity comparisons must diff all of those tables, not only the mapper's nominal one.
- **A route's phase may not precede the write-ownership phase of any operation it performs.** Where a table has two writers (see `ai_agent_artifact`, `ai_agent_tool_output_image_generation`), assign ownership per operation before switching either route.

## Migration rule

Before switching any write route, update this document from `Java` to `Python` ownership at operation granularity, deploy the Python writer, then change the exact Nginx route. Rollback reverses the route before re-enabling the Java writer.

Schema changes are out of scope unless separately approved. Today the repository's actual migration practice is plain SQL under `db/migrations/*.sql` (see `db/migrations/20260829_drop_legacy_agent_config_and_tool_outputs.sql`). **Alembic is not installed or configured** — no `alembic.ini`, no `alembic/` directory, no dependency in `backend-python/pyproject.toml`. Any future schema change therefore needs one of: (a) a follow-up approved task that introduces Alembic plus its own rollout/rollback plan, or (b) explicit approval to keep using reviewed plain-SQL migrations. Earlier revisions of this file and of `AGENTS.md` claimed Alembic was already the rule; that claim was inaccurate and is corrected here.

## Technical guardrail gap

**Half closed 2026-09-23.** Two credentials were required to give the single-writer rule teeth; one now exists.

| Credential | Status | Effect |
|---|---|---|
| Read-only account for phase-3 reads | **provisioned and in force 2026-09-23** — `reactor_py_ro`, `db/migrations/20260923_provision_phase3_readonly_account.sql` | a Python read path physically cannot write. `reactor-backend-python` connects as `reactor_py_ro` (`docker-compose.yml`); INSERT/UPDATE/DELETE raise `ERROR 1142`, asserted by `backend-python/tests/integration/test_readonly_account_denies_writes.py`. |
| Per-writer credentials for phase-4 writes | **not provisioned** | Java and Python would still share `reactor` for writes. |

Remaining gap, precisely: **phase-3A is closed** — `reactor-backend-python` connects as `reactor_py_ro` and the compose environment takes the secret as the required `REACTOR_PY_MYSQL_PASSWORD` variable. What is still open is writes: `reactor-backend` (Java) keeps `reactor`, and phase 4 has not provisioned per-writer write credentials, so a future Python writer would still share that account. Per-writer write credentials are a phase-4 prerequisite and are **not** to be invented early.

**Residual verification gap (2026-09-23):** the 1142 rejection was re-verified against a throwaway MySQL 9.3 during phase 3A, and the integration suite asserts it — but that suite has **not** been re-run against the current repository code, because doing so needs the `reactor_py_ro` password, which is deliberately absent from the repository and must be supplied by the operator. Treat "in force for the running stack" as a **configuration** claim backed by `docker-compose.yml` and the 1142 assertions, not as a fresh end-to-end run.

The password for `reactor_py_ro` is deliberately absent from the repository. The migration takes it as the session variable `@reactor_py_ro_password` and aborts with a self-explanatory error if it is unset, empty, shorter than 12 characters, or outside `[A-Za-z0-9_+=.@-]`. Never pass it on the `mysql` command line.
