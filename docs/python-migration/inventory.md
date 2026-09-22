# Java → Python migration inventory

Last updated: 2026-09-22

## Baseline

- Backend: Java 21, Spring Boot 3.4.3, Spring AI 1.1.4, MyBatis/MyBatis Plus (not JPA).
- Frontend: React 19. It calls the backend through `/web/`, `/api/`, and `/data/`.
- Tool service: the existing Python 3.11 `reactor-tool` remains a separate service.
- Storage: MySQL 8.4, plus optional Elasticsearch 7, Qdrant, ClickHouse/JDBC sources and local SQLite owned by `reactor-tool`.
- Size: 816 production Java files (about 82k lines), 170 Java test files (about 27k lines), 20 controllers, 108 method routes, 33 MySQL tables and 29 MyBatis mapper XMLs (plus 1 `mybatis-config.xml`; earlier docs said "30 XML mappers", which counted the config file).
- SSE counting: **6 handlers declare `produces = text/event-stream`, but only 5 are real `SseEmitter` streams.** `/web/health` declares the media type and returns a single plain `ok` body. Both counts are kept so route tables and content-type audits stay reconcilable.
- Deployment: Nginx (`docker/nginx.conf`) fronts the React SPA and proxies `/web/`, `/api/`, `/data/` to the Java backend on port 8100, plus `/tool/` to `reactor-tool` on port 1601. `reactor-sandbox` runs on 1602. The Python coexistence backend `reactor-backend-python` listens on `${PYTHON_BACKEND_PORT:-8200}` but has **no Nginx upstream** and is reachable only by direct port until a cutover adds one.
- Python side today: `GET /internal/health/live`, `GET /internal/health/ready`, and (non-prod only) `GET /docs`. Zero business routes, zero SSE server endpoints.

## Java module to Python package mapping

All Spring MVC HTTP surface lives in `Reactor-agent-trigger` (`org.wwz.ai.trigger.http`). No `@RestController`/`@Controller` exists in the other modules.

| Java module | Current responsibility | Python target |
|---|---|---|
| `Reactor-agent-app` | bootstrap, configuration, executors, Spring wiring | `reactor_backend.main`, `config`, lifespan wiring |
| `Reactor-agent-trigger` | HTTP/SSE controllers, filters, transport VOs | `api.routers`, `api.schemas`, middleware |
| `Reactor-agent-api` | shared request/response contracts | `api.schemas`, `shared.responses` |
| `Reactor-agent-case` | application use cases and stream orchestration | `application` |
| `Reactor-agent-domain` | agent runtime, tools, memory, ledger, data agent | `domain`, `runtime` |
| `Reactor-agent-infrastructure` | MyBatis, remote HTTP/SSE, repositories | `infrastructure.database`, `infrastructure.integrations` |
| `Reactor-agent-types` | response codes, executor config, request context | `shared` and `config` |

## HTTP surface

Unless explicitly marked, controller responses use the `{code, info, data}` envelope. Success is `code="0000"`; generic failure is `0001`, invalid input is `0002`, and login failure is `0003`.

**HTTP methods are exactly those listed.** Exception: the two `/web` handlers use `@RequestMapping` with no `method` attribute, so they accept **any** HTTP method (GET/POST/PUT/DELETE/PATCH/HEAD). A Python reimplementation that registers POST-only will diverge on 405 behaviour.

Phase legend: `0/1` baseline/infra · `3` side-effect-free read (the P3 pilot is the three public featured GETs) · `4` identity/CRUD write · `5` SSE/run control · `6` tool/skill/file · `7` core agent · `8` advanced runtime. **A route's phase may not precede the write-ownership phase of any table it touches.**

