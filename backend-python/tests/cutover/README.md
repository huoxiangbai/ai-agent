# Phase 3B cutover / rollback drill

Proves that exactly three public featured GETs move to Python and everything
else stays on Java — and that the move can be undone. See
`docs/python-migration/execplans/featured-public-cutover.md` for the full
runbook; this directory is the harness.

```
gen_config.py   renders a runnable nginx.conf from production docker/nginx.conf
probes.py       the fixed 14-probe set + upstream attribution + phase diffing
drill.sh        nginx lifecycle and the same checks at every phase
```

Nothing here is imported by production code. Artifacts land in
`build/cutover-drill/` and are gitignored.

## What is actually being proven

The three featured URIs are contract-identical on both backends by design, so no
body-level test can tell which upstream answered. Two witnesses are used:

- **`$upstream_addr`** from nginx's `cutover` log format — the only reliable
  attribution. Parsed by `probes.py`, which fails the phase if any probe was
  served by the wrong upstream.
- **Body/status/header stability vs the `pre` phase** — `pre` runs entirely
  against Java through the drill nginx and becomes the reference. Every later
  phase must reproduce those responses. Nondeterminism is removed by naming exact
  JSON Pointers in `BASE_POINTERS` / `EXTRA_POINTERS` (an error-body clock, and
  the random `eventData.taskId` UUID Java generates per call) — the same rule the
  contract lab uses, per case and with no global ignore list. Contract-grade
  evidence (per-case JSON Pointer allowlists) lives in
  `tests/contract/cases/phase3-featured*.json`.

Near-misses (trailing slash, multi-segment) are pinned to Java on purpose: the
detail location is a single-segment regex so a request like
`/api/agent/featured-conversations/a/b` keeps Java's Spring error body instead
of being swallowed by a prefix match.

## Commands

```bash
# backends must already be up; drill.sh refuses to proceed otherwise
backend-python/tests/cutover/drill.sh up

backend-python/tests/cutover/drill.sh check pre        # everything on Java
backend-python/tests/cutover/drill.sh cutover          # switch ON  (timed)
backend-python/tests/cutover/drill.sh check on-python
backend-python/tests/cutover/drill.sh rollback         # switch OFF (timed + recovery)
backend-python/tests/cutover/drill.sh check on-java
backend-python/tests/cutover/drill.sh cutover          # leave it on Python
backend-python/tests/cutover/drill.sh check final

backend-python/tests/cutover/drill.sh status
backend-python/tests/cutover/drill.sh down
```

`cutover` and `rollback` append to `build/cutover-drill/timing.log`. `rollback`
times both the switch itself and the end-to-end window until the recovery probes
pass on Java again.

`check` runs, at every phase, the same three things: the probe set, both
contract manifests (`phase3-featured.json`, `phase3-featured-errors.json`) live
against their Java goldens, and the four frontend consumer test files.

## Gates that are easy to get wrong

- **R-32.** `reactor-contract` exits 0 when a case lands in `skipped` (for
  example a missing `${CONTRACT_*}` variable). `drill.sh` therefore gates on
  `skipped == []` *and* on the expected case count, never on the exit code.
- **R-26.** A machine-level proxy hijacks `127.0.0.1` on this host. Every
  `httpx` client here uses `trust_env=False`; every `curl` uses `--noproxy '*'`.
- **R-31.** zsh globs `[0]`; MySQL 9.3 has no `mysql_native_password`;
  `mysqld` needs `--no-defaults` plus an explicit `--datadir`.
- **R-33.** The contract goldens were recorded against a database seeded with
  `contract-seed.sql` only. `featured_read_edge_seed.sql` must never share that
  database — its malformed-JSON fixture row makes Java throw a 500 that has
  nothing to do with the cutover.
- **R-34.** Python runs as `reactor_py_ro` (SELECT-only). The password for the
  throwaway database is test-only and is never written to argv, a report, or the
  repo.

## Header identity

`probes.py` records `content-type`, `server`, `allow`, `location`,
`x-accel-buffering` and `vary` as sorted comma-token lists, with an absent
header recorded as `[]`. That makes "Java sends no `Server` header" versus
"Python sends `Server: uvicorn`" an ordinary hard-failing mismatch instead of a
silent pass. Matching Java here is load-bearing and is why
`backend-python/Dockerfile` passes `--no-server-header`.
