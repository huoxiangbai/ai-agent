#!/usr/bin/env bash
# Phase 4 featured-admin cutover / rollback drill (nginx side).
#
# Complements drill.sh (phase 3B public reads). This one switches exactly the five
# admin URIs and proves the reverse rollback. MySQL, Java and Python are brought up
# separately — this script refuses to proceed until they answer (risk-register.md
# R-31 covers the bring-up quirks).
#
# Backends default to Java :8100 / Python :8200, matching docker/nginx.conf. When
# those ports are held by another process, run the backends on free ports and
# point the drill at them with DRILL_JAVA_PORT / DRILL_PYTHON_PORT (and
# DRILL_TOOL_PORT if reactor-tool is not on :1601). Defaults preserve the phase-3B
# behaviour exactly.
#
#   admin_drill.sh up               generate drill nginx.conf, start nginx on
#                                   :18081 (starts rolled back: no fragment)
#   admin_drill.sh cutover          install featured-admin.conf + nginx -t +
#                                   reload (timed)
#   admin_drill.sh rollback         remove the fragment + nginx -t + reload (timed),
#                                   then wait for recovery probes to pass on Java
#   admin_drill.sh check <phase>    probes + contract + frontend checks
#   admin_drill.sh status           switch state and backend liveness
#   admin_drill.sh down             stop the drill nginx (logs kept for audit)
#
# PRECONDITION for `cutover`: REACTOR_PY_FEATURED_ADMIN_WRITE_OWNER=python and
# REACTOR_PY_MYSQL_USER=reactor_py_featured_writer on the Python process. With
# either still closed the switch still routes, but every write answers 0001 /
# ERROR 1142 — that is the fail-closed behaviour, not a drill failure.
#
# Artifacts land under build/cutover-drill-admin/ and are not committed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND_PY="$ROOT/backend-python"
DRILL="$ROOT/build/cutover-drill-admin"
PREFIX="$DRILL/nginx"
CONF="$PREFIX/nginx.conf"
FRAG_DIR="$PREFIX/featured-python.d"
FRAG_NAME="featured-admin.conf"
FRAG_SRC="$ROOT/docker/nginx-featured-python.d/$FRAG_NAME"
PROD_NGINX="$ROOT/docker/nginx.conf"
CHECKS="$DRILL/checks"
PORT="${DRILL_ADMIN_PORT:-18081}"
JAVA_PORT="${DRILL_JAVA_PORT:-8100}"
PYTHON_PORT="${DRILL_PYTHON_PORT:-8200}"
TOOL_PORT="${DRILL_TOOL_PORT:-1601}"
BASE="http://127.0.0.1:$PORT"

log() { printf '[admin-drill] %s\n' "$*"; }

now() { python3 -c 'import time; print(f"{time.time():.6f}")'; }

nginx_bin() { command -v nginx; }

# Same shape as drill.sh's helper. Do NOT rewrite this as
# ``command -v nginx | xargs -I{} {}``: macOS ships BSD xargs, which does not
# honour the GNU-style ``-I{}`` and dies with ``xargs: {}: No such file or
# directory`` before nginx is ever invoked.
nginx_ctl() {
  "$(nginx_bin)" -p "$PREFIX/" -c "$CONF" "$@"
}

wait_http() {
  local url=$1 label=$2 tries=${3:-30}
  for _ in $(seq 1 "$tries"); do
    if curl -sS --noproxy '*' -o /dev/null --max-time 3 "$url"; then
      log "$label is answering ($url)"
      return 0
    fi
    sleep 1
  done
  log "ERROR: $label never answered at $url"
  return 1
}

require_backends() {
  wait_http "http://127.0.0.1:$JAVA_PORT/web/health" "java" 5
  wait_http "http://127.0.0.1:$PYTHON_PORT/internal/health/ready" "python" 5
}

