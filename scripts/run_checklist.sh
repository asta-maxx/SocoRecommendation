#!/usr/bin/env bash
# The checklist, run end to end: every check for ENG-01 to ENG-12 and ENG-29.
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
export RECO_STATE_DIR="$WORK/state"   # the checklist's engines keep their settings state here, never in the service's folder
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
build_list = sorted(Path("Tracing/pack_text").glob("SOCO-REC_Wave1A_Build_List_*.txt"))[-1]  # the current pack
print(f"**Pack:** {build_list.name.removesuffix('.txt')}  ")
for line in build_list.read_text(encoding="utf-8").splitlines():
    cells = line.split(" | ")
    if cells[0] == item and len(cells) > 10:
        print(f"**Task:** {cells[5]}  ")
        print(f"**How to check it is done:** {cells[-2]}")
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
check "1.1 environment, own database, 17 collections (16, and ml_return_requests from ENG-30)" "$PY scripts/setup_engine_db.py" "17 of 17 collections present"
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
  check "2.8 broken file rejected; still serving" "grep 'settings file rejected' '$LOG' | tail -1; curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8190/health" "HTTP200"
else fail "2.8 broken file rejected; still serving"; fi
sed 's/pool_size = 300 /pool_size = 250 /' "$WORK/good.toml" >"$SETTINGS_COPY"
if wait_for "grep -q 'raise config_version' '$LOG'" 60; then pass "2.9 change without a new version refused"
  proof "2.9 change without a new version refused" "wait for the engine log line refusing a change without a new config_version" 0 "$(grep 'raise config_version' "$LOG" | tail -2)" PASS
else fail "2.9 change without a new version refused"; fi
# 2.10 (Kala F5): going back to the earlier version is put in force AND written in the diary as a rollback.
cp "$WORK/good.toml" "$WORK/before.toml"
sedi "s/config_version = \"$NEXT\"/config_version = \"$V\"/; s/popularity_window_days = 45 /popularity_window_days = 30 /" "$SETTINGS_COPY"
sed 's/pool_size = 250 /pool_size = 300 /' "$SETTINGS_COPY" > "$WORK/rollback.toml" && cp "$WORK/rollback.toml" "$SETTINGS_COPY"
if wait_for "grep -q '\"settings changed\".*\"config_version\": \"$V\".*\"previous_version\": \"$NEXT\"' '$LOG'" 60; then
  check "2.10 a rollback to the earlier version is recorded in the diary (Kala F5)" "ML_MONGO_DB=reco_demo $PY scripts/show_config_changes.py" "ROLLBACK"
