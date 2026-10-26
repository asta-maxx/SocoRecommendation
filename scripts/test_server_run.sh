#!/usr/bin/env bash
# The whole test-server run in one command, so nothing has to be pasted.
#
#     bash scripts/test_server_run.sh
#
# Run from the repo root in Git Bash (Windows) or bash (Linux), after cloning
# branch wave1a/eng-09-11-m1 and putting .env in place (copied by hand, never
# through git). It:
#   1. creates .venv and installs requirements.txt (once);
#   2. checks .env: it must exist and say ENGINE_ENV=test; ML_MONGO_DB and
#      MODEL_VERSION are set for the test server if missing;
#   3. checks the engine database and runs the unit tests;
#   4. runs the full checklist with proofs (about 25 minutes), output in
#      "Test Output/" and checklist_server.txt;
#   5. commits the raw proofs to a new branch proofs/test-server-<date> and pushes
#      it (never merged; Allen's Claude reads it, checks it and makes the PDFs).
set -u
cd "$(dirname "$0")/.."
# Run from the code branch, and come back to it after pushing the proofs (26 Oct: a
# server left on the proofs branch pulled into it instead of the code).
code_branch="wave1a/eng-09-11-m1"
if [ "$(git branch --show-current)" != "$code_branch" ]; then
  echo "== switching to $code_branch (was $(git branch --show-current))"
  git checkout -q "$code_branch" || { echo "STOP: could not switch to $code_branch"; exit 1; }
fi
git pull -q --ff-only || echo "   (git pull did not go through; running the code already here: $(git log --oneline -1))"
echo "== code: $(git branch --show-current) $(git log --oneline -1)"

if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else
  echo "== creating .venv"
  if command -v py >/dev/null 2>&1; then py -3.12 -m venv .venv
  else python3.12 -m venv .venv 2>/dev/null || python -m venv .venv; fi
  if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
fi
"$PY" -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version" || { echo "STOP: Python 3.12 is needed"; exit 1; }
echo "== installing requirements"
"$PY" -m pip install -q -r requirements.txt || { echo "STOP: pip install failed"; exit 1; }

echo "== checking .env"
[ -f .env ] || { echo "STOP: .env is missing. Copy it from the laptop by hand (never through git)."; exit 1; }
grep -q '^ENGINE_ENV=test' .env || {
  echo "STOP: .env must say ENGINE_ENV=test on the test server (it says: $(grep '^ENGINE_ENV=' .env || echo nothing))."
  echo "      Fix it with:  sed -i 's/^ENGINE_ENV=.*/ENGINE_ENV=test/' .env"; exit 1; }
grep -q '^ML_MONGO_DB=soco_engine_test' .env || { sed -i 's/^ML_MONGO_DB=.*/ML_MONGO_DB=soco_engine_test/' .env
  grep -q '^ML_MONGO_DB=' .env || echo 'ML_MONGO_DB=soco_engine_test' >> .env; echo "   ML_MONGO_DB set to soco_engine_test"; }
# 1.2.0 (26 Oct 2026): ENG-14's post types grew (Kala: adding a type is a model_version change).
grep -q '^MODEL_VERSION=1.2.0' .env || { sed -i 's/^MODEL_VERSION=.*/MODEL_VERSION=1.2.0/' .env
  grep -q '^MODEL_VERSION=' .env || echo 'MODEL_VERSION=1.2.0' >> .env; echo "   MODEL_VERSION set to 1.2.0"; }
set -a; . ./.env; set +a
# Review of 26 Oct 2026, point 1: until the test engine runs next to its databases, a
# longer test-only limit for the request and for each source (the engine refuses them in
# production). Printed into the proofs by checklist line 6.0.
# 26 Oct run: 3 s was not enough (a feed request is 17 database steps of about 250 ms from
# Kansas City), so 10 s, as the review allows ("raise it if that isn't enough").
export REQUEST_BUDGET_MS="${REQUEST_BUDGET_MS:-10000}" SOURCE_TIME_LIMIT_MS="${SOURCE_TIME_LIMIT_MS:-10000}"
# Review point 3: the service's settings state (the surface-off state and pending diary
# entries) lives outside the repo folder, so a fresh clone or redeploy keeps it.
export RECO_STATE_DIR="${RECO_STATE_DIR:-$(cd .. && pwd)/reco-state}"
mkdir -p "$RECO_STATE_DIR"; echo "   settings state folder: $RECO_STATE_DIR"
echo "   test-only limits: request ${REQUEST_BUDGET_MS} ms, each source ${SOURCE_TIME_LIMIT_MS} ms"

echo "== engine database"
"$PY" scripts/setup_engine_db.py || { echo "STOP: the engine database is not reachable. Is this server's IP on both Atlas access lists?"; exit 1; }
echo "== unit tests"
"$PY" -m pytest -q -p no:cacheprovider -m "not mongo" 2>&1 | tail -3

# A run adds to the proof files it finds, so last run's are moved aside first (kept, never deleted).
if [ -d "Test Output" ] || [ -f checklist_server.txt ]; then
  old="../proofs/earlier-$(date +%Y-%m-%d_%H%M%S)"; mkdir -p "$old"
  mv "Test Output" checklist_server.txt "$old"/ 2>/dev/null; echo "   last run's proofs moved to $(cd "$old" && pwd)"
fi
echo "== full checklist with proofs (about 25 minutes)"
PROOF_DIR="Test Output" bash scripts/run_checklist.sh 2>&1 | tee checklist_server.txt

# The proofs stay on the server (the repo is private; the server does not push, 26 Oct
# 2026): packed into one file to send by hand (WeTransfer). PUSH_PROOFS=1 pushes them to a
# branch of their own instead, if this server is ever given write access.
if [ "${PUSH_PROOFS:-0}" = "1" ]; then
  echo "== pushing the raw proofs to a branch of their own"
  branch="proofs/test-server-$(date +%Y-%m-%d)"
  git checkout -q -b "$branch" 2>/dev/null || git checkout -q "$branch"
  git add -f "Test Output" checklist_server.txt
  git -c user.name="${GIT_AUTHOR_NAME:-Allen Matthew}" -c user.email="${GIT_AUTHOR_EMAIL:-allen@test-server}"     commit -q -m "Test server checklist run, $(date +%Y-%m-%d): raw proofs" && git push -u origin "$branch"     && echo "DONE: pushed $branch." || echo "The push did not go through (see above)."
  git checkout -q "$code_branch" && echo "== back on $code_branch"
else
  pack="proofs-test-server-$(date +%Y-%m-%d_%H%M).tgz"
  mkdir -p ../proofs
  tar czf "../proofs/$pack" "Test Output" checklist_server.txt     && echo "DONE: the proofs are packed in $(cd ../proofs && pwd)/$pack. Send that file (WeTransfer)."     || echo "Packing failed; the proofs are in 'Test Output/' and checklist_server.txt."
fi

