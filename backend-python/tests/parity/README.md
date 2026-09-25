# Cloned-database Java / Python parity (featured-admin)

Proves the slice's acceptance criterion: **the same request sequence against Java
and against Python, on two databases cloned from one snapshot, produces equivalent
HTTP responses and equivalent contents of every affected table.**

```
featured_admin_parity.py   request sequence + table dump + normalized diff
```

Nothing here is imported by production code. Artifacts land in `build/` and are
gitignored.

## What is compared

1. **HTTP responses** for the full admin sequence — status, the recorded header
   set, and the JSON body with key order preserved. Nondeterminism (the
   `BasicErrorController` clock, `updatedAt`/`publishedAt` stamps written by the
   run itself) is removed only by naming exact JSON Pointers in `--ignore-pointer`.
   There is no global ignore list.
2. **Effects of the writes, through the read paths**, not just the tables. The
   already-cut-over public reads (`/api/agent/featured-conversations`,
   `/home`) are hit after `online` and again after `offline`, and the set of
   `featuredId` values they expose is compared. A write that lands in the table
   but never becomes visible through the read path fails here.
3. **All affected tables**, full contents, keyed by business key rather than row
   id:
   * `ai_agent_featured_conversation` — the writer target;
   * `ai_agent_dialogue_session` — to prove `create` only *reads* it and never
     writes it. Checked twice: cross-side (Java post vs Python post), and
     pre-vs-post per side with `update_time` **kept**, so a sneaky write cannot
     hide behind the engine-column drop.

Not every body is deterministic, so each case declares one of three modes:

| mode | compares | used for |
| --- | --- | --- |
| `exact` | status, headers, normalized body | filtered admin lists, all writes, all error shapes |
| `featured_ids` | status, headers, the **set** of `featuredId`s in the body | public-read effect witnesses (row order is `id DESC` tiebreak inside snapshot data) |
| `shape` | status, headers, `data.total`, `data.list` length | unfiltered admin lists (row *identity* is snapshot-dependent; count and page width are not) |

On top of the mode, a case may assert `must_contain` / `must_absent` substrings
and `expect_list_length` / `expect_data_total` on **both** sides.

### Column policy

| columns | policy | why |
| --- | --- | --- |
| `id`, `create_time`, `update_time` | dropped from the cross-side diff | `AUTO_INCREMENT` / `DEFAULT CURRENT_TIMESTAMP` / `ON UPDATE CURRENT_TIMESTAMP` — engine-driven, cannot be forced equal across two clones |
| `published_at`, `updated_at` | compared by null-ness exactly, and by a `--timestamp-tolerance-seconds` window (default 300s) when both sides are non-null | application wall-clocks stamped by this very run |
| everything else | compared exactly | deterministic from the request |

`update_time` is kept in the pre-vs-post `ai_agent_dialogue_session` diff — that
is the witness that `create` never writes the session table.

## Why two databases, not one

The single-writer rule forbids Java and Python writing the same database at the
same time. So the drill clones the snapshot twice (`java_side`, `python_side`),
points Java at one and Python at the other, runs the identical sequence against
each, then diffs the two resulting states. That is the only way to compare writes
without ever having two writers on one database.

The script enforces this: if `--java-db-url` and `--python-db-url` name the same
database it exits 2 before sending anything.

## Commands

```bash
# 1) throwaway mysqld (never /usr/local/var/mysql) with two databases cloned
#    from one snapshot:
#      ai_agent_station_java   <- Java's spring.datasource.url
#      ai_agent_station_py     <- REACTOR_PY_MYSQL_DATABASE
#    both loaded from the same db/schema.sql + the same seed.

# 2) Java (:8100) with writes ENABLED and its datasource pointing at *_java
#    (Java has no writer fence; it is the current owner of these routes).
# 3) Python (:8200) with
#      REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER=python
#      REACTOR_PY_MYSQL_USER=reactor_py_featured_writer   (or the test clone)
#      REACTOR_PY_MYSQL_DATABASE=ai_agent_station_py

backend-python/tests/parity/featured_admin_parity.py \
  --java-base-url  http://127.0.0.1:8100 \
  --python-base-url http://127.0.0.1:8200 \
  --java-db-url 'mysql+asyncmy://<test-admin>:<test-only>@127.0.0.1:3307/ai_agent_station_java?charset=utf8mb4' \
  --python-db-url 'mysql+asyncmy://<test-admin>:<test-only>@127.0.0.1:3307/ai_agent_station_py?charset=utf8mb4' \
  --output build/parity-featured-admin.json
```

Writes go to **Java first, then Python** — never interleaved, and each side only
ever talks to its own database. Exit code 0 only when there are zero response
differences and zero table differences. The report names every differing JSON
Pointer / column / business key.

## Gates that are easy to get wrong

- **R-33 (fixture contamination).** The two databases must be cloned from *one*
  snapshot before the run and must not share a connection pool with any other
  test. The script asserts the two sides agree on both tables before it writes
  anything, so a drifted fixture fails as a named finding rather than a mystery
  diff at the end.
- **Replay is non-conflicting, not state-preserving.** Every `sessionId` embeds a
  per-invocation `run_id` (override with `--run-id`), so re-running against the
  same pair of databases adds its own rows instead of fighting the previous run's
  UNIQUE keys. Both sides get the same `run_id` in one invocation. The
  `ON DUPLICATE KEY UPDATE` branch is exercised *within* a run: `create-s1` then
  `create-s1-duplicate` reuse the same `sessionId`.
- **R-26.** Every client uses `trust_env=False` / `--noproxy '*'`.
- **R-34.** The credentials here are test-only for a throwaway database. They
  never enter the report, argv of the script itself, or the repository — the
  report records database *names* only. Production credentials and `~/.my.cnf`
  are out of bounds.
- **Unfiltered lists are not exact-comparable.** `query-list-lombok-defaults` and
  `query-list-whitespace-title` return snapshot rows whose order depends on
  `id DESC` tiebreaks, so they use `shape` mode. A snapshot whose `sort_order`
  reaches `2000000000` is reported as a warning so that a surprising fixture is
  named rather than silently reshaping the page.
