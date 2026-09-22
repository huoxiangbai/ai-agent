# Public API and SSE compatibility contract

Last updated: 2026-09-22

## Global HTTP contract

- Public paths and HTTP methods remain unchanged during migration.
- **HTTP methods are exactly those in `inventory.md`, except the two `/web` handlers.** `ANY /web/health` and `ANY /web/api/v1/gpt/queryAgentStreamIncr` use `@RequestMapping` with no `method` attribute and accept GET/POST/PUT/DELETE/PATCH/HEAD. The UI only issues POST for the stream, but the server does not enforce it — a Python route registered POST-only would diverge on 405.
- JSON business responses normally use `{"code": string, "info": string, "data": any}`.
- Protocol codes are `0000` success, `0001` unknown/business failure, `0002` invalid parameter and `0003` login failure.
- Existing controllers often return HTTP 200 even when the envelope reports a business error. Python must match each endpoint's recorded status rather than impose a new global HTTP error policy. Java has **no** `@ControllerAdvice`, `@ExceptionHandler` or `ErrorController`; error shaping is per-handler try/catch into the envelope.
- Pagination payloads use `{"total": number, "list": array}`.
- Axios unwraps `data` only for `code === "0000"` (and a legacy numeric `200`). Changing the envelope breaks the UI.
- Multipart uploads must allow the browser to supply the boundary. Binary ZIP/PDF/DOCX downloads are not wrapped in JSON.
- Timestamps, null handling, sort order and empty-list behavior are endpoint contract data, not implementation details.
- CORS is served by a global `CorsFilter` (`allowedHeaders=*`, `allowedMethods=*`; credentials + explicit origins only when `visitorCookie.allowedOrigins` is set). Six controllers also carry class-level `@CrossOrigin(origins="*)`; `FeaturedConversationAdmin` and `SubAgentDefinitionAdmin` do not. Preserve the inconsistency rather than normalizing it.
- FastAPI defaults must not leak in: no automatic 307 redirect slashes, no 422 body replacing a Java-shaped `0002` envelope unless the recorded golden shows it.

### Python-side envelope mapping (coexistence backend)

The Python exception handlers currently map: `ApiError` → HTTP 200 + code `0001`; request validation → HTTP 422 + code `0002`; unhandled exception → HTTP 500 + code `0001` and message `未知失败`. Per-endpoint goldens take precedence over this default.

## Visitor identity contract

- Cookie-protected path prefixes (from `VisitorIdentityFilter`): `/web/api/v1/gpt/queryAgentStreamIncr`, `/1/web/api/v1/gpt/queryAgentStreamIncr`, `/api/agent/visitor`, `/api/agent/conversation/sessions`, `/api/agent/file`, `/api/agent/workspace`, `/api/agent/run`, `/api/agent/ask-user`, `/api/agent/plan-approval`.
- **Not** cookie-protected: `/api/agent/session/*`, `/api/agent/featured-conversations/*`, `/api/agent/image-generation/*`, `/api/agent/genui/*`, `/api/v1/admin/*`, `/data/*`, `/web/health`.
- `/1/web/api/v1/gpt/queryAgentStreamIncr` is a **legacy alias matched by the filter but mapped by no controller** — it can issue `Set-Cookie` and then 404. Recorded, not deleted.
- Cookie name: `ai_agent_visitor_token`.
- Defaults: HttpOnly, path `/`, max age 365 days, SameSite `Lax`; Secure is environment-controlled.
- A missing or stale cookie causes identity resolution/creation and a new `Set-Cookie` header.
- Client IP uses the first `X-Forwarded-For` value, falling back to the direct peer. User-Agent is recorded.
- Request-scoped visitor identity must be cleared after each request/task to prevent cross-request leakage.
- Filter-protected GETs are therefore **not pure reads**: they write `ai_agent_visitor_identity` (resolve/create/refresh). They cannot cut over before a single writer owns those operations.

## Frontend-strong response fields

### Visitor

`visitorId`, optional `username`, `named`.

### Conversation session list

`sessionId`, `title`, `status`, `latestQueryText`, `runCount`, `finishedRunCount`, `failedRunCount`, `startedAt`, `lastActiveAt`.

### Conversation detail

Top level: `sessionId`, `title`, `status`, `deepThink`, run counters, optional timestamps and `runs`.

Each run: `requestId`, `status`, `queryText`, optional `finalSummaryText`, timestamps, optional `contextUsage`, and `replayFrames`.

Each replay frame: `reqId`, `status`, `finished`, `resultMap.agentType`, optional `resultMap.multiAgent` and optional `resultMap.eventData`.

### Featured conversations

- Card: `featuredId`, `sessionId`, `title`, `summary`, optional `coverUrl`, `tags`, optional `publishedAt`, optional `contentLastActiveAt`.
- Detail adds optional `status`, `contentAvailable`, optional `contentUnavailableReason`, and nullable `historyDetail`.
- List uses the standard `total/list` pagination object.

### Session capabilities

- Top level: `locked`, `skills`, `mcpServers`.
- Capability item: `refId`, `name`, `enabled`, optional `source`.
- Update request: `kind` (`skill` or `mcp`), `refId`, `enabled`.

## Main SSE contract

- Transport is POST `text/event-stream`, credentials included, JSON request body and UTF-8 data frames.
- The client does not automatically retry the original POST. Recovery uses run state plus `/api/agent/run/follow`.
- A frame with an SSE `id` updates the client's resume cursor.
- Top-level JSON requires:
  - `status: string`
  - `packageType: string`
  - `finished: boolean`
  - `errorMsg?: string | null`
  - `resultMap?: object`