| Controller prefix | Routes | Kind | Planned phase | Owner | Verification | Rollback owner |
|---|---|---|---|---|---|---|
| `/web` | `ANY /health` (plain `ok` body, SSE media type only); `ANY /api/v1/gpt/queryAgentStreamIncr` (real SSE) | health / main agent | health `0/1`; stream `5, 7` | health: infra; stream: agent-runtime | health: live/ready probe; stream: SSE contract (deferred) | cutover owner |
| `/api/agent/visitor` | `GET /bootstrap`; `POST /naming` | identity (filter-protected; GET writes) | 4 | identity | HTTP contract case `visitor-bootstrap` (naming deferred) | cutover owner |
| `/api/agent/conversation/sessions` | `GET /`; `GET /{sessionId}` | history/replay (filter-protected; identity writes) | 4 | identity + ledger | HTTP contract cases `conversation-list`, `conversation-detail` | cutover owner |
| `/api/agent/featured-conversations` | `GET /home`; `GET /`; `GET /{featuredId}` | read-only featured content (P3 pilot) | 3 | featured-read | HTTP contract cases `featured-home`, `featured-list`, `featured-detail` | cutover owner |
| `/api/agent/session` | `GET /{sessionId}/capabilities`; `PUT /{sessionId}/capabilities` | capability read/write (not filter-protected; GET is a pure read) | 4 | capability | HTTP contract case `capability-get` (PUT deferred) | cutover owner |
| `/api/agent/run` | `POST /stop`; `POST /inject`; `POST /follow` | run control/SSE (atomic family) | 5 | run-control | SSE lifecycle/cancel (deferred) | cutover owner (whole family) |
| `/api/agent/ask-user` | `POST /answer`; `POST /resume`; `GET /pending`; `POST /cancel` | HITL/SSE | 8 (`resume` also in the P5 atomic family) | hitl-ask-user | CAS + restart tests (deferred) | cutover owner (whole family) |
| `/api/agent/plan-approval` | `POST /approve`; `POST /reject`; `POST /resume`; `GET /pending`; `POST /cancel` | HITL/SSE | 8 (`resume` also in the P5 atomic family) | hitl-plan-approval | CAS + restart tests (deferred) | cutover owner (whole family) |
| `/api/agent/file` | `POST /upload` | multipart/workspace | 6 (write op on `ai_agent_artifact`) | file-workspace | multipart + checksum (deferred) | cutover owner |
| `/api/agent/workspace` | `GET /{sessionId}/archive` | streaming ZIP | 6 | file-workspace | binary/Content-Disposition/checksum (deferred) | cutover owner |
| `/api/agent/image-generation` | `POST /generate`; `GET /history` | image tool/history | 6 (write op on `ai_agent_tool_output_image_generation`) | image-generation | batch atomicity + history pagination (deferred) | cutover owner |
| `/api/agent/genui` | `POST /export/pdf`; `POST /export/docx` | binary export | 6 | genui-export | binary headers/checksum (deferred) | cutover owner |
| `/api/v1/admin/featured-conversations` | `POST /create`; `PUT /update`; `POST /online/{featuredId}`; `POST /offline/{featuredId}`; `POST /query-list` | admin CRUD | reads `3` (only if proven side-effect-free); writes `4` | featured-admin | cloned-DB parity (deferred) | cutover owner |
| `/api/v1/admin/ai-client-api` | `POST /create`; `PUT /update-by-id`; `PUT /update-by-api-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-api-id/{apiId}`; `GET /query-by-id/{id}`; `GET /query-by-api-id/{apiId}`; `GET /query-enabled`; `POST /query-list`; `GET /query-all` | model provider CRUD | reads `3` (only if proven side-effect-free); writes `4` | ai-client-admin | cloned-DB parity (deferred) | cutover owner |
| `/api/v1/admin/ai-client-model` | `POST /test/{modelId}`; `POST /test-by-id/{id}`; `POST /create`; `PUT /update-by-id`; `PUT /update-by-model-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-model-id/{modelId}`; `GET /query-by-id/{id}`; `GET /query-by-model-id/{modelId}`; `GET /query-by-api-id/{apiId}`; `GET /query-by-model-type/{modelType}`; `GET /query-enabled`; `POST /query-list`; `GET /query-all` | model CRUD/connectivity | reads `3` (only if proven side-effect-free); writes + `/test*` `4` | ai-client-admin | cloned-DB parity; `/test*` = **live/manual suite only** (deferred) | cutover owner |
| `/api/v1/admin/ai-client-tool-mcp` | `POST /create`; `PUT /update-by-id`; `PUT /update-by-mcp-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-mcp-id/{mcpId}`; `GET /query-by-id/{id}`; `GET /query-by-mcp-id/{mcpId}`; `GET /query-all`; `GET /query-by-status/{status}`; `GET /query-by-transport-type/{transportType}`; `GET /query-enabled`; `POST /query-list` | MCP CRUD | reads `3` (only if proven side-effect-free); writes `4` | mcp-admin | cloned-DB parity + registry reload (deferred) | cutover owner |
| `/api/v1/admin/admin-user` | `POST /create`; `PUT /update-by-id`; `PUT /update-by-user-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-user-id/{userId}`; `GET /query-by-id/{id}`; `GET /query-by-user-id/{userId}`; `GET /query-by-username/{username}`; `GET /query-enabled`; `GET /query-by-status/{status}`; `POST /query-list`; `GET /query-all`; `POST /login`; `POST /validate-login` | admin identity | reads `3` (only if proven side-effect-free); writes + login `4` | admin-user | cloned-DB parity + login semantics (deferred) | cutover owner |
| `/api/v1/admin/skills` | `GET /list`; `POST /parse-package`; `POST /upload`; `POST /create`; `POST /import-url`; `DELETE /{name}`; `POST /reload` | filesystem/skill registry | 6 | skill-admin | workspace security + registry reload (deferred) | cutover owner |
| `/api/v1/admin/sub-agent-definitions` | `GET /query-list`; `GET /tool-catalog`; `GET /{agentKey}`; `POST /create`; `PUT /update`; `DELETE /{agentKey}`; `DELETE /delete`; `POST /reload` | sub-agent config | 8 | sub-agent-admin | cloned-DB parity + registry reload (deferred) | cutover owner |
| `/data` | `POST /queryModelInfo`; `POST /vectorRecall`; `POST /esRecall`; `POST /chatQuery`; `POST /apiChatQuery`; `POST /testQuery`; `POST /getNl2SqlReq`; `GET /allModels`; `GET /previewData` | Data Agent | 8 | data-agent | per-datastore fixtures + SQL safety (deferred; `chatQuery` SSE shape documented) | cutover owner |

