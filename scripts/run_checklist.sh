#!/usr/bin/env bash
# The checklist, run end to end: every check for ENG-01 to ENG-11 and ENG-29 (pack v1.3).
#
#     bash scripts/run_checklist.sh
#     PROOF_DIR="Test Output" bash scripts/run_checklist.sh   # also saves each task's full output
#
# With PROOF_DIR set, every check's command, exit code and full output are written
# to one file per task (<PROOF_DIR>/ENG-NN.md), headed by the task's Build List
# "How to check it is done", the date, the commit and where it ran.
#
# Prints PASS or FAIL per item and a summary; exits 0 only if everything passes.
# Anything that writes uses a throwaway settings copy and the throwaway database
# reco_demo, which is dropped at the end. Ports 8190/8191 are used so a demo
# running on 8100/8101 is not disturbed. Nothing secret is printed.

set -u
cd "$(dirname "$0")/.."
# The virtual environment's Python: .venv/bin (macOS, Linux, WSL) or .venv/Scripts (Windows, Git Bash).
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=.venv/Scripts/python.exe; fi
WORK=$(mktemp -d "${TMPDIR:-/tmp}/soco-checklist.XXXXXX")
SETTINGS_COPY="$WORK/engine.toml"
LOG="$WORK/engine.log"
PASSES=0
FAILS=0
FAILED=()