else fail "2.10 a rollback to the earlier version is recorded in the diary (Kala F5)" "the rollback was not picked up"; fi
check "2.11 a dated change is written to the diary; the rule and its exception with the database down; restart and redeploy (no database)" "$PY -m pytest -q tests/test_settings_diary.py -p no:cacheprovider -m 'not mongo'" "18 passed"
check "2.12 the rule and its exception on a real engine database (throwaway reco_diary_check): not written, not applied, alerted; feed off at once; restart and redeploy with the database down keep it off; written once; back on only after its entry" "$PY scripts/demo_settings_diary.py" "13 of 13 passed"
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
check "4.1 copies keep source, ids, undo fields, E code; order history" "$T -k 'copy or e1 or history or four_sources'" "8 passed"
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
check "6.1 contract: 401, 400s, 503 off/internal, database fault, response shape" "$PY -m pytest -q tests/test_recommendations.py -p no:cacheprovider -m 'not mongo'" "27 passed"
# Review of 26 Oct, point 1: the limits this run uses, written into the proof.
check "6.0 the time limits this run uses (test-only REQUEST_BUDGET_MS / SOURCE_TIME_LIMIT_MS when set; refused in production)" "$PY scripts/show_limits.py" "environment"
check "6.2 constructed data: eligible newest first; record matches the response" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_recommendations.py -p no:cacheprovider -m mongo" "2 passed"
# The serving copy turns both surfaces on, so it is a change: it needs a new config_version, or the
# engine (rightly) keeps the version already recorded in reco_demo by the jobs (2.9's rule).
SV=$(sed -n 's/^config_version = "\([0-9]*\)"/\1/p' settings/engine.toml)
sed "s/^surface_mode_feed = \"off\"/surface_mode_feed = \"live\"/; s/^surface_mode_product = \"off\"/surface_mode_product = \"live\"/; s/^config_version = \"$SV\"/config_version = \"$((SV + 50))\"/" settings/engine.toml >"$WORK/serve.toml"
SERVE_TOKEN="checklist-$RANDOM$RANDOM"
INGEST_TOKEN="$SERVE_TOKEN" SETTINGS_FILE="$WORK/serve.toml" ML_MONGO_DB=reco_demo $PY -m uvicorn reco.main:app --port 8192 >"$WORK/serve.log" 2>&1 &
started 8192; disown
if wait_for "curl -sf http://127.0.0.1:8192/health" 60; then
  check "6.3 feed over HTTP: every record matches (one each: request_id, items in order, methods, fallback rung); p95 within 200 ms, judged only without test-only limits" "INGEST_TOKEN=$SERVE_TOKEN ML_MONGO_DB=reco_demo $PY scripts/try_recommendations.py http://127.0.0.1:8192 feed" "19 of 19"
  check "6.4 product over HTTP: every record matches (one each: request_id, items in order, methods, fallback rung); p95 within 200 ms, judged only without test-only limits" "INGEST_TOKEN=$SERVE_TOKEN ML_MONGO_DB=reco_demo $PY scripts/try_recommendations.py http://127.0.0.1:8192 product" "19 of 19"
  check "6.5 a wrong token is 401" "curl -s -X POST http://127.0.0.1:8192/v1/recommendations -H 'Authorization: Bearer wrong' -d '{}' -w ' HTTP%{http_code}'" "HTTP401"
  V=$(sed -n 's/^config_version = "\([0-9]*\)"/\1/p' "$WORK/serve.toml"); NEXT=$((V + 1))
  sedi "s/config_version = \"$V\"/config_version = \"$NEXT\"/; s/^surface_mode_feed = \"live\"/surface_mode_feed = \"off\"/" "$WORK/serve.toml"
  if wait_for "grep -q '\"settings changed\".*\"config_version\": \"$NEXT\"' '$WORK/serve.log'" 60; then
    check "6.6 feed set to off (no restart): 503" "curl -s -X POST http://127.0.0.1:8192/v1/recommendations -H 'Authorization: Bearer $SERVE_TOKEN' -d '{\"user_id\":\"64f1c0ffee0000000000abcd\",\"surface\":\"feed\",\"page\":1,\"limit\":5,\"session_id\":\"ses_1\"}' -w ' HTTP%{http_code}'" "HTTP503"
  else fail "6.6 feed set to off (no restart): 503" "the settings change was not picked up"; fi
  # Put back what 6.3 to 6.6 changed: the real file (config_version $SV, both surfaces off), recorded here, not by section 7's jobs.
  cp settings/engine.toml "$WORK/serve.toml"
  if wait_for "grep -q '\"settings changed\".*\"config_version\": \"$SV\".*\"previous_version\": \"$NEXT\"' '$WORK/serve.log'" 60; then
    check "6.7 the settings 6.3 to 6.6 changed are put back: the real file is in force and in the diary" "ML_MONGO_DB=reco_demo SETTINGS_FILE=settings/engine.toml $PY scripts/show_settings_in_force.py" "in step with the file: yes"
  else fail "6.7 the settings 6.3 to 6.6 changed are put back" "the engine did not pick up the real file"; fi
else fail "6.3 engine with live surfaces started" "$(tail -1 "$WORK/serve.log")"; fi
stop 8192

echo "== 7. ENG-07: daily refresh jobs (throwaway reco_demo)"
proof_to ENG-07
T="$PY -m pytest -q tests/test_nightly.py -p no:cacheprovider"
check "7.1 the scheduler runs at the set time (2 AM IST), reconciliation last; one failed job doesn't stop the rest" "$T -k '2am or does_not_stop or run_time'" "5 passed"
check "7.2 a batch is read only once complete; rows carry provenance" "TEST_MONGO_TIMEOUT_MS=15000 $T -k 'current or provenance or replaces'" "3 passed"
check "7.3 a failure halfway keeps the previous batch" "TEST_MONGO_TIMEOUT_MS=15000 $T -k halfway" "1 passed"
check "7.4 a killed run is recorded as failed and never read" "TEST_MONGO_TIMEOUT_MS=15000 $T -k killed" "1 passed"
check "7.5 a real kill halfway: previous batch still read" "out=\$(ML_MONGO_DB=reco_demo $PY scripts/demo_kill_job.py 2>&1); echo \"\$out\"; grep -A1 '3. straight' <<<\"\$out\" | grep -q 'DEMO-U1=fashion' && grep -q abandoned <<<\"\$out\" && echo kill-check-ok" "kill-check-ok"
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
# Its own database name: on the test server soco_engine_test is the engine's database, which the seed rightly refuses.
check "8.9 the engine test environment holds the constructed data" "$PY scripts/seed_test_platform.py soco_platform_test" "all parse"

