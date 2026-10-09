#!/bin/sh
# Spin up llm_guardrails services with one command (uv version).
# Usage: ./run.sh   (ports/behavior from .env: WITH_BRIDGE=0 normal dev,
#        WITH_BRIDGE=1 bench mode -- bridge on :8080, dashboard on :8081,
#        proxy moves to :8002 so the bench server can take :8000)
#        (Ctrl-C stops everything)
# POSIX sh compatible (works with sh, dash, bash).
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "ERROR: .env missing. Run: cp .env.example .env  # then fill in UPSTREAM_* values" >&2
  exit 1
fi

if [ ! -f governance.db ]; then
  echo "== governance.db missing, initializing... =="
  uv run scripts/init_db.py
fi

# Read toggles from .env without sourcing it (never eval secrets).
# Only pre-declared keys are picked up; anything else in .env is ignored.
WITH_BRIDGE=$(grep -E '^WITH_BRIDGE=' .env 2>/dev/null | tail -n 1 | cut -d '=' -f 2- | tr -d '[:space:]')
WITH_BRIDGE=${WITH_BRIDGE:-0}

DASH_PORT=8080
PROXY_PORT=8000
if [ "$WITH_BRIDGE" = "1" ]; then
  DASH_PORT=8081   # :8080 is the bench hook contract port when bridging
  PROXY_PORT=8002  # :8000 is the bench server's port when bridging
fi

mkdir -p logs

# Stop every process this script started, including grandchildren
# (`uv run` -> python). PIDs are recorded as each service starts: `jobs -p`
# returns nothing inside $(...) or a pipe under dash (/bin/sh on Ubuntu), so
# the old cleanup silently killed nothing and left servers holding ports.
PIDS=""
kill_tree() {
  for child in $(pgrep -P "$1" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$1" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM EXIT
  echo ""
  echo "== stopping all services... =="
  for pid in $PIDS; do
    kill_tree "$pid"
  done
}
trap cleanup INT TERM EXIT

# Warn (don't fail) when a port is already taken -- usually a previous
# run.sh that is still running, whose services would keep serving old code.
for port in 8001 "$PROXY_PORT" "$DASH_PORT" 8080 8000; do
  if [ "$port" = "8080" ] && [ "$WITH_BRIDGE" != "1" ]; then continue; fi
  if [ "$port" = "8000" ] && [ "$WITH_BRIDGE" != "1" ]; then continue; fi
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$port "; then
    echo "WARN port :$port is already in use -- stop the previous run.sh (or that process) first, or it keeps serving old code" >&2
  fi
done

wait_for() {
  url="$1"; name="$2"
  i=1
  while [ "$i" -le 30 ]; do
    if curl -sf -o /dev/null "$url" 2>/dev/null; then
      echo "OK   $name -> $url"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "FAIL $name not up at $url -- tail logs/$name.log" >&2
  return 1
}

echo "== starting governance_api :8001 =="
(cd governance_api && PROXY_PUBLIC_URL="http://localhost:$PROXY_PORT" uv run uvicorn main:app --port 8001 --reload) > logs/governance_api.log 2>&1 &
PIDS="$PIDS $!"
# governance_api loads the NER model at startup -- everything else waits for
# it so seeding/health checks don't race it.
wait_for http://localhost:8001/healthz governance_api
if [ "$WITH_BRIDGE" = "1" ]; then
  echo "== bench mode: proxy on :$PROXY_PORT (bench server needs :8000) =="
else
  echo "== starting proxy :$PROXY_PORT =="
fi
(cd proxy && uv run uvicorn main:app --port "$PROXY_PORT" --reload) > logs/proxy.log 2>&1 &
PIDS="$PIDS $!"
echo "== starting dashboard :$DASH_PORT =="
(cd dashboard && uv run python -m http.server "$DASH_PORT") > logs/dashboard.log 2>&1 &
PIDS="$PIDS $!"
if [ "$WITH_BRIDGE" = "1" ]; then
  echo "== starting bench_bridge :8080 =="
  (cd bench_bridge && uv run uvicorn main:app --port 8080 --reload) > logs/bench_bridge.log 2>&1 &
  PIDS="$PIDS $!"
fi
# Bench mode also starts the GuardRailBench sample apps on :8000 when that repo
# sits next to this one, so the dashboard's test console can run the
# multi-agent, single-agent and RAG apps. run_all.py reuses whatever is on
# :8000, so the bench suite still runs normally.
BENCH_DIR="$ROOT/../GuardRailBench-Sample"
BENCH_APP=0
if [ "$WITH_BRIDGE" = "1" ] && [ -f "$BENCH_DIR/server.py" ] && [ -x "$BENCH_DIR/.venv/bin/python" ]; then
  BENCH_APP=1
  echo "== starting GuardRailBench apps :8000 (test console) =="
  (cd "$BENCH_DIR" && .venv/bin/python -m uvicorn server:app --port 8000 --workers 1) > logs/bench_app.log 2>&1 &
  PIDS="$PIDS $!"
fi

echo "logs: logs/governance_api.log logs/proxy.log logs/dashboard.log"
echo "waiting for remaining health checks (max ~30s)..."

wait_for "http://localhost:$PROXY_PORT/healthz" proxy
wait_for "http://localhost:$DASH_PORT/" dashboard
if [ "$WITH_BRIDGE" = "1" ]; then
  wait_for http://localhost:8080/healthz bench_bridge
fi
if [ "$BENCH_APP" = "1" ]; then
  wait_for http://localhost:8000/health bench_app || echo "WARN GuardRailBench apps not up; the test console's bench modes will be unavailable (logs/bench_app.log)"
fi

echo ""
echo "All up:"
echo "  api:       http://localhost:8001/healthz"
echo "  proxy:     http://localhost:$PROXY_PORT/healthz"
echo "  dashboard: http://localhost:$DASH_PORT/index.html"
if [ "$WITH_BRIDGE" = "1" ]; then
  echo "  bridge:    http://localhost:8080/healthz (GuardRailBench hook contract)"
  [ "$BENCH_APP" = "1" ] && echo "  bench app: http://localhost:8000/health (GuardRailBench sample apps)"
  echo "Chat: uv run examples/chat_interface.py  (examples follow WITH_BRIDGE -> proxy :$PROXY_PORT)"
fi
echo "Verify with:"
if [ "$WITH_BRIDGE" != "1" ]; then
  echo "  curl localhost:8001/healthz; curl localhost:$PROXY_PORT/healthz; curl -s localhost:$DASH_PORT/ | head -5"
else
  echo "  curl localhost:8001/healthz; curl localhost:$PROXY_PORT/healthz; curl localhost:8080/healthz; curl -s localhost:$DASH_PORT/ | head -5"
fi
echo "Press Ctrl-C to stop everything."
wait
