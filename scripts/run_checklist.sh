#!/usr/bin/env bash
# The Step 1 checklist, run end to end: every check for ENG-01 to ENG-04 (pack v1.3).
#
#     bash scripts/run_checklist.sh
#
# Prints PASS or FAIL per item and a summary; exits 0 only if everything passes.
# Anything that writes uses a throwaway settings copy and the throwaway database
# reco_demo, which is dropped at the end. Ports 8190/8191 are used so a demo
# running on 8100/8101 is not disturbed. Nothing secret is printed.

set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
WORK=$(mktemp -d /tmp/soco-checklist.XXXXXX)
SETTINGS_COPY="$WORK/engine.toml"
LOG="$WORK/engine.log"
PASSES=0
FAILS=0
FAILED=()

pass() { PASSES=$((PASSES + 1)); printf "  PASS  %s\n" "$1"; }
fail() { FAILS=$((FAILS + 1)); FAILED+=("$1"); printf "  FAIL  %s\n" "$1"; [ -n "${2:-}" ] && printf "        %s\n" "$2"; }
check() { # check "label" "command" ["text the output must contain"]
  local out
  out=$(eval "$2" 2>&1); local code=$?
  if [ $code -eq 0 ] && { [ -z "${3:-}" ] || grep -qF -- "$3" <<<"$out"; }; then pass "$1"
  else fail "$1" "$(tail -2 <<<"$out" | tr '\n' ' ' | cut -c1-160)"; fi
}
wait_for() { # wait_for "command" seconds
  local i; for ((i = 0; i < $2; i++)); do eval "$1" >/dev/null 2>&1 && return 0; sleep 1; done; return 1
}
cleanup() {
  pkill -f "uvicorn reco.main:app --port 819" >/dev/null 2>&1
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
check "2.1 twelve modules; gatekeepers hold" "$PY -m pytest -q tests/test_module_layout.py -p no:cacheprovider" "16 passed"
check "2.2 jobs mode" "$PY -m reco.jobs --list" "interest"
cp settings/engine.toml "$SETTINGS_COPY"
SETTINGS_FILE="$SETTINGS_COPY" ML_MONGO_DB=reco_demo $PY -m uvicorn reco.main:app --port 8190 >"$LOG" 2>&1 &
disown
if wait_for "curl -sf http://127.0.0.1:8190/health" 60; then
  check "2.3 health 200 with both databases up" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8190/health" "HTTP200"
else fail "2.3 health 200 with both databases up" "engine did not start: $(tail -1 "$LOG")"; fi
ML_MONGO_URI="mongodb://127.0.0.1:1" MONGO_TIMEOUT_SECONDS=1 SETTINGS_FILE="$SETTINGS_COPY" \
  $PY -m uvicorn reco.main:app --port 8191 >"$WORK/down.log" 2>&1 &
disown
if wait_for "curl -s -o /dev/null http://127.0.0.1:8191/health" 60; then
  check "2.4 health 503 with the engine database down" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8191/health" "HTTP503"
else fail "2.4 health 503 with the engine database down" "second engine did not start"; fi
pkill -f "uvicorn reco.main:app --port 8191" >/dev/null 2>&1
check "2.5 every request is logged" "grep '\"logger\": \"reco.request\"' '$LOG'" "\"status\": 200"
V=$(sed -n 's/^config_version = "\([0-9]*\)"/\1/p' "$SETTINGS_COPY"); NEXT=$((V + 1))
sed -i '' "s/config_version = \"$V\"/config_version = \"$NEXT\"/; s/changed_by = \"Allen\"/changed_by = \"Checklist\"/; s/popularity_window_days = 30 /popularity_window_days = 45 /" "$SETTINGS_COPY"
if wait_for "grep -q '\"settings changed\".*\"config_version\": \"$NEXT\"' '$LOG'" 60; then pass "2.6 setting change in force within a minute, logged"
else fail "2.6 setting change in force within a minute, logged"; fi
check "2.7 change diary shows who changed what" "ML_MONGO_DB=reco_demo $PY scripts/show_config_changes.py" "interest.popularity_window_days: 30 -> 45"
cp "$SETTINGS_COPY" "$WORK/good.toml"
{ echo 'this is = not [valid'; cat "$WORK/good.toml"; } >"$SETTINGS_COPY"
if wait_for "grep -q 'settings file rejected' '$LOG'" 60; then
  check "2.8 broken file rejected; still serving" "curl -s -w ' HTTP%{http_code}' http://127.0.0.1:8190/health" "HTTP200"
else fail "2.8 broken file rejected; still serving"; fi
sed 's/pool_size = 300 /pool_size = 250 /' "$WORK/good.toml" >"$SETTINGS_COPY"
if wait_for "grep -q 'raise config_version' '$LOG'" 60; then pass "2.9 change without a new version refused"
else fail "2.9 change without a new version refused"; fi
pkill -f "uvicorn reco.main:app --port 8190" >/dev/null 2>&1

echo "== 3. ENG-03: reading SOCO's data correctly"
check "3.1 one of each record type (the ENG-03 check)" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider" " passed"
check "3.2 the four cases the ENG-03 check names" "$PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider -k 'follow_with_text_ids or businessregister_actor or product_post_on_a_platform_feed or history_and_a_return'" "4 passed"
check "3.3 one source per kind; no event source switch" "$PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider -k 'source'" " passed"
check "3.4 ignored platform data is never read" "$PY -m pytest -q tests/test_platform_records.py -p no:cacheprovider -k ignored" "3 passed"
check "3.5 every real platform document reads cleanly" "$PY scripts/check_platform_records.py" "PASS: 0 document(s) could not be read"

echo "== 4. ENG-04: the engine sync"
T="$PY -m pytest -q tests/test_sync.py -p no:cacheprovider"
check "4.1 copies keep source, ids, undo fields, E code; order history" "$T -k 'copy or e1 or history or three_sources'" "5 passed"
check "4.2 backfill keyed on the platform _id, restartable" "TEST_MONGO_TIMEOUT_MS=15000 $T -k backfill" "2 passed"
check "4.3 (a) reconciliation: ids and field values, mismatches re-read" "TEST_MONGO_TIMEOUT_MS=15000 $T -k reconciliation" "2 passed"
check "4.4 (b) a like undone after copying updates the copy" "TEST_MONGO_TIMEOUT_MS=15000 $T -k undo" "1 passed"
check "4.5 (c) an hour stopped: nothing lost, nothing doubled" "TEST_MONGO_TIMEOUT_MS=15000 $T -k hour_stopped" "1 passed"
check "4.6 (d) same updated_at across a page boundary" "TEST_MONGO_TIMEOUT_MS=15000 $T -k page_boundary" "1 passed"
check "4.7 (e) a failure before the checkpoint re-reads the batch" "TEST_MONGO_TIMEOUT_MS=15000 $T -k failure_before" "1 passed"
check "4.8 (f) the alert fires: behind, and a failed run" "TEST_MONGO_TIMEOUT_MS=15000 $T -k alert_fires" "2 passed"
check "4.9 (g) retention: 365 days on the original time" "TEST_MONGO_TIMEOUT_MS=15000 $PY -m pytest -q tests/test_sync.py tests/test_engine_environment.py -p no:cacheprovider -k retention" " passed"
check "4.10 real backfill from SOCO into reco_demo" "ML_MONGO_DB=reco_demo $PY -m reco.jobs sync && ML_MONGO_DB=reco_demo $PY scripts/show_events.py | grep -c 'backfill done'" "3"
check "4.11 real reconciliation of yesterday passes" "ML_MONGO_DB=reco_demo $PY -m reco.jobs reconcile_sync" '"passed": true'

cleanup
trap - EXIT
if $PY -c "
import asyncio
from pymongo import AsyncMongoClient
from reco.config import get_settings
async def m():
    c = AsyncMongoClient(get_settings().ml_mongo_uri); gone = 'reco_demo' not in await c.list_database_names(); await c.close(); raise SystemExit(0 if gone else 1)
asyncio.run(m())" && ! pgrep -f "uvicorn reco.main:app --port 819" >/dev/null; then pass "Z.1 clean up: reco_demo dropped, no engine left running"
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
