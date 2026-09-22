# Database ownership matrix

Last updated: 2026-09-18

Shared reads are permitted during migration. For a given operation, Java and Python must never both be active writers. No application-level dual write is allowed.

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
| `sales_data` | demo/Data Agent query source | sample/query data; no XML mapper | phase 8 |
| `ai_agent_visitor_identity` | visitor filter/application service | insert, lookup by token digest, last-seen update, bind-name-if-absent | phase 3 read/resolve, phase 4 naming write |
| `ai_agent_dialogue_run` | run ledger and conversation replay | insert start then finish update; request ID is the logical identity | phase 7 |
| `ai_agent_dialogue_session` | session ledger/history | upsert session; visitor-scoped queries | phase 3 reads, phase 7 writes |
| `ai_agent_llm_invocation` | LLM ledger/replay | insert start then finish update | phase 7 |
| `ai_agent_tool_invocation` | tool ledger/replay | insert start then finish update | phase 7 |
| `ai_agent_user_question` | Ask User repository | insert plus CAS answer/claim/cancel/status updates; yield creation is transactional | phase 8 |
| `ai_agent_plan_approval` | Plan Approval repository | insert plus CAS decide/claim/cancel/status updates; yield creation is transactional | phase 8 |
| `ai_agent_tool_output_deep_search` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_code_interpreter` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_data_analysis` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_multimodal_agent` | tool-output writer/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_image_generation` | image service/tool/replay | batch persistence participates in explicit transaction; history pagination | phase 6 read, phase 7 write |
| `ai_agent_tool_output_canvas_publish` | Canvas tool-output/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_emit_ui_tree` | GenUI tool-output/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_tool_output_emit_ui_patch` | GenUI tool-output/replay | append keyed by invocation/request/tool-call | phase 7 |
| `ai_agent_artifact` | artifact ledger/history | batch insert; queried by run/tool/source | phase 6 read, phase 7 write |
| `ai_agent_featured_conversation` | public/admin featured services | upsert, status update, online/admin pagination | phase 3 reads, phase 4 writes |
| `ai_agent_ltm_curated_entry` | LTM service | insert, content update, soft delete, active selection | phase 8 |
| `ai_agent_working_memory_turn` | working-memory store | ordered turn allocation, insert, readiness invalidation | phase 8 |
| `ai_agent_working_memory_message` | working-memory/history/search | batch insert plus ordered/full-text/history queries | phase 3 history reads remain ledger-backed; phase 8 ownership |
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

## Migration rule

Before switching any write route, update this document from `Java` to `Python` ownership, deploy the Python writer, then change the exact Nginx route. Rollback reverses the route before re-enabling the Java writer. Schema changes are out of scope unless separately approved and applied with Alembic.
