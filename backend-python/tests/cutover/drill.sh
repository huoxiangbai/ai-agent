#!/usr/bin/env bash
# Phase 3B cutover / rollback drill (nginx side).
#
# Owns only the nginx lifecycle and the fixed checks. MySQL, Java (:8100) and
# Python (:8200) are brought up by the documented commands in
# docs/python-migration/execplans/featured-public-cutover.md — this script
# refuses to proceed until they answer, rather than trying to boot them (their
# bring-up carries host-specific quirks, see risk-register.md R-31).
#
#   drill.sh up                  generate drill nginx.conf from docker/nginx.conf,
#                                nginx -t, start nginx on :18080 (starts rolled
#                                back: no fragment present)
#   drill.sh cutover             install the fragment + nginx -t + reload (timed)
#   drill.sh rollback            remove the fragment + nginx -t + reload (timed),
#                                then wait for recovery probes to pass on Java
#   drill.sh check <phase>       run the same smoke/contract/frontend checks
#   drill.sh status              show switch state and backend liveness
#   drill.sh down                stop the drill nginx (logs kept for audit)
#
# All artifacts land under build/cutover-drill/ and are not committed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND_PY="$ROOT/backend-python"
DRILL="$ROOT/build/cutover-drill"
PREFIX="$DRILL/nginx"
CONF="$PREFIX/nginx.conf"
FRAG_DIR="$PREFIX/featured-python.d"
FRAG_NAME="featured-conversations.conf"
FRAG_SRC="$ROOT/docker/nginx-featured-python.d/$FRAG_NAME"
PROD_NGINX="$ROOT/docker/nginx.conf"
CHECKS="$DRILL/checks"
PORT="${DRILL_PORT:-18080}"
BASE="http://127.0.0.1:$PORT"

export CONTRACT_VISITOR_TOKEN=fixture-raw-token
export CONTRACT_SESSION_ID=fixture-session
export CONTRACT_FEATURED_ID=fixture-featured

log() { printf '[drill] %s\n' "$*"; }

now() { python3 -c 'import time; print(f"{time.time():.6f}")'; }

nginx_bin() { command -v nginx; }

nginx_ctl() {
  "$(nginx_bin)" -p "$PREFIX/" -c "$CONF" "$@"
}

wait_http() {
  # curl --noproxy: a machine-level proxy hijacks 127.0.0.1 on this host (R-26).
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
  wait_http "http://127.0.0.1:8100/web/health" "java" 5
  wait_http "http://127.0.0.1:8200/internal/health/ready" "python" 5
}