Notes:

- `AiClientModel` connection-test routes are not read-only even though they do not write MySQL; they make external model calls and stay in phase 4. Their verification is an explicit **manual live suite** only — never unattended CI (see `risk-register.md` live/paid classification).
- **Handler-name collision:** `POST /data/queryModelInfo` is served by a handler also named `vectorRecall` (overloading the real `/data/vectorRecall` handler). Route registries must key on **path + verb**, never on Java method name.
- `ai_agent_artifact` and `ai_agent_tool_output_image_generation` each have **two writers**: the phase-6 upload/generate routes and the phase-7 in-run tool writers. Ownership is therefore recorded at operation granularity in `database-ownership.md`.

## Visitor cookie protection

`VisitorIdentityFilter` (order 2, `/*`) enforces visitor identity on these path prefixes only:

`/web/api/v1/gpt/queryAgentStreamIncr`, `/1/web/api/v1/gpt/queryAgentStreamIncr`, `/api/agent/visitor`, `/api/agent/conversation/sessions`, `/api/agent/file`, `/api/agent/workspace`, `/api/agent/run`, `/api/agent/ask-user`, `/api/agent/plan-approval`.

Everything else is **not** visitor-cookie protected: `/api/agent/session/*`, `/api/agent/featured-conversations/*`, `/api/agent/image-generation/*`, `/api/agent/genui/*`, all `/api/v1/admin/*`, all `/data/*`, `/web/health`.

Consequences that are contract data, not implementation details:

- Filter-protected GETs are **not pure reads**. A valid cookie updates `last_seen_at`/IP/User-Agent on `ai_agent_visitor_identity`; a missing or stale cookie inserts a visitor and returns `Set-Cookie`. These routes therefore cannot cut over before a single writer is assigned for that table's resolve/create/refresh operations (phase 4).
- **Legacy alias `/1/web/api/v1/gpt/queryAgentStreamIncr`** is matched by the filter but mapped by **no controller**. Requests hit the filter (and may receive `Set-Cookie`) and then 404. Recorded as a pending legacy artifact; not deleted during migration audits.
- `POST /api/agent/workspace/{sessionId}/archive` additionally calls `VisitorRequestContext.requireVisitorId()` even though it is a GET-shaped download.

## Frontend-only routes with no Java implementation

`ui/src/services/agent.ts` calls `/web/api/login`, `/web/api/getWhiteList` and `/web/api/reactor/apply`. No controller, mapper or config in the repository implements any of them. They are either dead UI code or an undocumented external surface. Recorded as **uncovered / pending determination**; the UI is out of migration scope so nothing is removed here.

## SSE surface and lifecycle

Six handlers declare `produces = text/event-stream`. Five of them return `SseEmitter` and are real event streams; `/web/health` is listed because of its declared media type but is **not** a stream.

