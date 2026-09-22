# Public API and SSE compatibility contract

Last updated: 2026-09-18

## Global HTTP contract

- Public paths and HTTP methods remain unchanged during migration.
- JSON business responses normally use `{"code": string, "info": string, "data": any}`.
- Protocol codes are `0000` success, `0001` unknown/business failure, `0002` invalid parameter and `0003` login failure.
- Existing controllers often return HTTP 200 even when the envelope reports a business error. Python must match each endpoint's recorded status rather than impose a new global HTTP error policy.
- Pagination payloads use `{"total": number, "list": array}`.
- Axios unwraps `data` only for `code === "0000"` (and a legacy numeric `200`). Changing the envelope breaks the UI.
- Multipart uploads must allow the browser to supply the boundary. Binary ZIP/PDF/DOCX downloads are not wrapped in JSON.
- Timestamps, null handling, sort order and empty-list behavior are endpoint contract data, not implementation details.

## Visitor identity contract

- Protected paths include the main agent stream, visitor/history/file/workspace/run, Ask User and Plan Approval routes.
- Cookie name: `ai_agent_visitor_token`.
- Defaults: HttpOnly, path `/`, max age 365 days, SameSite `Lax`; Secure is environment-controlled.
- A missing or stale cookie causes identity resolution/creation and a new `Set-Cookie` header.
- Client IP uses the first `X-Forwarded-For` value, falling back to the direct peer. User-Agent is recorded.
- Request-scoped visitor identity must be cleared after each request/task to prevent cross-request leakage.

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

`/data/chatQuery` emits JSON with a discriminated `eventType`:

- `THINK`: string `data`
- `CHART_DATA`: array-of-object `data`
- `ERROR`: string `data`
- `READY`: optional `data`

## Contract-test design

- Base URLs come from `JAVA_BASE_URL` and `PYTHON_BASE_URL`.
- Each case defines method, path, headers, body, expected content type and an endpoint-specific normalization allowlist.
- HTTP comparison covers status, content type, selected headers, cookie attributes, complete JSON shape, value types, nulls and ordering where meaningful.
- SSE comparison parses `id`, `event`, `retry` and multi-line `data`, then compares ordered normalized frames and terminal outcome.
- Non-deterministic values may only be removed by JSON path named in that case (for example generated IDs or timestamps). Unknown extra/missing fields remain diffs.
- Golden fixtures never contain secrets, raw visitor cookies, full user prompts or paid-provider responses.
- Initial cases cover visitor bootstrap, conversation list/detail, featured home/list/detail and capability GET. Python placeholders may return explicit `501` but may not fake successful business data.