echo "== 9. ENG-08: eligibility filters E-01 to E-12"
proof_to ENG-08
T="TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_eligibility.py -p no:cacheprovider"
check "9.1 each rule E-01 to E-12: one item excluded, one kept (the ENG-08 check)" "$T -m 'not mongo' -k '(test_e0 or test_e1) and not serves_every_other'" "12 passed"
check "9.6 E-12 still serves ok, review, fix_requested and no compliance record (ENG-30 point 11)" "$T -m 'not mongo' -k serves_every_other" "4 passed"
check "9.2 the viewer's follows, blocks and feedback are read when the list is built" "$T -k viewer_context" "1 passed"
check "9.3 every exclusion is logged with request_id, item_id and rule" "$T -k logged" "1 passed"
check "9.4 an item failing the final recheck is replaced by the next eligible one" "$T -k recheck" "1 passed"
check "9.5 the rules run on SOCO's real data" "$PY scripts/show_exclusions.py" "left out, by rule"

echo "== 10. ENG-09: the fallback ladder"
proof_to ENG-09
check "10.1 each rung is reported on the response and the record (the ENG-09 check)" "$PY -m pytest -q tests/test_recommendations.py -p no:cacheprovider -k each_rung" "8 passed"
check "10.2 one test user per rung; first match wins; 4 falls to 3; 5 with no old score is an error; rung 3 empty" "$PY -m pytest -q tests/test_read_path.py -p no:cacheprovider" "21 passed"
check "10.3 on a database: the 5 qualified actions, the nightly popularity, one user per rung" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_ladder_store.py -p no:cacheprovider" "4 passed"
check "10.4 the ladder walks SOCO's real users (reads only)" "$PY scripts/show_ladder.py" "users by step"

echo "== 11. ENG-10 and ENG-11: M1 on the engine's copies, and its check script"
proof_to ENG-10
check "11.1 each action read from one place: weights, undo, reversal, open return request, seed posts, Kala's count" "$PY -m pytest -q tests/test_m1_copies.py -p no:cacheprovider" "20 passed"
proof_to ENG-11
check "11.2 the M1 check script: 18 checks on the constructed users (ENG-11's 11, ENG-29's 2, pack v1.4's 3, Kala's 2)" "$PY scripts/check_m1.py" "Result: 18 of 18 passed"
proof_to ENG-10
check "11.3 M1 runs on SOCO's real data from the copies (into reco_demo)" "ML_MONGO_DB=reco_demo $PY -m reco.jobs interest" '"outcome": "succeeded"'

echo "== 12. ENG-12: candidate sources"
proof_to ENG-12
check "12.1 each source's rule; a source over its limit is dropped and logged (the ENG-12 check, without the timing)" "$PY -m pytest -q tests/test_sources.py -p no:cacheprovider -m 'not mongo'" "9 passed"
check "12.2 on a database: the post index (recent, no seed posts, no test-account views) and every source reading it" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_sources.py -p no:cacheprovider -m mongo" "1 passed"
check "12.3 the post index builds from SOCO's real posts (into reco_demo)" "ML_MONGO_DB=reco_demo $PY -m reco.jobs post_index" '"outcome": "succeeded"'
proof_to ENG-14
check "12.4 ENG-14 vectors, post type, pool rules, profile, cosine top 200 (no database)" "$PY -m pytest -q tests/test_similar.py -p no:cacheprovider -m 'not mongo'" "35 passed"
check "12.5 ENG-14 the job writes a current batch; one list reads within 20 ms beyond the network (the ENG-14 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_similar.py -p no:cacheprovider -m mongo" "1 passed"
check "12.6 ENG-14 similar posts runs on SOCO's real data (into reco_demo)" "ML_MONGO_DB=reco_demo $PY -m reco.jobs similar_posts" '"outcome": "succeeded"'

