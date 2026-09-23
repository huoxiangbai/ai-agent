-- Deterministic seed for the Java/Python contract lab.
--
-- Applies only to the dedicated throwaway test database. Never run this against
-- a shared or production database: it deletes and re-inserts fixture rows by
-- fixed keys and empties ai_client_tool_mcp.
--
-- Fixed identities (see tests/contract/README.md):
--   CONTRACT_VISITOR_TOKEN = fixture-raw-token
--   token_digest           = SHA-256("fixture-raw-token") hex
--     recompute: python3 -c "import hashlib;print(hashlib.sha256(b'fixture-raw-token').hexdigest())"
--   visitor_id             = fixture-visitor-0001
--   CONTRACT_SESSION_ID    = fixture-session
--   CONTRACT_FEATURED_ID   = fixture-featured
--
-- Ordering columns are pinned so every ORDER BY in the seven initial cases is
-- deterministic: featured (sort_order DESC, id DESC), session list
-- (last_active_at DESC, id DESC), runs (create_time ASC, id ASC), llm
-- invocations (invocation_seq ASC, id ASC), tool invocations
-- (llm_invocation_id ASC, dispatch_index ASC, id ASC), artifacts
-- (create_time ASC, id ASC). All timestamps are fixed literals in Asia/Shanghai.

SET NAMES utf8mb4;
SET time_zone = '+08:00';

-- ai_client_tool_mcp: emptied on purpose so session-capabilities returns
-- mcpServers: []. Discover failures are swallowed by SessionCapabilityService.
DELETE FROM ai_client_tool_mcp;

-- Replay chain children: kept empty so the empty-collection shape is itself
-- part of the contract.
DELETE FROM ai_agent_tool_output_deep_search
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_code_interpreter
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_data_analysis
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_multimodal_agent
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_image_generation
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_canvas_publish
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_emit_ui_tree
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_output_emit_ui_patch
WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_artifact WHERE request_id = 'fixture-run-0001' OR run_id = 101;
DELETE FROM ai_agent_tool_invocation WHERE run_id = 101;

-- No session_capability overrides: every discovered skill stays enabled=true.
DELETE FROM ai_agent_session_capability
WHERE session_id IN ('fixture-session', 'fixture-session-2');

DELETE FROM ai_agent_llm_invocation WHERE run_id = 101;
DELETE FROM ai_agent_dialogue_run
WHERE request_id = 'fixture-run-0001' OR run_uid = 'fixture-run-0001' OR id = 101;
DELETE FROM ai_agent_dialogue_session
WHERE session_id IN ('fixture-session', 'fixture-session-2');
DELETE FROM ai_agent_featured_conversation
WHERE featured_id IN ('fixture-featured', 'fixture-featured-2');
DELETE FROM ai_agent_visitor_identity
WHERE visitor_id = 'fixture-visitor-0001'
   OR token_digest = 'a8f53b12900598e36fd242c58f5a08df8d4f10a71b9ff169ad29f5f4df0d4501';

-- Pre-seeded visitor so filter-protected GETs resolve (newlyCreated=false) and
-- do not emit Set-Cookie. Without this row those cases would mint a random
-- visitor and the session list would come back empty.
INSERT INTO ai_agent_visitor_identity (
    id, visitor_id, token_digest, status,
    first_seen_at, last_seen_at, last_ip, last_user_agent, username,
    create_time, update_time, deleted
) VALUES (
    1, 'fixture-visitor-0001',
    'a8f53b12900598e36fd242c58f5a08df8d4f10a71b9ff169ad29f5f4df0d4501',
    1,
    '2026-01-01 09:00:00.000', '2026-01-01 09:00:00.000',
    '127.0.0.1', 'contract-fixture', NULL,
    '2026-01-01 09:00:00', '2026-01-01 09:00:00', 0
);