| Route | Real stream? | Producer | Consumer expectations | Phase | Owner | Verification | Rollback owner |
|---|---|---|---|---|---|---|---|
| `/web/health` | **no** — single plain `ok` body | `AiAgentController` | content type is `text/event-stream` but there is no event framing | 0/1 | infra | live/ready probe | n/a |
| `/web/api/v1/gpt/queryAgentStreamIncr` | yes | main agent dispatch | any HTTP method; no automatic retry; visitor cookie; event IDs are persisted client-side | 5, 7 | agent-runtime | SSE contract (deferred) | cutover owner (atomic family) |
| `/api/agent/run/follow` | yes | attach/replay live run | heartbeat plus resumable event stream | 5 | run-control | SSE lifecycle (deferred) | cutover owner (atomic family) |
| `/api/agent/ask-user/resume` | yes | HITL resume | resumes yielded run and streams subsequent frames | 8 (P5 family) | hitl-ask-user | SSE lifecycle (deferred) | cutover owner (atomic family) |
| `/api/agent/plan-approval/resume` | yes | plan resume | resumes yielded run and streams subsequent frames | 8 (P5 family) | hitl-plan-approval | SSE lifecycle (deferred) | cutover owner (atomic family) |
| `/data/chatQuery` | yes | Data Agent | `THINK`, `CHART_DATA`, `ERROR`, `READY`, `DEBUG` payloads | 8 | data-agent | SSE contract (deferred) | cutover owner |

The main stream JSON envelope requires `status`, `packageType`, `finished`, optional `errorMsg`, and `resultMap`. When `resultMap.eventData` exists, the UI requires `messageOrder`, `messageType`, `messageId`, `taskId`, `taskOrder`, and nested `resultMap`. Unknown fields are intentionally retained by the frontend.

Data Agent `eventType` values are `THINK`, `CHART_DATA`, `ERROR`, `READY` and `DEBUG` (from `EventTypeEnum`). The producer also accepts free-form event-type strings via `ChatDataMessage.ofStatus`, so consumers must tolerate unknown `eventType` values rather than reject the frame.

The four stateful routes `/web/api/v1/gpt/queryAgentStreamIncr`, `/api/agent/run/*`, `/api/agent/ask-user/*` and `/api/agent/plan-approval/*` form one **atomic route family** and must share one upstream and one in-memory run owner. The whole family is in scope for that rule — not only the active-run subset.

## Runtime capabilities

Every capability below has a planned phase, a verification method and a rollback owner. Verification methods marked *deferred* have no case yet and are tracked in the `api-contracts.md` deferred registry.

| Capability | Detail | Phase | Verification | Rollback owner |
|---|---|---|---|---|
| Agent execution | ReAct and Plan-Solve strategies, prompt shaping, model selection/fallback, usage capture, maximum-turn handling and final-answer projection | 7 | scripted-fake event/ledger parity | cutover owner |
| Tools | workspace file ops, shell/code execution, code interpreter, data analysis, deep search, image generation, OCR, document/slides/spreadsheet generation and reading, Canvas/GenUI, social/search tools and task-list tools | 6 (adapters) / 7 (in-run) | fake-backed adapter contract + workspace security *deferred* | cutover owner |
| Skill runtime | directory discovery, Markdown parsing, package import/materialization, per-session workspace execution, bounded bash timeout and path guards | 6 | path-guard + subprocess-cancel tests *deferred* | cutover owner |
| MCP | configuration-backed servers, deferred discovery, resource listing/reading, tool-name normalization and execution | 6 | fake-backed adapter contract *deferred* | cutover owner |
| Human-in-the-loop | Ask User and Plan Approval: persisted records, CAS state transitions, in-memory pending registries, resume streams | 8 | CAS/restart/parity tests *deferred* | cutover owner |
| Sub-agents | definition registry, context isolation, foreground/background dispatch, concurrency gate, mailbox/progress and parent cancellation | 8 | parent/child cancel + restart tests *deferred* | cutover owner |
| Memory | working-memory turns/messages, compaction audit, curated LTM, LTM fork execution and optional session memory | 8 | recorded-session no-dup/no-loss *deferred* | cutover owner |
| Ledger/replay | dialogue sessions/runs, LLM/tool invocation ledgers, typed tool-output tables, artifacts and replay projectors | 7 | start/finish lifecycle + replay idempotency *deferred* | cutover owner |
| Run control | active-run registry, stop cancellation, injected messages, follow/reattach and SSE heartbeat | 5 | disconnect/cancel/backpressure, no leaked tasks *deferred* | cutover owner (atomic family) |
| Background work | session todo list, persistent background-task records, in-memory registries; Data Agent startup init is a `CommandLineRunner` | 8 | restart + orphan-running recovery *deferred* | cutover owner |

## External systems

`Test mode` says how automated migration tests may reach the system. `live/manual` means an explicitly invoked, auditable human suite only — never unattended CI.

