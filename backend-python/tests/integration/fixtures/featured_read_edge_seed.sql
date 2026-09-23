-- Edge-case rows for the featured public-read repository integration tests.
--
-- Applies only to the dedicated throwaway test database (same rule as
-- tests/contract/fixtures/contract-seed.sql). Fixed keys are deleted first so
-- the file is idempotent. All timestamps are fixed literals in Asia/Shanghai.
--
-- Covered edges:
--   * OFFLINE / deleted featured rows are excluded from list+home but reachable
--     by queryByFeaturedId (no status filter) for the detail gate to reject
--   * malformed tags_json (scalar / object / broken) → parse_tags fallbacks
--   * millisecond timestamps (`.123`) round-trip through Jackson formatting
--   * a plan_solve run (deepThink last-run-wins) and a 0-llm run
--   * internal/subagent llm invocations skipped by the projector
--   * code_interpreter tool + output + output artifact (tool frame family)

SET NAMES utf8mb4;
SET time_zone = '+08:00';

-- Replay chain children for the edge run.
DELETE FROM ai_agent_tool_output_code_interpreter
WHERE request_id = 'edge-run-ci' OR run_id = 401;
DELETE FROM ai_agent_artifact
WHERE request_id IN ('edge-run-ci', 'edge-run-plan', 'edge-run-empty') OR run_id IN (401, 402, 403);
DELETE FROM ai_agent_tool_invocation WHERE run_id IN (401, 402, 403);
DELETE FROM ai_agent_llm_invocation WHERE run_id IN (401, 402, 403);
DELETE FROM ai_agent_dialogue_run
WHERE request_id IN ('edge-run-ci', 'edge-run-plan', 'edge-run-empty')
   OR id IN (401, 402, 403);
DELETE FROM ai_agent_dialogue_session
WHERE session_id IN (
    'edge-session-tags', 'edge-session-millis', 'edge-session-deep',
    'edge-session-offline', 'edge-session-deleted', 'edge-session-empty'
);
DELETE FROM ai_agent_featured_conversation
WHERE featured_id IN (
    'edge-featured-tags', 'edge-featured-millis', 'edge-featured-offline',
    'edge-featured-deleted', 'edge-featured-deep', 'edge-featured-empty-history'
);

-- Sessions. featured_conversation.session_id is UNIQUE, so each featured row
-- needs its own session even when the row is only used for a rejection case.
INSERT INTO ai_agent_dialogue_session (
    id, session_id, visitor_id, title, status,
    latest_request_id, latest_query_text, latest_summary_text,
    run_count, finished_run_count, failed_run_count,
    started_at, last_active_at, create_time, update_time, deleted
) VALUES
    (31, 'edge-session-tags', 'fixture-visitor-0001', 'Edge tags session', 1,
     NULL, 'edge tags query', NULL, 0, 0, 0,
     '2026-01-05 09:00:00.000', '2026-01-05 09:10:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:10:00', 0),
    (32, 'edge-session-millis', 'fixture-visitor-0001', '新对话', 1,
     'edge-run-plan', 'plan the thing', NULL, 2, 1, 0,
     '2026-01-05 10:00:00.123', '2026-01-05 10:30:00.456',
     '2026-01-05 10:00:00', '2026-01-05 10:30:00', 0),
    (33, 'edge-session-deep', 'fixture-visitor-0001', 'Edge deep session', 1,
     'edge-run-ci', 'run code', NULL, 1, 1, 0,
     '2026-01-05 11:00:00.000', '2026-01-05 11:30:00.000',
     '2026-01-05 11:00:00', '2026-01-05 11:30:00', 0),
    (34, 'edge-session-offline', 'fixture-visitor-0001', 'Edge offline session', 1,
     NULL, 'offline query', NULL, 0, 0, 0,
     '2026-01-05 09:00:00.000', '2026-01-05 09:10:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:10:00', 0),
    (35, 'edge-session-deleted', 'fixture-visitor-0001', 'Edge deleted session', 1,
     NULL, 'deleted query', NULL, 0, 0, 0,
     '2026-01-05 09:00:00.000', '2026-01-05 09:10:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:10:00', 0),
    (36, 'edge-session-empty', 'fixture-visitor-0001', 'Edge empty session', 1,
     NULL, 'empty query', NULL, 0, 0, 0,
     '2026-01-05 09:00:00.000', '2026-01-05 09:20:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:20:00', 0);