echo "== 13. ENG-13: quotas (the pool of 300), and ENG-30 point 3 (reposts)"
proof_to ENG-13
check "13.1 quotas, round-robin, short sources, duplicates, reposts as originals, filters before and after; repost chains (no database)" "$PY -m pytest -q tests/test_quotas.py -p no:cacheprovider -m 'not mongo'" "23 passed"
check "13.2 on a database: 300 or fewer, quotas within 1, no duplicates; blocked author out before, hidden original out after (the ENG-13 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_quotas.py -p no:cacheprovider -m mongo" "1 passed"

echo "== 14. ENG-15: merge into the shortlist"
proof_to ENG-15
check "14.1 percentiles within each source, both methods in proportion, duplicates keep the higher percentile and both tags, cut by order, pool sizes logged (no database)" "$PY -m pytest -q tests/test_merge.py -p no:cacheprovider -m 'not mongo'" "17 passed"
check "14.2 on a database: 200 or fewer, no duplicates, method two filtered (the ENG-15 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_merge.py -p no:cacheprovider -m mongo" "1 passed"

echo "== 15. ENG-16: M8 promoter score, and ENG-30 points 1, 2 and 8"
proof_to ENG-16
check "15.1 one person, the promoter fallback, the return window, completed sales, components, both methods, trust (no database)" "$PY -m pytest -q tests/test_promoter.py -p no:cacheprovider -m 'not mongo'" "16 passed"
check "15.2 on a database: both methods with confidence; repost sale to the original; own-store buy for nobody; open request then completed; returned; reposts only not scored; a confirmed case halves (the ENG-16 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_promoter.py -p no:cacheprovider -m mongo" "1 passed"
check "15.3 M8 scores SOCO's real promoters, both methods (into reco_demo; skipped would mean the return-request copy is not current)" "ML_MONGO_DB=reco_demo $PY -m reco.jobs promoter" '"batches"'

echo "== 16. ENG-17: M5 product ranker, both methods"
proof_to ENG-17
check "16.1 method one's components and rescaling; hand-computed lift for three pairs; at least 2 co-purchases; intent label; the fallback order and its step; context and cart never appear; exactly limit (no database)" "$PY -m pytest -q tests/test_product_ranker.py -p no:cacheprovider -m 'not mongo'" "27 passed"
check "16.2 on a database: both batches current; lift by hand; both methods serve through the request path; cart and context left out; stale batch falls back; checkout baskets labelled checkout (the ENG-17 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_product_ranker.py -p no:cacheprovider -m mongo" "1 passed"
check "16.3 M5 lists SOCO's real products, both methods (into reco_demo)" "ML_MONGO_DB=reco_demo $PY -m reco.jobs product_ranking" '"batches"'
check "16.4 both methods serve: one product request for a user assigned each method, through the request path (ENG-17's check, on the environment it runs in)" "ML_MONGO_DB=reco_demo $PY scripts/try_product_methods.py" "both methods served: yes"

echo "== 17. ENG-19: the feed ranking"
proof_to ENG-19
check "17.1 the formula by hand, Kala's ladder for authors with no score, variety and its relaxation order, the shuffle fix, paging (no database)" "$PY -m pytest -q tests/test_feed_ranking.py -p no:cacheprovider -m 'not mongo'" "16 passed"
check "17.2 on a database: the order follows the formula, variety rules hold, a product's commission changes nothing, page 2 leaves out page 1 (the ENG-19 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_feed_ranking.py -p no:cacheprovider -m mongo" "1 passed"

echo "== 18. ENG-30: commission settings (point 4) and the daily report of unmatched history texts (point 5)"
proof_to ENG-30
check "18.1 store disabled and product 15 merge; a missing field falls through; poolPercent 60 ignored and logged; a duplicate scope resolves to the later row; unreadable means M6 does not run; unmatched history texts reported daily (no database)" "$PY -m pytest -q tests/test_commission.py -p no:cacheprovider -m 'not mongo'" "17 passed"
check "18.2 on a database: commissionconfigs read in full, only the fields used, and merged" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_commission.py -p no:cacheprovider -m mongo" "1 passed"

echo "== Z. The settings in force at the end"
proof_to ENG-02
check "Z.0 the settings in force at the end are the real file's (config_version, both surface modes); the real file is unchanged" "git diff --exit-code --stat settings/engine.toml && ML_MONGO_DB=reco_demo SETTINGS_FILE=settings/engine.toml $PY scripts/show_settings_in_force.py" "in step with the file: yes"

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