cmd_up() {
  mkdir -p "$PREFIX/tmp" "$FRAG_DIR" "$PREFIX/html" "$CHECKS"
  python3 "$BACKEND_PY/tests/cutover/gen_config.py" \
    --source "$PROD_NGINX" \
    --prefix "$PREFIX" \
    --listen-port "$PORT" \
    --java-upstream-port "$JAVA_PORT" \
    --python-upstream-port "$PYTHON_PORT" \
    --tool-upstream-port "$TOOL_PORT" \
    --output "$CONF"
  # Switch starts rolled back so `up` is a clean baseline.
  rm -f "$FRAG_DIR"/*.conf "$FRAG_DIR"/*.conf.disabled
  log "nginx -t (switch OFF / all admin traffic on Java) ..."
  if nginx_ctl -t; then
    log "nginx -t exit=0 (switch OFF)"
  else
    log "nginx -t FAILED (switch OFF)"
    exit 1
  fi
  if [[ -f "$PREFIX/nginx.pid" ]] && kill -0 "$(cat "$PREFIX/nginx.pid")" 2>/dev/null; then
    nginx_ctl -s reload
  else
    nginx_ctl
  fi
  wait_http "$BASE/web/health" "drill nginx" 15
  cmd_status
}

cmd_cutover() {
  [[ -f "$FRAG_SRC" ]] || { log "ERROR: missing $FRAG_SRC"; exit 1; }
  mkdir -p "$FRAG_DIR"
  local t0 t1
  t0=$(now)
  cp "$FRAG_SRC" "$FRAG_DIR/$FRAG_NAME"
  cmp -s "$FRAG_SRC" "$FRAG_DIR/$FRAG_NAME" || { log "ERROR: fragment copy drifted"; exit 1; }
  log "nginx -t (switch ON) ..."
  if nginx_ctl -t; then
    log "nginx -t exit=0 (switch ON)"
  else
    log "nginx -t FAILED (switch ON)"
    exit 1
  fi
  nginx_ctl -s reload
  t1=$(now)
  python3 -c "print(f'[admin-drill] cutover applied in {$t1 - $t0:.3f}s (file copy + nginx -t + reload)')"
  echo "$t0 $t1 cutover" >> "$DRILL/timing.log"
}

cmd_rollback() {
  [[ -d "$FRAG_DIR" ]] || { log "ERROR: missing $FRAG_DIR"; exit 1; }
  local t0 t1 t2
  t0=$(now)
  rm -f "$FRAG_DIR"/*.conf
  log "nginx -t (switch OFF) ..."
  if nginx_ctl -t; then
    log "nginx -t exit=0 (switch OFF)"
  else
    log "nginx -t FAILED (switch OFF)"
    exit 1
  fi
  nginx_ctl -s reload
  t1=$(now)
  python3 -c "print(f'[admin-drill] rollback applied in {$t1 - $t0:.3f}s (file removal + nginx -t + reload)')"
  if "$0" _recovery_probe; then
    t2=$(now)
    python3 -c "print(f'[admin-drill] rollback verified end-to-end in {$t2 - $t0:.3f}s (apply {$t1 - $t0:.3f}s + recovery verification)')"
  else
    t2=$(now)
    log "ERROR: rollback did not recover within the probe window (elapsed $(python3 -c "print(f'{$t2 - $t0:.3f}')")s)"
    echo "$t0 $t2 rollback-FAILED" >> "$DRILL/timing.log"
    exit 1
  fi
  echo "$t0 $t2 rollback" >> "$DRILL/timing.log"
}

cmd_check() {
  local phase=${1:?usage: admin_drill.sh check <phase>}
  local out="$CHECKS/$phase"
  mkdir -p "$out"
  local expect_flag=()
  local reference=()
  case "$phase" in
    pre|on-java) expect_flag=() ;;
    on-python|final) expect_flag=(--expect-cutover) ;;
    *) log "unknown phase '$phase' (use pre|on-python|on-java|final)"; exit 1 ;;
  esac
  if [[ "$phase" != "pre" ]]; then
    reference=(--reference "$CHECKS/pre/probes.json")
  fi

  log "[$phase] admin probes ..."
  # ``tests/`` has no ``__init__.py`` (phase-3B's probes.py only imports
  # ``reactor_backend.*``), so running admin_probes.py as a script puts its own
  # directory on sys.path instead of $BACKEND_PY. PYTHONPATH restores it so the
  # ``from tests.cutover.probes import ...`` line resolves.
  (cd "$BACKEND_PY" && PYTHONPATH="$BACKEND_PY" uv run python tests/cutover/admin_probes.py \
    --base-url "$BASE" \
    --phase "$phase" \
    --access-log "$PREFIX/access.log" \
    --output "$out/probes.json" \
    --java-upstream-port "$JAVA_PORT" \
    --python-upstream-port "$PYTHON_PORT" \
    ${expect_flag[@]+"${expect_flag[@]}"} \
    ${reference[@]+"${reference[@]}"}) | tee "$out/probes.txt"

  log "[$phase] contract (live via nginx vs java goldens) ..."
  if [[ -f "$BACKEND_PY/tests/contract/cases/phase4-featured-admin.json" ]]; then
    (cd "$BACKEND_PY" && \
      PYTHON_BASE_URL="$BASE" \
      uv run reactor-contract "tests/contract/cases/phase4-featured-admin.json" \
        --golden "tests/contract/golden/java-featured-admin.json" \
        --output "$out/contract-admin.json") | tee "$out/contract-admin.txt"
    # R-32: exit code alone is not a gate — a case can land in `skipped`.
    python3 - "$out/contract-admin.json" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
cases = report.get("cases", [])
skipped = report.get("skipped", [])
diffs = {
    c["name"]: c.get("differences") or []
    for c in cases
    if not c.get("matched")
}
print(f"contract[admin] cases={len(cases)} skipped={skipped} differing={list(diffs)}")
if skipped or diffs:
    print(json.dumps({"skipped": skipped, "diffs": diffs}, ensure_ascii=False, indent=2))
    raise SystemExit(1)
PY
  else
    log "[$phase] no phase4-featured-admin manifest yet — skipped (record the golden first)"
  fi

  log "[$phase] frontend admin consumer tests ..."
  (cd "$ROOT/ui" && npx vitest run \
    src/services/featuredConversationAdmin.test.ts \
    src/pages/Home/featuredConversationAdminModel.test.ts \
    src/pages/Home/FeaturedConversationAdminPanel.test.tsx) | tee "$out/frontend.txt"

  log "[$phase] OK"
}

cmd_status() {
  local state=OFF
  [[ -f "$FRAG_DIR/$FRAG_NAME" ]] && state=ON
  log "switch: $state (fragment $FRAG_NAME in $FRAG_DIR)"
  if [[ -f "$PREFIX/nginx.pid" ]] && kill -0 "$(cat "$PREFIX/nginx.pid")" 2>/dev/null; then
    log "drill nginx: running (pid $(cat "$PREFIX/nginx.pid")) on :$PORT"
  else
    log "drill nginx: not running"
  fi
  curl -sS --noproxy '*' -o /dev/null -w "java  :$JAVA_PORT -> %{http_code}\n" --max-time 3 \
    "http://127.0.0.1:$JAVA_PORT/web/health" || log "java  :$JAVA_PORT -> down"
  curl -sS --noproxy '*' -o /dev/null -w "python:$PYTHON_PORT -> %{http_code}\n" --max-time 3 \
    "http://127.0.0.1:$PYTHON_PORT/internal/health/ready" || log "python:$PYTHON_PORT -> down"
}

cmd_down() {
  if [[ -f "$PREFIX/nginx.pid" ]] && kill -0 "$(cat "$PREFIX/nginx.pid")" 2>/dev/null; then
    nginx_ctl -s quit || true
    log "drill nginx stopped; logs kept in $PREFIX/{access,error}.log"
  else
    log "drill nginx was not running"
  fi
}

case "${1:-}" in
  up) require_backends; cmd_up ;;
  cutover) cmd_cutover ;;
  rollback) cmd_rollback ;;
  check) cmd_check "${2:-}" ;;
  _recovery_probe)
    python3 - "$PORT" "$JAVA_PORT" "$PREFIX/access.log" <<'PY'
import re
import sys
import time
from pathlib import Path

import httpx

port, java_port, access = sys.argv[1], sys.argv[2], Path(sys.argv[3])
base = f"http://127.0.0.1:{port}"
pattern = re.compile(r'"(?P<req>[^"]+)" \d+ \d+ upstream="(?P<up>[^"]*)"')
targets = [
    ("POST", "/api/v1/admin/featured-conversations/query-list", '{"pageNo":1,"pageSize":1}', 200),
    ("GET", "/web/health", None, 200),
]

last = None
deadline = time.time() + 15
while time.time() < deadline:
    try:
        with httpx.Client(base_url=base, trust_env=False, timeout=5.0) as client:
            for method, path, body, want in targets:
                response = client.request(
                    method,
                    path,
                    content=None if body is None else body.encode("utf-8"),
                    headers={} if body is None else {"content-type": "application/json"},
                )
                if response.status_code != want:
                    raise RuntimeError(f"{method} {path} -> {response.status_code}")
        latest = {}
        if access.exists():
            for line in access.read_text(encoding="utf-8", errors="replace").splitlines():
                match = pattern.search(line)
                if match:
                    latest[match.group("req")] = match.group("up")
        health_up = latest.get("GET /web/health HTTP/1.1", "")
        if not health_up.endswith(f":{java_port}"):
            raise RuntimeError(f"control not on java yet: {health_up!r}")
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001 - retry until deadline
        last = exc
        time.sleep(0.15)
print(f"recovery probe failed: {last}", file=sys.stderr)
raise SystemExit(1)
PY
    ;;
  status) cmd_status ;;
  down) cmd_down ;;
  *)
    sed -n '2,25p' "$0"
    exit 2
    ;;
esac