cmd_up() {
  mkdir -p "$PREFIX/tmp" "$FRAG_DIR" "$PREFIX/html" "$CHECKS"
  python3 "$BACKEND_PY/tests/cutover/gen_config.py" \
    --source "$PROD_NGINX" \
    --prefix "$PREFIX" \
    --listen-port "$PORT" \
    --output "$CONF"
  # Switch starts in the rolled-back state so `up` is a clean baseline.
  rm -f "$FRAG_DIR"/*.conf "$FRAG_DIR"/*.conf.disabled
  log "nginx -t (switch OFF / all traffic on Java) ..."
  local t_check
  if nginx_ctl -t; then
    log "nginx -t exit=0 (recorded as the routing-config syntax check, switch OFF)"
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
  # The live switch must be byte-identical to the committed fragment.
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
  python3 -c "print(f'[drill] cutover applied in {$t1 - $t0:.3f}s (file copy + nginx -t + reload)')"
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
  python3 -c "print(f'[drill] rollback applied in {$t1 - $t0:.3f}s (file removal + nginx -t + reload)')"
  # End-to-end: time until the recovery probes actually pass on Java again.
  if "$0" _recovery_probe; then
    t2=$(now)
    python3 -c "print(f'[drill] rollback verified end-to-end in {$t2 - $t0:.3f}s (apply {$t1 - $t0:.3f}s + recovery verification)')"
  else
    t2=$(now)
    log "ERROR: rollback did not recover within the probe window (elapsed $(python3 -c "print(f'{$t2 - $t0:.3f}')")s)"
    echo "$t0 $t2 rollback-FAILED" >> "$DRILL/timing.log"
    exit 1
  fi
  echo "$t0 $t2 rollback" >> "$DRILL/timing.log"
}

cmd_check() {
  local phase=${1:?usage: drill.sh check <phase>}
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

  log "[$phase] smoke probes ..."
  (cd "$BACKEND_PY" && uv run python tests/cutover/probes.py \
    --base-url "$BASE" \
    --phase "$phase" \
    --access-log "$PREFIX/access.log" \
    --output "$out/probes.json" \
    ${expect_flag[@]+"${expect_flag[@]}"} \
    ${reference[@]+"${reference[@]}"}) | tee "$out/probes.txt"

  log "[$phase] contract (live via nginx vs java goldens) ..."
  local manifest golden label
  for spec in \
    "phase3-featured.json:java-featured.json:featured:3" \
    "phase3-featured-errors.json:java-featured-errors.json:featured-errors:4"
  do
    manifest=${spec%%:*}
    spec=${spec#*:}
    golden=${spec%%:*}
    spec=${spec#*:}
    label=${spec%%:*}
    local expected=${spec##*:}
    (cd "$BACKEND_PY" && \
      PYTHON_BASE_URL="$BASE" \
      uv run reactor-contract "tests/contract/cases/$manifest" \
        --golden "tests/contract/golden/$golden" \
        --output "$out/contract-$label.json") | tee "$out/contract-$label.txt"
    # R-32: exit code alone is not a gate — a case can land in `skipped`.
    python3 - "$out/contract-$label.json" "$expected" "$label" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = int(sys.argv[2])
label = sys.argv[3]
cases = report.get("cases", [])
skipped = report.get("skipped", [])
diffs = {
    c["name"]: c.get("differences") or []
    for c in cases
    if not c.get("matched")
}
print(f"contract[{label}] cases={len(cases)} skipped={skipped} differing={list(diffs)}")
if skipped or diffs or len(cases) < expected:
    print(json.dumps({"skipped": skipped, "diffs": diffs}, ensure_ascii=False, indent=2))
    raise SystemExit(1)
PY
  done

  log "[$phase] frontend consumer tests ..."
  (cd "$ROOT/ui" && npx vitest run \
    src/services/featuredConversation.test.ts \
    src/pages/FeaturedConversations/view.test.tsx \
    src/pages/FeaturedConversationDetail/view.test.tsx \
    src/pages/Home/WelcomeView.test.tsx) | tee "$out/frontend.txt"

  log "[$phase] OK"
}

cmd_status() {
  local state=OFF
  [[ -f "$FRAG_DIR/$FRAG_NAME" ]] && state=ON
  log "switch: $state (fragment in $FRAG_DIR)"
  if [[ -f "$PREFIX/nginx.pid" ]] && kill -0 "$(cat "$PREFIX/nginx.pid")" 2>/dev/null; then
    log "drill nginx: running (pid $(cat "$PREFIX/nginx.pid")) on :$PORT"
  else
    log "drill nginx: not running"
  fi
  curl -sS --noproxy '*' -o /dev/null -w 'java  :8100 -> %{http_code}\n' --max-time 3 \
    "http://127.0.0.1:8100/web/health" || log "java  :8100 -> down"
  curl -sS --noproxy '*' -o /dev/null -w 'python:8200 -> %{http_code}\n' --max-time 3 \
    "http://127.0.0.1:8200/internal/health/ready" || log "python:8200 -> down"
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
    # Inline the generated port/log paths.
    python3 - "$PORT" "$PREFIX/access.log" <<'PY'
import re
import sys
import time
from pathlib import Path

import httpx

port, access = sys.argv[1], Path(sys.argv[2])
base = f"http://127.0.0.1:{port}"
pattern = re.compile(r'"(?P<req>[^"]+)" \d+ \d+ upstream="(?P<up>[^"]*)"')
targets = [
    ("GET /api/agent/featured-conversations/home?limit=6 HTTP/1.1", 200),
    ("GET /api/agent/featured-conversations?pageNo=1&pageSize=20 HTTP/1.1", 200),
    ("GET /api/agent/featured-conversations/fixture-featured HTTP/1.1", 200),
    ("GET /web/health HTTP/1.1", 200),
]

last = None
deadline = time.time() + 15
while time.time() < deadline:
    try:
        with httpx.Client(base_url=base, trust_env=False, timeout=5.0) as client:
            for request_line, want in targets:
                _method, uri, _ = request_line.split(" ")
                path, _, query = uri.partition("?")
                params = dict(p.split("=", 1) for p in query.split("&") if p)
                response = client.request(_method, path, params=params or None)
                if response.status_code != want:
                    raise RuntimeError(f"{request_line} -> {response.status_code}")
        latest = {}
        if access.exists():
            for line in access.read_text(encoding="utf-8", errors="replace").splitlines():
                match = pattern.search(line)
                if match:
                    latest[match.group("req")] = match.group("up")
        health_up = latest.get("GET /web/health HTTP/1.1", "")
        if not health_up.endswith(":8100"):
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
    sed -n '2,20p' "$0"
    exit 2
    ;;
esac
