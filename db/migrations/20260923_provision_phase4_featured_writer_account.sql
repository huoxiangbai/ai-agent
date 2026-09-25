-- Provision the phase-4 per-writer database account for the featured-admin slice.
--
-- Why this exists (risk-register.md R-22, extended): phase 3 enforced "Python must
-- not write" with `reactor_py_ro`. Phase 4 has to let Python write exactly one
-- table while still forbidding every other write, so that a Python bug, a stray
-- migration, or the next slice landing early cannot touch anything else. This is
-- layer 1 of the two-layer writer fence for `ai_agent_featured_conversation`;
-- layer 2 is `REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER` (fail-closed, defaults to
-- `java`).
--
-- Scope, deliberately narrow:
--   SELECT              ON `<db>`.*                                  (reads only:
--                       create() checks `ai_agent_dialogue_session`; upsert/update
--                       re-read `ai_agent_featured_conversation` first)
--   INSERT, UPDATE      ON `<db>`.ai_agent_featured_conversation      (the writer)
--
-- There is NO DELETE grant, on purpose. Every "delete" in this domain is the
-- soft-delete `deleted = 0` update inside `upsert` / `updateStatus`, so a real
-- DELETE can only ever be a bug and must fail at the account layer with ERROR 1142.
-- There is no DDL grant: the schema is frozen for this migration stage (no Alembic).
--
-- Idempotent: re-running is safe. This file only ever GRANTs; it never REVOKEs,
-- so re-applying it cannot widen or narrow an existing grant by accident.
--
-- ---------------------------------------------------------------------------
-- The password is NOT in this file. Set it before running, or the run aborts:
--
--   SET @reactor_py_featured_writer_password := '<from your secret store>';
--   SET @reactor_py_featured_writer_database := 'ai-agent-station';   -- optional
--   SOURCE db/migrations/20260923_provision_phase4_featured_writer_account.sql;
--
-- Never pass the password on the mysql command line: it would land in shell
-- history and the process list. Use an interactive SET, a client option file
-- outside the repository, or a secrets store that injects the session variable.
--
-- Password policy (enforced below): 12 or more characters from [A-Za-z0-9_+=.@-].
-- That charset is not cosmetic — it is what makes the dynamic SQL below safe to
-- build without quote-escaping, and it rules out ';', '\' and '"' entirely.
-- ---------------------------------------------------------------------------

SET @reactor_py_featured_writer_database :=
  IFNULL(NULLIF(@reactor_py_featured_writer_database, ''), 'ai-agent-station');

-- Guard: refuse to run with a missing, short, or unsafe password. The failure
-- mode is a missing-table error whose name states exactly what to do, rather
-- than a silently created account with a known password.
-- IFNULL matters: a NULL session variable is binary, and REGEXP against a
-- utf8mb4 pattern raises a charset error that hides the real problem.
SET @reactor_py_featured_writer_ok := IFNULL(@reactor_py_featured_writer_password, '')
  REGEXP '^[A-Za-z0-9_+=.@-]{12,}$';

SET @ddl := IF(
  @reactor_py_featured_writer_ok,
  CONCAT(
    'CREATE USER IF NOT EXISTS ''reactor_py_featured_writer''@''%'' IDENTIFIED BY ''',
    @reactor_py_featured_writer_password,
    ''''
  ),
  'SELECT * FROM abort__set_reactor_py_featured_writer_password_before_running'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- SELECT across the schema (read side of the slice: session existence check and
-- the pre-upsert row lookups). Quoted because the default database name contains
-- hyphens. USAGE is implicit.
SET @ddl := CONCAT(
  'GRANT SELECT ON `', @reactor_py_featured_writer_database, '`.*',
  ' TO ''reactor_py_featured_writer''@''%'''
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Writer grant: exactly one table, exactly two verbs. No DELETE (soft delete is
-- an UPDATE), no CREATE/ALTER/DROP/INDEX/GRANT.
SET @ddl := CONCAT(
  'GRANT INSERT, UPDATE ON `', @reactor_py_featured_writer_database,
  '`.ai_agent_featured_conversation TO ''reactor_py_featured_writer''@''%'''
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verify from the same session: the account must hold SELECT plus INSERT/UPDATE
-- on the one table, and nothing else. Both statements are informational, not
-- assertions — read the output.
SELECT user, host, plugin, account_locked, password_expired
  FROM mysql.user
 WHERE user = 'reactor_py_featured_writer';

SHOW GRANTS FOR 'reactor_py_featured_writer'@'%';