-- Two sessions for the same visitor: distinct last_active_at pins
-- ORDER BY last_active_at DESC, id DESC (session 1 lists first).
INSERT INTO ai_agent_dialogue_session (
    id, session_id, visitor_id, title, status,
    latest_request_id, latest_query_text, latest_summary_text,
    run_count, finished_run_count, failed_run_count,
    started_at, last_active_at, create_time, update_time, deleted
) VALUES
    (1, 'fixture-session', 'fixture-visitor-0001', 'Fixture session one', 1,
     'fixture-run-0001', 'fixture query text', 'fixture summary text',
     1, 1, 0,
     '2026-01-01 09:00:00.000', '2026-01-03 09:00:00.000',
     '2026-01-01 09:00:00', '2026-01-03 09:00:00', 0),
    (2, 'fixture-session-2', 'fixture-visitor-0001', 'Fixture session two', 1,
     NULL, 'second fixture query text', NULL,
     0, 0, 0,
     '2026-01-01 08:00:00.000', '2026-01-03 08:00:00.000',
     '2026-01-01 08:00:00', '2026-01-03 08:00:00', 0);

-- Two ONLINE featured rows: sort_order 100/50 pins ORDER BY sort_order DESC,
-- id DESC and gives queryPublicList a total of 2 to page over.
INSERT INTO ai_agent_featured_conversation (
    id, featured_id, session_id, title, summary,
    cover_resource_key, cover_url, tags_json,
    sort_order, status, published_by, published_at, updated_by, updated_at,
    create_time, update_time, deleted
) VALUES
    (1, 'fixture-featured', 'fixture-session',
     'Fixture featured conversation',
     'Deterministic contract fixture summary.',
     NULL, NULL, '["fixture","contract"]',
     100, 'ONLINE', 'contract-fixture', '2026-01-02 10:00:00.000',
     'contract-fixture', '2026-01-02 10:00:00.000',
     '2026-01-02 10:00:00', '2026-01-02 10:00:00', 0),
    (2, 'fixture-featured-2', 'fixture-session-2',
     'Fixture featured conversation two',
     'Second deterministic contract fixture summary.',
     NULL, NULL, '["fixture"]',
     50, 'ONLINE', 'contract-fixture', '2026-01-02 11:00:00.000',
     'contract-fixture', '2026-01-02 11:00:00.000',
     '2026-01-02 11:00:00', '2026-01-02 11:00:00', 0);

-- One finished run on fixture-session so ReplayProjector really executes and
-- historyDetail/runs is non-empty. visitor_id must be non-null and match the
-- cookie visitor, otherwise case 6 records the 0001 permission envelope.
INSERT INTO ai_agent_dialogue_run (
    id, run_uid, request_id, session_id, visitor_id, entry_agent, status,
    query_text, final_summary_text,
    llm_call_count, tool_call_count, artifact_count,
    prompt_tokens_total, completion_tokens_total, total_tokens_total,
    error_code, error_msg, started_at, finished_at, duration_ms,
    create_time, update_time, deleted
) VALUES (
    101, 'fixture-run-0001', 'fixture-run-0001', 'fixture-session',
    'fixture-visitor-0001', 'react', 1,
    'fixture query text', 'fixture summary text',
    1, 0, 0,
    100, 50, 150,
    NULL, NULL, '2026-01-01 09:00:00.000', '2026-01-01 09:00:05.000', 5000,
    '2026-01-01 09:00:00', '2026-01-01 09:00:05', 0
);

-- One LLM invocation drives contextUsage and at least one replay frame.
INSERT INTO ai_agent_llm_invocation (
    id, run_id, invocation_seq, agent_name, step_no, call_kind, streaming,
    model_name, response_text, reasoning_content, tool_call_count,
    prompt_tokens, completion_tokens, total_tokens,
    status, started_at, finished_at, duration_ms,
    create_time, update_time, deleted
) VALUES (
    201, 101, 1, 'react', 1, 'ask', 0,
    'fixture-model', 'fixture response text', NULL, 0,
    100, 50, 150,
    1, '2026-01-01 09:00:01.000', '2026-01-01 09:00:02.000', 1000,
    '2026-01-01 09:00:01', '2026-01-01 09:00:02', 0
);
