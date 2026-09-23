-- Provision the phase-3 read-only database account for reactor-backend-python.
--
-- Why this exists (risk-register.md R-22): until now both backends connected
-- with the same read-write account `reactor`, so the single-writer rule had no
-- technical enforcement. This account can only SELECT, so a Python bug, a stray
-- migration, or a future writer landing early cannot touch a table through it.
--
-- Scope is SELECT on the whole schema, deliberately not a table list. The rule
-- being enforced is "Python must not write" — not read isolation. Java already
-- reads every table, and the phase-3 read set grows with each slice (the featured
-- pilot alone reaches featured_conversation, dialogue_session, dialogue_run,
-- llm_invocation, tool_invocation, artifact and tool_output_*). Re-granting per
-- slice would be busywork without a security benefit. Tighten to a table list
-- later if a real read-isolation requirement appears.
--
-- Idempotent: re-running is safe. This file only ever GRANTs; it never REVOKEs,
-- so re-applying it cannot widen or narrow an existing grant by accident.
--
-- ---------------------------------------------------------------------------
-- The password is NOT in this file. Set it before running, or the run aborts:
--
--   SET @reactor_py_ro_password := '<from your secret store>';
--   SET @reactor_py_ro_database := 'ai-agent-station';   -- optional override
--   SOURCE db/migrations/20260923_provision_phase3_readonly_account.sql;
--
-- Never pass the password on the mysql command line: it would land in shell
-- history and the process list. Use an interactive SET, a client option file
-- outside the repository, or a secrets store that injects the session variable.
--
-- Password policy (enforced below): 12 or more characters from [A-Za-z0-9_+=.@-].
-- That charset is not cosmetic — it is what makes the dynamic SQL below safe to
-- build without quote-escaping, and it rules out ';', '\' and '"' entirely.
-- ---------------------------------------------------------------------------

SET @reactor_py_ro_database := IFNULL(NULLIF(@reactor_py_ro_database, ''), 'ai-agent-station');

-- Guard: refuse to run with a missing, short, or unsafe password. The failure
-- mode is a missing-table error whose name states exactly what to do, rather
-- than a silently created account with a known password.
-- IFNULL matters: a NULL session variable is binary, and REGEXP against a
-- utf8mb4 pattern raises a charset error that hides the real problem.
SET @reactor_py_ro_ok := IFNULL(@reactor_py_ro_password, '')
  REGEXP '^[A-Za-z0-9_+=.@-]{12,}$';

SET @ddl := IF(
  @reactor_py_ro_ok,
  CONCAT(
    'CREATE USER IF NOT EXISTS ''reactor_py_ro''@''%'' IDENTIFIED BY ''',
    @reactor_py_ro_password,
    ''''
  ),
  'SELECT * FROM abort__set_reactor_py_ro_password_before_running'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- SELECT-only. Quoted because the default database name contains hyphens.
-- USAGE is implicit; no INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/GRANT/etc.
SET @ddl := CONCAT(
  'GRANT SELECT ON `', @reactor_py_ro_database, '`.* TO ''reactor_py_ro''@''%'''
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verify from the same session: the account must be able to read and must not
-- hold any write privilege. Both statements are informational, not assertions —
-- read the output.
SELECT user, host, plugin, account_locked, password_expired
  FROM mysql.user
 WHERE user = 'reactor_py_ro';

SHOW GRANTS FOR 'reactor_py_ro'@'%';