| System | Use | Test mode | Phase | Verification | Rollback owner |
|---|---|---|---|---|---|
| OpenAI-compatible chat/image endpoints | main LLM, compaction/LTM extraction, image generation, web-search variants | fake / sanitized recording | 7 | scripted-fake parity | cutover owner |
| `reactor-tool` / `reactor-sandbox` | code interpreter, deep search, multimodal, data analysis, file/artifact service and sandboxed skill execution | fake | 6 | adapter contract + timeout/cancel | cutover owner |
| MCP servers | dynamically configured tools and resources | fake | 6 | adapter contract | cutover owner |
| MySQL 8.4 | application configuration, identity, ledgers, memory and task state | dedicated test DB | all | cloned-DB parity | cutover owner |
| Elasticsearch 7 | Data Agent schema/value recall | fixture | 8 | per-datastore fixture tests | cutover owner |
| Qdrant | vector recall | fixture | 8 | per-datastore fixture tests | cutover owner |
| ClickHouse and arbitrary JDBC sources | Data Agent query execution | fixture | 8 | fixture + SQL-injection/dialect safety | cutover owner |
| Exa and configured search providers | web search | fake / sanitized recording | 6 | fake-backed contract | cutover owner |
| `AiClientModel` connection tests (`/test*`) | admin connectivity probe | **live/manual** | 4 | explicit manual suite only | cutover owner |

## Concurrency, timeout, retry and cancellation baseline

- Default development concurrency: dispatch 32, LLM 32, task 16, tool 16. Production currently raises LLM to 128, task to 64 and tool to 32.
- Main LLM timeout is 1,200 seconds; tool batch timeout is 5,400 seconds; compaction summarizer timeout is 120 seconds; skill bash timeout is 120 seconds with a 600-second maximum.
- Shared outbound HTTP pools bound total/per-host requests. Individual adapters specify connect/read/write/call timeouts.
- Java uses bounded platform/virtual-thread executors. Rejection is surfaced as a busy error rather than silently leaving incomplete futures.
- Cancellation propagates from active runs to futures, remote HTTP/SSE calls, tool batches and sub-agents. Client disconnect detection is implemented around `SseEmitter`.
- Retry is feature-specific. LLM and connection retries must be inventoried per adapter; non-idempotent tool and write operations must not receive generic automatic retries.

## Configuration inventory

- Server and database: port, main/query data sources and MySQL pool settings.
- Visitor identity: cookie name, HttpOnly, Secure, SameSite, path, max age and allowed origins.
- Execution: virtual-thread flags, four executor pools, heartbeat and sub-agent acquire timeout.
- Agent: LLM timeout, HTTP pool, workspace root/limits, skill directories/limits and compaction thresholds.
- Integrations: model/provider records in MySQL, `reactor-tool`, image/search providers, Elasticsearch, Qdrant and Data Agent JDBC catalogs.
- Observability: Spring Actuator exposes health, info, metrics and Prometheus at `/actuator/*`. **Nginx does not proxy `/actuator/`** — only `/web/`, `/api/`, `/data/` and `/tool/` — so Actuator is reachable only on direct port 8100.
- CORS: a global `CorsFilter` (order 1, `/*`) allows `allowedHeaders=*` and `allowedMethods=*`; credentials plus explicit origins apply only when `visitorCookie.allowedOrigins` is configured. Six controllers additionally carry class-level `@CrossOrigin(origins="*")` (`AdminUserAdmin`, `AiClientApiAdmin`, `AiClientModelAdmin`, `AiClientToolMcpAdmin`, `SkillAdmin` — GET/POST/DELETE/OPTIONS only — and `AgentSessionCapability` — GET/PUT/OPTIONS). `FeaturedConversationAdmin` and `SubAgentDefinitionAdmin` have no class-level CORS annotation. This inconsistency is contract data.
- Error shaping: there is **no** `@ControllerAdvice`, `@ExceptionHandler` or `ErrorController`. Each handler catches and maps into the `{code, info, data}` envelope, so business errors normally stay HTTP 200. A Python reimplementation must not introduce a global HTTP error policy or FastAPI 307/422 drift.
- Python coexistence backend (`backend-python/`): env-only config with prefix `REACTOR_PY_` — `APP_NAME`, `ENVIRONMENT`, `HOST`, `PORT` (default 8200), `LOG_LEVEL`, `DATABASE_URL`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_POOL_SIZE`, `MYSQL_MAX_OVERFLOW`, `MYSQL_POOL_RECYCLE_SECONDS`, `DATABASE_READY_TIMEOUT_SECONDS`. Secrets are `SecretStr` with `repr=False`; the DSN is built with `quote_plus`. Compose overrides the port via `PYTHON_BACKEND_PORT`.
- Python unused dependency: `sse-starlette` is declared in `backend-python/pyproject.toml` but never imported by `src/`. Harmless today; flagged so it is not mistaken for an SSE server implementation.
