# Java → Python migration inventory

Last updated: 2026-09-18

## Baseline

- Backend: Java 21, Spring Boot 3.4.3, Spring AI 1.1.4, MyBatis/MyBatis Plus.
- Frontend: React 19. It calls the backend through `/web/`, `/api/`, and `/data/`.
- Tool service: the existing Python 3.11 `reactor-tool` remains a separate service.
- Storage: MySQL 8.4, plus optional Elasticsearch 7, Qdrant, ClickHouse/JDBC sources and local SQLite owned by `reactor-tool`.
- Size: 816 production Java files (about 82k lines), 170 Java test files (about 27k lines), 20 controllers, 108 method routes, 6 SSE routes, 33 MySQL tables and 30 XML mappers.
- Deployment: Nginx fronts the React SPA, Java backend on port 8100 and `reactor-tool` on port 1601. `reactor-sandbox` runs on 1602.

## Java module to Python package mapping

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

| Controller prefix | Routes | Kind | Planned phase |
|---|---|---|---|
| `/web` | `GET/REQUEST /health`; `POST/REQUEST /api/v1/gpt/queryAgentStreamIncr` | SSE/main agent | 5, 7 |
| `/api/agent/visitor` | `GET /bootstrap`; `POST /naming` | identity | 3, 4 |
| `/api/agent/conversation/sessions` | `GET /`; `GET /{sessionId}` | read-only history/replay | 3 |
| `/api/agent/featured-conversations` | `GET /home`; `GET /`; `GET /{featuredId}` | read-only featured content | 3 |
| `/api/agent/session` | `GET /{sessionId}/capabilities`; `PUT /{sessionId}/capabilities` | capability read/write | 3, 4 |
| `/api/agent/run` | `POST /stop`; `POST /inject`; `POST /follow` | run control/SSE | 5 |
| `/api/agent/ask-user` | `POST /answer`; `POST /resume`; `GET /pending`; `POST /cancel` | HITL/SSE | 8 |
| `/api/agent/plan-approval` | `POST /approve`; `POST /reject`; `POST /resume`; `GET /pending`; `POST /cancel` | HITL/SSE | 8 |
| `/api/agent/file` | `POST /upload` | multipart/workspace | 6 |
| `/api/agent/workspace` | `GET /{sessionId}/archive` | streaming ZIP | 6 |
| `/api/agent/image-generation` | `POST /generate`; `GET /history` | image tool/history | 6 |
| `/api/agent/genui` | `POST /export/pdf`; `POST /export/docx` | binary export | 6 |
| `/api/v1/admin/featured-conversations` | `POST /create`; `PUT /update`; `POST /online/{featuredId}`; `POST /offline/{featuredId}`; `POST /query-list` | admin CRUD | 3, 4 |
| `/api/v1/admin/ai-client-api` | `POST /create`; `PUT /update-by-id`; `PUT /update-by-api-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-api-id/{apiId}`; `GET /query-by-id/{id}`; `GET /query-by-api-id/{apiId}`; `GET /query-enabled`; `POST /query-list`; `GET /query-all` | model provider CRUD | 3, 4 |
| `/api/v1/admin/ai-client-model` | `POST /test/{modelId}`; `POST /test-by-id/{id}`; `POST /create`; `PUT /update-by-id`; `PUT /update-by-model-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-model-id/{modelId}`; `GET /query-by-id/{id}`; `GET /query-by-model-id/{modelId}`; `GET /query-by-api-id/{apiId}`; `GET /query-by-model-type/{modelType}`; `GET /query-enabled`; `POST /query-list`; `GET /query-all` | model CRUD/connectivity | 3, 4 |
| `/api/v1/admin/ai-client-tool-mcp` | `POST /create`; `PUT /update-by-id`; `PUT /update-by-mcp-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-mcp-id/{mcpId}`; `GET /query-by-id/{id}`; `GET /query-by-mcp-id/{mcpId}`; `GET /query-all`; `GET /query-by-status/{status}`; `GET /query-by-transport-type/{transportType}`; `GET /query-enabled`; `POST /query-list` | MCP CRUD | 3, 4 |
| `/api/v1/admin/admin-user` | `POST /create`; `PUT /update-by-id`; `PUT /update-by-user-id`; `DELETE /delete-by-id/{id}`; `DELETE /delete-by-user-id/{userId}`; `GET /query-by-id/{id}`; `GET /query-by-user-id/{userId}`; `GET /query-by-username/{username}`; `GET /query-enabled`; `GET /query-by-status/{status}`; `POST /query-list`; `GET /query-all`; `POST /login`; `POST /validate-login` | admin identity | 3, 4 |
| `/api/v1/admin/skills` | `GET /list`; `POST /parse-package`; `POST /upload`; `POST /create`; `POST /import-url`; `DELETE /{name}`; `POST /reload` | filesystem/skill registry | 6 |
| `/api/v1/admin/sub-agent-definitions` | `GET /query-list`; `GET /tool-catalog`; `GET /{agentKey}`; `POST /create`; `PUT /update`; `DELETE /{agentKey}`; `DELETE /delete`; `POST /reload` | sub-agent config | 8 |
| `/data` | `POST /queryModelInfo`; `POST /vectorRecall`; `POST /esRecall`; `POST /chatQuery`; `POST /apiChatQuery`; `POST /testQuery`; `POST /getNl2SqlReq`; `GET /allModels`; `GET /previewData` | Data Agent | 8 |