-- Featured rows. sort_order 500 is above the contract fixture's 100 so the
-- edge rows surface first in ORDER BY sort_order DESC, id DESC.
INSERT INTO ai_agent_featured_conversation (
    id, featured_id, session_id, title, summary,
    cover_resource_key, cover_url, tags_json,
    sort_order, status, published_by, published_at, updated_by, updated_at,
    create_time, update_time, deleted
) VALUES
    (31, 'edge-featured-tags', 'edge-session-tags', 'Edge tags', 'Malformed tags',
     NULL, NULL, '{"not":"an array"}',
     500, 'ONLINE', 'edge', '2026-01-05 09:00:00.123', 'edge', '2026-01-05 09:00:00.123',
     '2026-01-05 09:00:00', '2026-01-05 09:00:00', 0),
    (32, 'edge-featured-millis', 'edge-session-millis', 'Edge millis', 'Millis times',
     NULL, NULL, '[1, true, null]',
     400, 'online', 'edge', '2026-01-05 10:00:00.456', 'edge', '2026-01-05 10:00:00.456',
     '2026-01-05 10:00:00', '2026-01-05 10:00:00', 0),
    (33, 'edge-featured-offline', 'edge-session-offline', 'Edge offline', 'Not online',
     NULL, NULL, '[]',
     300, 'OFFLINE', 'edge', '2026-01-05 09:00:00.000', 'edge', '2026-01-05 09:00:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:00:00', 0),
    (34, 'edge-featured-deleted', 'edge-session-deleted', 'Edge deleted', 'Soft deleted',
     NULL, NULL, '[]',
     250, 'ONLINE', 'edge', '2026-01-05 09:00:00.000', 'edge', '2026-01-05 09:00:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:00:00', 1),
    (35, 'edge-featured-deep', 'edge-session-deep', 'Edge deep', 'Tool frames',
     NULL, NULL, '[]',
     200, 'ONLINE', 'edge', '2026-01-05 11:00:00.000', 'edge', '2026-01-05 11:00:00.000',
     '2026-01-05 11:00:00', '2026-01-05 11:00:00', 0),
    (36, 'edge-featured-empty-history', 'edge-session-empty', 'Edge empty history',
     'Zero runs', NULL, NULL, '[]',
     150, 'ONLINE', 'edge', '2026-01-05 09:00:00.000', 'edge', '2026-01-05 09:00:00.000',
     '2026-01-05 09:00:00', '2026-01-05 09:00:00', 0);

-- Runs: plan_solve (deepThink true), a 0-llm run on the same session (last-run-wins
-- keeps deepThink true only if this one is NOT plan_solve/react — it is `other`),
-- and a code-interpreter run.
INSERT INTO ai_agent_dialogue_run (
    id, run_uid, request_id, session_id, visitor_id, entry_agent, status,
    query_text, final_summary_text,
    llm_call_count, tool_call_count, artifact_count,
    prompt_tokens_total, completion_tokens_total, total_tokens_total,
    error_code, error_msg, started_at, finished_at, duration_ms,
    create_time, update_time, deleted
) VALUES
    (401, 'edge-run-ci', 'edge-run-ci', 'edge-session-deep',
     'fixture-visitor-0001', 'react', 1,
     'run code', 'code summary',
     1, 1, 1,
     0, 0, 0,
     NULL, NULL, '2026-01-05 11:00:00.000', '2026-01-05 11:00:05.000', 5000,
     '2026-01-05 11:00:00', '2026-01-05 11:00:05', 0),
    (402, 'edge-run-plan', 'edge-run-plan', 'edge-session-millis',
     'fixture-visitor-0001', 'plan_solve', 1,
     'plan the thing', 'plan summary',
     1, 0, 0,
     10, 5, 15,
     NULL, NULL, '2026-01-05 10:00:00.123', '2026-01-05 10:00:01.456', 1333,
     '2026-01-05 10:00:00', '2026-01-05 10:00:01', 0),
    (403, 'edge-run-empty', 'edge-run-empty', 'edge-session-millis',
     'fixture-visitor-0001', 'other', 0,
     'no llm here', NULL,
     0, 0, 0,
     0, 0, 0,
     NULL, NULL, '2026-01-05 10:20:00.000', '2026-01-05 10:20:01.000', 1000,
     '2026-01-05 10:20:00', '2026-01-05 10:20:01', 0);

