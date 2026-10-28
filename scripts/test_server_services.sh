#!/usr/bin/env bash
# Start the engine's scheduled work on the test server, against its own database
# (review of 26 Oct 2026, point 6): the sync loop (a pass every few minutes) and the
# scheduler (every nightly job at 2 AM IST). Both run in the background and keep
# running while this Windows session stays signed in (disconnecting Remote Desktop is
# fine; signing out stops them). Logs go to logs/.
#
# It also runs the engine's API (POST /v1/recommendations, GET /health) for SOCO_BE on
# the same server, on http://127.0.0.1:8100 (ENGINE_PORT to change; this server only,
# not the internet). It answers exactly as settings/engine.toml says: with a surface
# off it returns 503 and SOCO_BE shows its own ordering (APP-15 rule 3). No test-only
# time limits here: it keeps the real request budget.
#
#     bash scripts/test_server_services.sh start
#     bash scripts/test_server_services.sh status
#     bash scripts/test_server_services.sh stop
#
# The next morning: .venv/Scripts/python.exe scripts/show_job_runs.py --by scheduler
set -u
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
set -a; . ./.env; set +a
export RECO_STATE_DIR="${RECO_STATE_DIR:-$(cd .. && pwd)/reco-state}"; mkdir -p "$RECO_STATE_DIR"
grep -q '^ENGINE_ENV=test' .env || { echo "STOP: .env must say ENGINE_ENV=test"; exit 1; }
mkdir -p logs
case "${1:-status}" in
  start)
    for job in sync_loop scheduler api; do
      if [ -f "logs/$job.pid" ] && kill -0 "$(cat "logs/$job.pid")" 2>/dev/null; then echo "$job already running"; continue; fi
      if [ "$job" = api ]; then
        nohup env -u REQUEST_BUDGET_MS -u SOURCE_TIME_LIMIT_MS "$PY" -m uvicorn reco.main:app --host 127.0.0.1 --port "${ENGINE_PORT:-8100}" >>"logs/$job.log" 2>&1 &
      else
        nohup "$PY" -m reco.jobs "$job" >>"logs/$job.log" 2>&1 &
      fi
      echo $! >"logs/$job.pid"; echo "started $job (pid $!), database ${ML_MONGO_DB:-soco_engine_test}, log logs/$job.log"
    done
    [ -f logs/api.pid ] && echo "engine API: http://127.0.0.1:${ENGINE_PORT:-8100} (check: curl -s http://127.0.0.1:${ENGINE_PORT:-8100}/health)" ;;
  stop)
    for job in sync_loop scheduler api; do
      [ -f "logs/$job.pid" ] && kill "$(cat "logs/$job.pid")" 2>/dev/null && echo "stopped $job"; rm -f "logs/$job.pid"
    done ;;
  status)
    for job in sync_loop scheduler api; do
      if [ -f "logs/$job.pid" ] && kill -0 "$(cat "logs/$job.pid")" 2>/dev/null; then echo "$job running (pid $(cat "logs/$job.pid"))"
      else echo "$job not running"; fi
    done ;;
esac
