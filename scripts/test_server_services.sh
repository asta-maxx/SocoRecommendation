#!/usr/bin/env bash
# Start the engine's scheduled work on the test server, against its own database
# (review of 26 Oct 2026, point 6): the sync loop (a pass every few minutes) and the
# scheduler (every nightly job at 2 AM IST). Both run in the background and keep
# running while this Windows session stays signed in (disconnecting Remote Desktop is
# fine; signing out stops them). Logs go to logs/.
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
    for job in sync_loop scheduler; do
      if [ -f "logs/$job.pid" ] && kill -0 "$(cat "logs/$job.pid")" 2>/dev/null; then echo "$job already running"; continue; fi
      nohup "$PY" -m reco.jobs "$job" >>"logs/$job.log" 2>&1 &
      echo $! >"logs/$job.pid"; echo "started $job (pid $!), database ${ML_MONGO_DB:-soco_engine_test}, log logs/$job.log"
    done ;;
  stop)
    for job in sync_loop scheduler; do
      [ -f "logs/$job.pid" ] && kill "$(cat "logs/$job.pid")" 2>/dev/null && echo "stopped $job"; rm -f "logs/$job.pid"
    done ;;
  status)
    for job in sync_loop scheduler; do
      if [ -f "logs/$job.pid" ] && kill -0 "$(cat "logs/$job.pid")" 2>/dev/null; then echo "$job running (pid $(cat "logs/$job.pid"))"
      else echo "$job not running"; fi
    done ;;
esac