-- LLM invocations: a normal one, plus internal/subagent ones the projector skips.
INSERT INTO ai_agent_llm_invocation (
    id, run_id, invocation_seq, agent_name, step_no, call_kind, streaming,
    model_name, response_text, reasoning_content, tool_call_count,
    prompt_tokens, completion_tokens, total_tokens,
    est_total_tokens, est_system_tokens, est_message_tokens, est_tool_tokens,
    status, started_at, finished_at, duration_ms,
    create_time, update_time, deleted
) VALUES
    (401, 401, 1, 'react', 1, 'ask', 0,
     'fixture-model', 'thinking about code', NULL, 1,
     0, 0, 0,
     40, 10, 20, 10,
     1, '2026-01-05 11:00:01.000', '2026-01-05 11:00:02.000', 1000,
     '2026-01-05 11:00:01', '2026-01-05 11:00:02', 0),
    (402, 402, 1, 'plan_solve', 1, 'ask', 0,
     'fixture-model', 'planning text', NULL, 0,
     7, 3, 10,
     NULL, NULL, NULL, NULL,
     1, '2026-01-05 10:00:00.200', '2026-01-05 10:00:01.300', 1100,
     '2026-01-05 10:00:00', '2026-01-05 10:00:01', 0),
    (403, 401, 2, 'react', 2, 'internalCompact', 0,
     'fixture-model', 'must not appear', NULL, 0,
     0, 0, 0,
     NULL, NULL, NULL, NULL,
     1, '2026-01-05 11:00:02.000', '2026-01-05 11:00:03.000', 1000,
     '2026-01-05 11:00:02', '2026-01-05 11:00:03', 0),
    (404, 401, 3, 'subagent:help', 3, 'ask', 0,
     'fixture-model', 'subagent must not appear', NULL, 0,
     0, 0, 0,
     NULL, NULL, NULL, NULL,
     1, '2026-01-05 11:00:03.000', '2026-01-05 11:00:04.000', 1000,
     '2026-01-05 11:00:03', '2026-01-05 11:00:04', 0);

-- code_interpreter tool + rich output + one output artifact.
-- Column is llm_oberserve (schema typo) and request_id lives on the run row.
INSERT INTO ai_agent_tool_invocation (
    id, run_id, llm_invocation_id, tool_call_id, parent_tool_call_id,
    tool_name, tool_provider, agent_name,
    sub_agent_id, sub_agent_type, sub_agent_description,
    dispatch_index, input_json, llm_oberserve, error_msg, status,
    started_at, finished_at,
    create_time, update_time, deleted
) VALUES (
    401, 401, 401, 'call-ci-0001', NULL,
    'code_interpreter', 'local', 'react',
    NULL, NULL, NULL,
    0, '{"code":"print(1)"}', 'observation fallback', NULL, 1,
    '2026-01-05 11:00:01.500', '2026-01-05 11:00:02.500',
    '2026-01-05 11:00:01', '2026-01-05 11:00:02', 0
);

INSERT INTO ai_agent_tool_output_code_interpreter (
    tool_invocation_id, run_id, request_id, session_id, tool_call_id,
    status, error_msg, code_output, content, code, `explain`,
    created_at, updated_at
) VALUES (
    401, 401, 'edge-run-ci', 'edge-session-deep', 'call-ci-0001',
    1, NULL, 'printed 1', 'side content', 'print(1)', 'prints one',
    '2026-01-05 11:00:02', '2026-01-05 11:00:02'
);

INSERT INTO ai_agent_artifact (
    id, run_id, tool_invocation_id, request_id, tool_call_id,
    artifact_role, visibility, source_type, storage_key,
    file_name, mime_type, file_size, preview_url, download_url, metadata_json,
    create_time, update_time, deleted
) VALUES (
    401, 401, 401, 'edge-run-ci', 'call-ci-0001',
    'output', 'visible', 'code_interpreter', 'edge-key-0001',
    'result.txt', 'text/plain', 12, NULL, '/download/edge-key-0001',
    '{"relativePath":"out/result.txt"}',
    '2026-01-05 11:00:02', '2026-01-05 11:00:02', 0
);