# Portable helpers: macOS sed needs -i '', GNU sed (Linux, WSL, Git Bash) needs -i.
sedi() { if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi; }
# Test engines are stopped by the process id recorded when each starts; pkill as
# well where it exists (macOS, Linux, WSL). Git Bash has no pkill.
started() { eval "PID_$1=$!"; }
stop() {
  local pid; eval "pid=\${PID_$1:-}"
  [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1
  command -v pkill >/dev/null 2>&1 && pkill -f "uvicorn reco.main:app --port $1" >/dev/null 2>&1
  return 0
}
any_running() {
  local port pid
  for port in 8190 8191 8192 8197; do
    eval "pid=\${PID_$port:-}"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && return 0
  done
  command -v pgrep >/dev/null 2>&1 && pgrep -f "uvicorn reco.main:app --port 819" >/dev/null && return 0
  return 1
}
pass() { PASSES=$((PASSES + 1)); printf "  PASS  %s\n" "$1"; }
fail() { FAILS=$((FAILS + 1)); FAILED+=("$1"); printf "  FAIL  %s\n" "$1"; [ -n "${2:-}" ] && printf "        %s\n" "$2"; [ "${FUNCNAME[1]:-}" != check ] && proof "$1" "(see the checklist)" "-" "${2:-}" FAIL; return 0; }
PROOF_DIR="${PROOF_DIR:-}"
PROOF_FILE=""
proof_to() { # proof_to ENG-NN: the file the next checks' full output goes into
  [ -z "$PROOF_DIR" ] && return 0
  mkdir -p "$PROOF_DIR"; PROOF_FILE="$PROOF_DIR/$1.md"
  [ -f "$PROOF_FILE" ] && return 0
  {
    echo "# $1: check output"
    echo
    $PY - "$1" <<'EOF'
import sys
from pathlib import Path
item = sys.argv[1]
for line in Path("Tracing/pack_text/SOCO-REC_Wave1A_Build_List_App_DB_Engine_v1_3.xlsx.txt").read_text(encoding="utf-8").splitlines():
    cells = line.split(" | ")
    if cells[0] == item and len(cells) > 10:
        print(f"**Task:** {cells[5]}  ")
        print(f"**Build List v1.3, How to check it is done:** {cells[-2]}")
        break
EOF
    echo
    echo "- **Run:** $(date '+%Y-%m-%d %H:%M %Z') on $(hostname) ($(uname -s)), environment ${ENGINE_ENV:-dev}"
    echo "- **Code:** branch $(git branch --show-current), commit $(git rev-parse --short HEAD)"
    echo "- **Command:** PROOF_DIR=\"$PROOF_DIR\" bash scripts/run_checklist.sh. Each section below is one check: the command it ran, the full output, and the exit code."
    echo
  } >"$PROOF_FILE"
}
proof() { # proof "label" "command" exit-code "output" PASS|FAIL
  [ -z "$PROOF_FILE" ] && return 0
  { echo "## $5  $1"; echo; echo '~~~~'; echo "\$ $2"; echo "$4"; echo "(exit code $3)"; echo '~~~~'; echo; } >>"$PROOF_FILE"
}
check() { # check "label" "command" ["text the output must contain"]
  local out
  out=$(eval "$2" 2>&1); local code=$?
  if [ $code -eq 0 ] && { [ -z "${3:-}" ] || grep -qF -- "$3" <<<"$out"; }; then pass "$1"; proof "$1" "$2" "$code" "$out" PASS
  else fail "$1" "$(tail -2 <<<"$out" | tr '\n' ' ' | cut -c1-160)"; proof "$1" "$2" "$code" "$out" FAIL; fi
}
wait_for() { # wait_for "command" seconds
  local i; for ((i = 0; i < $2; i++)); do eval "$1" >/dev/null 2>&1 && return 0; sleep 1; done; return 1
}
cleanup() {
  for port in 8190 8191 8192 8197; do stop $port; done
  $PY - <<'EOF' >/dev/null 2>&1
import asyncio
from pymongo import AsyncMongoClient
from reco.config import get_settings
async def main():
    c = AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database("reco_demo"); await c.close()
asyncio.run(main())
EOF
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "== 0. Before you start"
git fetch -q origin 2>/dev/null
if [ -z "$(git status --porcelain)" ]; then pass "0.1 working tree clean"; else fail "0.1 working tree clean" "uncommitted changes: commit or stash before a demo"; fi
if [ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}' 2>/dev/null)" ]; then pass "0.2 branch in step with GitHub"; else fail "0.2 branch in step with GitHub" "push or pull"; fi
check "0.3 unit tests pass" "$PY -m pytest -q -m 'not mongo' -p no:cacheprovider" " passed"
check "0.4 database tests pass (Atlas awake)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q -m mongo -p no:cacheprovider" " passed"

echo "== 1. ENG-01: the engine's home and databases"
proof_to ENG-01
check "1.1 environment, own database, 16 collections" "$PY scripts/setup_engine_db.py" "16 of 16 collections present"
check "1.2 platform login is read-only" "$PY scripts/check_platform_access.py" "NONE (read-only)"
check "1.3 safety lock refuses engine = platform" "$PY -c \"
from reco.config import Settings
try:
    Settings(app_mongo_uri='mongodb+srv://reader@cluster0.example.net/', app_mongo_db='soco', ml_mongo_uri='mongodb+srv://writer@cluster0.example.net/', ml_mongo_db='soco')
except Exception as e:
    print(e)
\"" "AS-09"
check "1.4 .env is ignored by git" "git check-ignore -q .env && echo ignored" "ignored"
check "1.5 no connection string with a password in tracked files" "! git grep -qE \"mongodb(\\+srv)?://[^@ \\\"']+:[^@ \\\"']+@\" -- . ':!tests' && echo none" "none"
check "1.6 production refuses a .env file" "$PY -c \"
from reco.config import _require_production_env_from_server as check
try:
    check('production', server_engine_env='')
except RuntimeError as e:
    print(e)
\"" "SD-08"

echo "== 2. ENG-02: skeleton, health, logs, live settings (throwaway reco_demo)"
proof_to ENG-02
check "2.1 twelve modules; gatekeepers hold" "$PY -m pytest -q tests/test_module_layout.py -p no:cacheprovider" "16 passed"
check "2.2 jobs mode" "$PY -m reco.jobs --list" "interest"
cp settings/engine.toml "$SETTINGS_COPY"
SETTINGS_FILE="$SETTINGS_COPY" ML_MONGO_DB=reco_demo $PY -m uvicorn reco.main:app --port 8190 >"$LOG" 2>&1 &
started 8190; disown
if wait_for "curl -sf http://127.0.0.1:8190/health" 60; then
  check "2.3 health 200 with both databases up" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8190/health" "HTTP200"
else fail "2.3 health 200 with both databases up" "engine did not start: $(tail -1 "$LOG")"; fi
ML_MONGO_URI="mongodb://127.0.0.1:1" MONGO_TIMEOUT_SECONDS=1 SETTINGS_FILE="$SETTINGS_COPY" \
  $PY -m uvicorn reco.main:app --port 8191 >"$WORK/down.log" 2>&1 &
started 8191; disown
if wait_for "curl -s -o /dev/null http://127.0.0.1:8191/health" 60; then
  check "2.4 health 503 with the engine database down" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8191/health" "HTTP503"
else fail "2.4 health 503 with the engine database down" "second engine did not start"; fi
stop 8191
APP_MONGO_URI="mongodb://127.0.0.1:1" MONGO_TIMEOUT_SECONDS=1 SETTINGS_FILE="$SETTINGS_COPY" ML_MONGO_DB=reco_demo \
  $PY -m uvicorn reco.main:app --port 8197 >"$WORK/down2.log" 2>&1 &
started 8197; disown
if wait_for "curl -s -o /dev/null http://127.0.0.1:8197/health" 60; then
  check "2.4b health 503 with the platform database down" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8197/health" "HTTP503"
else fail "2.4b health 503 with the platform database down" "engine did not start"; fi
stop 8197
check "2.5 every request is logged" "grep '\"logger\": \"reco.request\"' '$LOG'" "\"status\": 200"
V=$(sed -n 's/^config_version = "\([0-9]*\)"/\1/p' "$SETTINGS_COPY"); NEXT=$((V + 1))
sedi "s/config_version = \"$V\"/config_version = \"$NEXT\"/; s/changed_by = \"Allen\"/changed_by = \"Checklist\"/; s/popularity_window_days = 30 /popularity_window_days = 45 /" "$SETTINGS_COPY"
if wait_for "grep -q '\"settings changed\".*\"config_version\": \"$NEXT\"' '$LOG'" 60; then pass "2.6 setting change in force within a minute, logged"
  proof "2.6 setting change in force within a minute, logged" "wait for the engine log line 'settings changed' with config_version $NEXT" 0 "$(grep '"settings changed"' "$LOG" | tail -2)" PASS
else fail "2.6 setting change in force within a minute, logged"; fi
check "2.7 change diary shows who changed what" "ML_MONGO_DB=reco_demo $PY scripts/show_config_changes.py" "interest.popularity_window_days: 30 -> 45"
cp "$SETTINGS_COPY" "$WORK/good.toml"
{ echo 'this is = not [valid'; cat "$WORK/good.toml"; } >"$SETTINGS_COPY"
if wait_for "grep -q 'settings file rejected' '$LOG'" 60; then
  check "2.8 broken file rejected; still serving" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8190/health" "HTTP200"
else fail "2.8 broken file rejected; still serving"; fi
sed 's/pool_size = 300 /pool_size = 250 /' "$WORK/good.toml" >"$SETTINGS_COPY"
if wait_for "grep -q 'raise config_version' '$LOG'" 60; then pass "2.9 change without a new version refused"
  proof "2.9 change without a new version refused" "wait for the engine log line refusing a change without a new config_version" 0 "$(grep 'raise config_version' "$LOG" | tail -2)" PASS
else fail "2.9 change without a new version refused"; fi
stop 8190

echo "== 3. ENG-03: reading SOCO's data correctly"
proof_to ENG-03
check "3.1 one of each record type (the ENG-03 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider" " passed"
check "3.2 the four cases the ENG-03 check names" "$PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider -k 'follow_with_text_ids or businessregister_actor or product_post_on_a_platform_feed or history_and_a_return'" "4 passed"
check "3.3 one source per kind; no event source switch" "$PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider -k 'source'" " passed"
check "3.4 ignored platform data is never read" "$PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider -k ignored" "3 passed"
check "3.5 every real platform document reads cleanly" "$PY scripts/check_platform_records.py" "PASS: 0 document(s) could not be read"

echo "== 4. ENG-04: the engine sync"
proof_to ENG-04
T="$PY -m pytest -q tests/test_sync.py -p no:cacheprovider"
check "4.1 copies keep source, ids, undo fields, E code; order history" "$T -k 'copy or e1 or history or four_sources'" "7 passed"
check "4.2 backfill keyed on the platform _id, restartable" "TEST_MONGO_TIMEOUT_MS=15000 $T -k backfill" "2 passed"
check "4.3 (a) reconciliation: ids and field values, mismatches re-read" "TEST_MONGO_TIMEOUT_MS=15000 $T -k reconciliation" "3 passed"
check "4.4 (b) a like undone after copying updates the copy" "TEST_MONGO_TIMEOUT_MS=15000 $T -k undo" "1 passed"
check "4.5 (c) an hour stopped: nothing lost, nothing doubled" "TEST_MONGO_TIMEOUT_MS=15000 $T -k hour_stopped" "1 passed"
check "4.6 (d) same updated_at across a page boundary" "TEST_MONGO_TIMEOUT_MS=15000 $T -k page_boundary" "1 passed"
check "4.7 (e) a failure before the checkpoint re-reads the batch" "TEST_MONGO_TIMEOUT_MS=15000 $T -k failure_before" "1 passed"
check "4.8 (f) the alert fires: behind, and a failed run" "TEST_MONGO_TIMEOUT_MS=15000 $T -k alert_fires" "2 passed"
check "4.9 (g) retention: 365 days on the original time" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_sync.py tests/test_engine_environment.py -p no:cacheprovider -k retention" " passed"
check "4.10 real backfill from SOCO into reco_demo" "ML_MONGO_DB=reco_demo $PY -m reco.jobs sync && ML_MONGO_DB=reco_demo $PY scripts/show_events.py | grep -c 'backfill done'" "4"
check "4.11 real reconciliation of yesterday passes" "ML_MONGO_DB=reco_demo $PY -m reco.jobs reconcile_sync" '"passed": true'

echo "== 5. ENG-05: the same method for each user"
proof_to ENG-05
T="$PY -m pytest -q tests/test_assignment.py -p no:cacheprovider"
check "5.1 same method across two restarts" "$T -k restarts" "1 passed"
check "5.2 changing a split moves users with no deploy" "$T -k no_deploy" "1 passed"
check "5.3 10,000 ids: each split within 2 points" "$T -k ten_thousand" "4 passed"
check "5.4 missing settings or user_id: everyone gets the default, logged" "$T -k 'missing or left_out'" "3 passed"
check "5.5 the real settings file splits within 2 points" "$PY scripts/show_assignment.py | grep -c 'within 2 points'" "3"

echo "== 6. ENG-06: serve a list and record it (throwaway reco_demo, port 8192)"
proof_to ENG-06
check "6.1 contract: 401, 400s, 503 off/internal, database fault, response shape" "$PY -m pytest -q tests/test_recommendations.py -p no:cacheprovider -m 'not mongo'" "26 passed"
check "6.2 constructed data: eligible newest first; record matches the response" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_recommendations.py -p no:cacheprovider -m mongo" "2 passed"
sed 's/^surface_mode_feed = "off"/surface_mode_feed = "live"/; s/^surface_mode_product = "off"/surface_mode_product = "live"/' settings/engine.toml >"$WORK/serve.toml"
SERVE_TOKEN="checklist-$RANDOM$RANDOM"
INGEST_TOKEN="$SERVE_TOKEN" SETTINGS_FILE="$WORK/serve.toml" ML_MONGO_DB=reco_demo $PY -m uvicorn reco.main:app --port 8192 >"$WORK/serve.log" 2>&1 &
started 8192; disown
if wait_for "curl -sf http://127.0.0.1:8192/health" 60; then
  check "6.3 feed over HTTP: p95 within 200 ms; every record matches" "INGEST_TOKEN=$SERVE_TOKEN ML_MONGO_DB=reco_demo $PY scripts/try_recommendations.py http://127.0.0.1:8192 feed" "19 of 19"
  check "6.4 product over HTTP: p95 within 200 ms; every record matches" "INGEST_TOKEN=$SERVE_TOKEN ML_MONGO_DB=reco_demo $PY scripts/try_recommendations.py http://127.0.0.1:8192 product" "19 of 19"
  check "6.5 a wrong token is 401" "curl -s -X POST http://127.0.0.1:8192/v1/recommendations -H 'Authorization: Bearer wrong' -d '{}' -w ' HTTP%{http_code}'" "HTTP401"
  V=$(sed -n 's/^config_version = "\([0-9]*\)"/\1/p' "$WORK/serve.toml"); NEXT=$((V + 1))
  sedi "s/config_version = \"$V\"/config_version = \"$NEXT\"/; s/^surface_mode_feed = \"live\"/surface_mode_feed = \"off\"/" "$WORK/serve.toml"
  if wait_for "grep -q '\"settings changed\".*\"config_version\": \"$NEXT\"' '$WORK/serve.log'" 60; then
    check "6.6 feed set to off (no restart): 503" "curl -s -X POST http://127.0.0.1:8192/v1/recommendations -H 'Authorization: Bearer $SERVE_TOKEN' -d '{\"user_id\":\"64f1c0ffee0000000000abcd\",\"surface\":\"feed\",\"page\":1,\"limit\":5,\"session_id\":\"ses_1\"}' -w ' HTTP%{http_code}'" "HTTP503"
  else fail "6.6 feed set to off (no restart): 503" "the settings change was not picked up"; fi
else fail "6.3 engine with live surfaces started" "$(tail -1 "$WORK/serve.log")"; fi
stop 8192

echo "== 7. ENG-07: daily refresh jobs (throwaway reco_demo)"
proof_to ENG-07
T="$PY -m pytest -q tests/test_nightly.py -p no:cacheprovider"
check "7.1 the scheduler runs at the set time (2 AM IST), reconciliation last; one failed job doesn't stop the rest" "$T -k '2am or does_not_stop or run_time'" "5 passed"
check "7.2 a batch is read only once complete; rows carry provenance" "TEST_MONGO_TIMEOUT_MS=15000 $T -k 'current or provenance or replaces'" "3 passed"
check "7.3 a failure halfway keeps the previous batch" "TEST_MONGO_TIMEOUT_MS=15000 $T -k halfway" "1 passed"
check "7.4 a killed run is recorded as failed and never read" "TEST_MONGO_TIMEOUT_MS=15000 $T -k killed" "1 passed"
check "7.5 a real kill halfway: previous batch still read" "out=\$(ML_MONGO_DB=reco_demo $PY scripts/demo_kill_job.py 2>/dev/null); grep -A1 '3. straight' <<<\"\$out\" | grep -q 'DEMO-U1=fashion' && grep -q abandoned <<<\"\$out\" && echo kill-check-ok" "kill-check-ok"
check "7.6 the real nightly run: both methods and the popularity batch current" "ML_MONGO_DB=reco_demo $PY -m reco.jobs nightly && ML_MONGO_DB=reco_demo $PY scripts/show_job_runs.py | grep -c CURRENT" "3"

echo "== 8. ENG-29: adapting to the platform as built"
proof_to ENG-29
T="TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_platform_dataset.py -p no:cacheprovider"
check "8.1 the constructed test data covers every platform collection and reads" "$T -k every_constructed" "1 passed"
check "8.2 an unmapped category is reported, and left out until mapped" "$T -k unmapped" "2 passed"
check "8.3 test-account and exemption lists (expiry, logged); a test account is left out of scoring" "$T -k 'test_account or account_lists or list_change'" "3 passed"
check "8.4 an order's history from tracking_info: delivery, return request, who cancelled" "$T -k 'tracking or first_delivery or cancellation'" "4 passed"
check "8.5 a product post on a feed list keeps post_id and product_id apart" "$T -k apart" "1 passed"
check "8.6 rec_serve_log rows are read and copied" "$T -k serve_log" "2 passed"
check "8.7 status spellings from the settings" "$T -k spellings" "1 passed"
check "8.8 the real daily category check runs on SOCO's data" "ML_MONGO_DB=reco_demo $PY -m reco.jobs category_check" '"outcome": "succeeded"'
check "8.9 the engine test environment holds the constructed data" "$PY scripts/seed_test_platform.py soco_engine_test" "all parse"

echo "== 9. ENG-08: eligibility filters E-01 to E-12"
proof_to ENG-08
T="TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_eligibility.py -p no:cacheprovider"
check "9.1 each rule E-01 to E-12: one item excluded, one kept (the ENG-08 check)" "$T -m 'not mongo' -k 'test_e0 or test_e1'" "12 passed"
check "9.2 the viewer's follows, blocks and feedback are read when the list is built" "$T -k viewer_context" "1 passed"
check "9.3 every exclusion is logged with request_id, item_id and rule" "$T -k logged" "1 passed"
check "9.4 an item failing the final recheck is replaced by the next eligible one" "$T -k recheck" "1 passed"
check "9.5 the rules run on SOCO's real data" "$PY scripts/show_exclusions.py" "left out, by rule"

echo "== 10. ENG-09: the fallback ladder"
proof_to ENG-09
check "10.1 each rung is reported on the response and the record (the ENG-09 check)" "$PY -m pytest -q tests/test_recommendations.py -p no:cacheprovider -k each_rung" "8 passed"
check "10.2 one test user per rung; first match wins; 4 and 5 fall to 3; rung 3 empty" "$PY -m pytest -q tests/test_read_path.py -p no:cacheprovider" "20 passed"
check "10.3 on a database: the 5 qualified actions, the nightly popularity, one user per rung" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_ladder_store.py -p no:cacheprovider" "4 passed"
check "10.4 the ladder walks SOCO's real users (reads only)" "$PY scripts/show_ladder.py" "users by step"

echo "== 11. ENG-10 and ENG-11: M1 on the engine's copies, and its check script"
proof_to ENG-10
check "11.1 each action read from one place: weights, undo, reversal, one view per post, categories" "$PY -m pytest -q tests/test_m1_copies.py -p no:cacheprovider" "15 passed"
proof_to ENG-11
check "11.2 the M1 check script: all 11 checks on the constructed users (the ENG-10 and ENG-11 check)" "$PY scripts/check_m1.py" "Result: 11 of 11 passed"
proof_to ENG-10
check "11.3 M1 runs on SOCO's real data from the copies (into reco_demo)" "ML_MONGO_DB=reco_demo $PY -m reco.jobs interest" '"outcome": "succeeded"'

cleanup
trap - EXIT
if $PY -c "
import asyncio
from pymongo import AsyncMongoClient
from reco.config import get_settings
async def m():
    c = AsyncMongoClient(get_settings().ml_mongo_uri); gone = 'reco_demo' not in await c.list_database_names(); await c.close(); raise SystemExit(0 if gone else 1)
asyncio.run(m())" && ! any_running; then pass "Z.1 clean up: reco_demo dropped, no engine left running"
else fail "Z.1 clean up: reco_demo dropped, no engine left running"; fi

echo
echo "== Result: $PASSES passed, $FAILS failed"
for item in "${FAILED[@]+"${FAILED[@]}"}"; do echo "   failed: $item"; done
echo
echo "Not checkable yet (need Aravinth): test/production servers and clusters,"
echo "production's read-only login (DB-02), private network (DB-12)."
echo "Data to fix: product categories not in the 23 (DB-07), contentfeedbacks missing,"
echo "cart request_id (DB-05)."
[ "$FAILS" -eq 0 ]