- `resultMap.eventData`, when present, requires:
  - `messageOrder: number`
  - `messageType: string`
  - `messageId: string`
  - `taskId: string`
  - `taskOrder: number`
  - `resultMap: object` with optional nested `messageType`
- Ordering keys and identifiers are stable merge keys. Python must not regenerate them while replaying or following a run.
- Important message families include reasoning, plan, task, tool-call deltas/final calls, tool results, files/artifacts, UI tree/patch, deep-search stages, context usage, LLM retry, sub-agent progress, `ask_user_question` and `plan_approval`.
- Unknown fields must be preserved. Compatibility tests compare required structure and known values while allowing additive fields.
- Terminal behavior distinguishes completed, stopped, failed and waiting-for-input states. A socket close by itself is not a successful terminal event.

## Data Agent SSE contract

`/data/chatQuery` emits JSON with a discriminated `eventType`. The enum defines five values:

- `THINK`: string `data`
- `CHART_DATA`: array-of-object `data`
- `ERROR`: string `data`
- `READY`: optional `data`
- `DEBUG`: debug information

The producer also accepts free-form event-type strings (`ChatDataMessage.ofStatus`), so a consumer must tolerate unknown `eventType` values instead of rejecting the frame. Comparators must treat unknown event types as additive fields unless a case pins them.

## Contract-test design

- Base URLs come from `JAVA_BASE_URL` and `PYTHON_BASE_URL`.
- Each case defines method, path, headers, body, expected content type and an endpoint-specific normalization allowlist.
- HTTP comparison covers status, content type, selected headers, cookie attributes, complete JSON shape, value types, nulls and ordering where meaningful.
- SSE comparison parses `id`, `event`, `retry` and multi-line `data`, then compares ordered normalized frames and terminal outcome.
- Non-deterministic values may only be removed by JSON path named in that case (for example generated IDs or timestamps). Unknown extra/missing fields remain diffs.
- Golden fixtures never contain secrets, raw visitor cookies, full user prompts or paid-provider responses.
- Initial cases cover visitor bootstrap, conversation list/detail, featured home/list/detail and capability GET. Python placeholders may return explicit `501` but may not fake successful business data.
- Every route must be either **covered** by a case or listed in the deferred registry below. Silence is not coverage.

## Deferred registry (explicitly not covered yet)

Phase-2 exit requires "every route covered or explicitly deferred". Today 7 of 108 method routes have cases; the rest are recorded here so coverage is never overstated. `Owner phase` is when the deferred item becomes blocking.

| Deferred group | Routes | Why deferred | Owner phase |
|---|---|---|---|
| Naming / visitor write | `POST /api/agent/visitor/naming` | identity write; needs single-writer first | 4 |
| Capability write | `PUT /api/agent/session/{sessionId}/capabilities` | write route; cloned-DB parity needed | 4 |
| Admin featured CRUD | `POST|PUT|POST` × 5 on `/api/v1/admin/featured-conversations` | write domain + cache/registry effects | 4 |
| Admin AI-client API CRUD | 10 routes on `/api/v1/admin/ai-client-api` | write domain, generated keys | 4 |
| Admin AI-client model CRUD + `/test*` | 14 routes on `/api/v1/admin/ai-client-model` | write domain; `/test*` is **live/manual only** | 4 |
| Admin MCP CRUD | 12 routes on `/api/v1/admin/ai-client-tool-mcp` | write domain + registry reload | 4 |
| Admin user CRUD + login | 14 routes on `/api/v1/admin/admin-user` | write domain + login semantics (`0003`) | 4 |
| File upload | `POST /api/agent/file/upload` | multipart + boundary + checksum | 6 |
| Workspace archive | `GET /api/agent/workspace/{sessionId}/archive` | streaming ZIP, `Content-Disposition`, Zip Slip | 6 |
| Image generation | `POST /api/agent/image-generation/generate`, `GET .../history` | batch atomicity + pagination | 6 |
| GenUI export | `POST /api/agent/genui/export/pdf`, `POST .../docx` | binary headers + checksum | 6 |
| Skills admin | 7 routes on `/api/v1/admin/skills` | multipart + filesystem/registry side effects | 6 |
| Run control | `POST /api/agent/run/stop`, `/inject`, `/follow` | SSE/run lifecycle; atomic family | 5 |
| Ask User | 4 routes on `/api/agent/ask-user` | CAS + in-memory registry + resume SSE | 8 |
| Plan Approval | 5 routes on `/api/agent/plan-approval` | CAS + in-memory registry + resume SSE | 8 |
| Sub-agent admin | 8 routes on `/api/v1/admin/sub-agent-definitions` | registry reload | 8 |
| Data Agent | 8 routes on `/data` (all except `chatQuery` SSE shape) | ES7/Qdrant/ClickHouse fixtures + SQL safety | 8 |
| Main agent stream | `ANY /web/api/v1/gpt/queryAgentStreamIncr` | full SSE corpus (order, ids, heartbeat, terminal states) | 5/7 |
| Health probe | `ANY /web/health` | plain body; covered by live/ready probe tests rather than HTTP contract | 0/1 |
| Frontend-only phantom | `/web/api/login`, `/web/api/getWhiteList`, `/web/api/reactor/apply` | **no Java implementation exists**; pending determination | open |

Multipart, binary export and the SSE corpus have no comparison capability yet. They are deferred rather than reported as covered.