`AiClientModel` connection-test routes are not read-only even though they do not write MySQL; they make external model calls and stay in phase 4.

## SSE surface and lifecycle

| Route | Producer | Consumer expectations |
|---|---|---|
| `/web/health` | `AiAgentController` | `text/event-stream` health response |
| `/web/api/v1/gpt/queryAgentStreamIncr` | main agent dispatch | POST SSE; no automatic retry; visitor cookie; event IDs are persisted client-side |
| `/api/agent/run/follow` | attach/replay live run | heartbeat plus resumable event stream |
| `/api/agent/ask-user/resume` | HITL resume | resumes yielded run and streams subsequent frames |
| `/api/agent/plan-approval/resume` | plan resume | resumes yielded run and streams subsequent frames |
| `/data/chatQuery` | Data Agent | `THINK`, `CHART_DATA`, `ERROR`, `READY` payloads |

The main stream JSON envelope requires `status`, `packageType`, `finished`, optional `errorMsg`, and `resultMap`. When `resultMap.eventData` exists, the UI requires `messageOrder`, `messageType`, `messageId`, `taskId`, `taskOrder`, and nested `resultMap`. Unknown fields are intentionally retained by the frontend.

## Runtime capabilities

- Agent execution: ReAct and Plan-Solve strategies, prompt shaping, model selection/fallback, usage capture, maximum-turn handling and final-answer projection.
- Tools: workspace file operations, shell/code execution, code interpreter, data analysis, deep search, image generation, OCR, document/slides/spreadsheet generation and reading, Canvas/GenUI, social/search tools and task-list tools.
- Skill runtime: directory discovery, Markdown parsing, package import/materialization, per-session workspace execution, bounded bash timeout and path guards.
- MCP: configuration-backed servers, deferred discovery, resource listing/reading, tool-name normalization and execution.
- Human-in-the-loop: Ask User and Plan Approval use persisted records plus CAS state transitions, in-memory pending registries and resume streams.
- Sub-agents: definition registry, context isolation, foreground/background dispatch, concurrency gate, mailbox/progress and parent cancellation.
- Memory: working-memory turns/messages, compaction audit, curated LTM, LTM fork execution and optional session memory.
- Ledger/replay: dialogue sessions/runs, LLM/tool invocation ledgers, typed tool-output tables, artifacts and replay projectors.
- Run control: active-run registry, stop cancellation, injected messages, follow/reattach and SSE heartbeat.
- Background work: session todo list, persistent background-task records and in-memory registries; Data Agent startup initialization is a `CommandLineRunner`.

## External systems

| System | Use |
|---|---|
| OpenAI-compatible chat/image endpoints | main LLM, compaction/LTM extraction, image generation, web-search variants |
| `reactor-tool` / `reactor-sandbox` | code interpreter, deep search, multimodal, data analysis, file/artifact service and sandboxed skill execution |
| MCP servers | dynamically configured tools and resources |
| MySQL 8.4 | application configuration, identity, ledgers, memory and task state |
| Elasticsearch 7 | Data Agent schema/value recall |
| Qdrant | vector recall |
| ClickHouse and arbitrary JDBC sources | Data Agent query execution |
| Exa and configured search providers | web search |

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
- Observability: Spring Actuator exposes health, info, metrics and Prometheus.
