---
tags: [demo]
task: ENG-04
duration: about 10 minutes
---
# Demo: ENG-04, the engine sync

## What this demo proves
The Build List's check for ENG-04: *"On test: (a) the reconciliation report shows matching ids and field values; (b) a like undone after it was copied updates the existing copy; (c) stopping the sync for an hour and restarting loses nothing and duplicates nothing; (d) two rows with the same updated_at across a page boundary are both copied; (e) a failure before the checkpoint re-reads that batch; (f) the alert fires in a test outage; (g) the retention setting is shown."*

It acts out (a), (f) and (g) live on SOCO's real dev data, and shows (b) to (e) as automatic tests on made-up rows. It also shows the real first copy (backfill) and that a second pass duplicates nothing. → [[ENG-04 - Engine sync]]

> [!important] Every step that writes uses the **throwaway database `reco_demo`**. SOCO's data is only ever read (the read-only login), and my real dev engine database `SoCo` is never touched. The three small helper scripts refuse to run against anything not named `reco_demo…`.

## Setup (before the audience watches)
One terminal, in the repo:
```bash
cd ~/vultrx/SocoRecommendation
```
Write the three helper scripts (throwaway files in `/tmp`):

- **`/tmp/soco-audit.py`** runs the daily audit for one day and prints one line per collection.
- **`/tmp/soco-damage.py`** deletes one copy and changes a value in another, in `reco_demo` only.
- **`/tmp/soco-behind.py`** makes the orders copy look 20 minutes behind, in `reco_demo` only.

```bash
cat > /tmp/soco-audit.py <<'EOF'
import asyncio, sys
from reco.config import get_settings
from reco.platform import connection as p
from reco.store import connection as e
from reco.sync.reconcile import reconcile_day

async def main(day):
    s = get_settings()
    assert s.ml_mongo_db.startswith("reco_demo"), "throwaway database only"
    e.init_client(s); p.init_client(s)
    for r in await reconcile_day(s, day):
        print(f"{r['day']} {r['source']:23} ids {r['platform_ids']}/{r['engine_ids']}  missing {r['missing']}"
              f"  mismatched {r['mismatched']} {' '.join(sum(r['mismatched_fields'].values(), []))}"
              f"  re-read {r['reread']}  {'PASSED' if r['passed'] else 'NOT PASSED'}")
    await p.close_client(); await e.close_client()

asyncio.run(main(sys.argv[1]))
EOF
cat > /tmp/soco-damage.py <<'EOF'
import asyncio
from datetime import datetime, timezone
from reco.config import get_settings
from reco.store import connection as e

async def main():
    s = get_settings()
    assert s.ml_mongo_db.startswith("reco_demo"), "throwaway database only"
    e.init_client(s); events = e.ml_db(s)["ml_events"]
    day = {"source": "postevents", "created_at": {"$gte": datetime(2026, 9, 23, 18, 30), "$lt": datetime(2026, 9, 24, 18, 30)}}
    first, second = [d["_id"] async for d in events.find(day).limit(2)]
    await events.delete_one({"_id": first})
    await events.update_one({"_id": second}, {"$set": {"platform.undone_at": datetime.now(timezone.utc)}})
    print("deleted one copy; changed undone_at on another")
    await e.close_client()

asyncio.run(main())
EOF
cat > /tmp/soco-behind.py <<'EOF'
import asyncio
from datetime import timedelta
from reco.config import get_settings
from reco.store import connection as e
from reco.store.scores import utc_now

async def main():
    s = get_settings()
    assert s.ml_mongo_db.startswith("reco_demo"), "throwaway database only"
    e.init_client(s)
    await e.ml_db(s)["ml_sync_state"].update_one({"_id": "orders"}, {"$set": {"current_as_of": utc_now() - timedelta(minutes=20)}})
    print("orders: last good pass moved to 20 minutes ago")
    await e.close_client()

asyncio.run(main())
EOF
```
> [!tip] The helper scripts need `PYTHONPATH=.` so they can find the engine's code; the commands below include it.

## Steps

### 1. The first full copy of SOCO's data (backfill)
- **Say:** "The engine doesn't wait to be sent anything. It goes and copies SOCO's activity log, orders and served lists, everything SOCO still holds, before SOCO's 90-day expiry deletes it."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs sync 2>&1 | grep -E "backfill finished|job finished"
  ```
- **They should see** (about 3 seconds; re-run 1 Oct after the audit fixes):
  ```
  ... "message": "backfill finished", ... "source": "postevents", "copied": 146}
  ... "message": "backfill finished", ... "source": "orders", "copied": 8}
  ... "message": "backfill finished", ... "source": "recommendationrequests", "copied": 12}
  ... "message": "backfill finished", ... "source": "rec_serve_log", "copied": 0}
  ... "message": "job finished", ... "job": "sync", "outcome": "succeeded", "duration_ms": 3155.7}
  ```
  `rec_serve_log` (SOCO's serve log, added by ENG-29) copies 0: SOCO hasn't created it yet.
  → [[Engine sync]]

### 2. What was copied, with its event codes and bookmarks
- **Say:** "Every copy keeps where it came from and gets the pack's event code. Each collection has a bookmark, so the next pass knows where to start."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py
  ```
- **They should see:**
  ```
  ml_events in reco_demo (dev): 158 copies
    postevents                -     19
    postevents                E2    5
    postevents                E3    3
    postevents                E4    6
    postevents                E5    63
    postevents                E9    50
    recommendationrequests    E1    12
  ml_orders: 8 orders
  retention: copies kept 365 days from the original event time (setting events.retention_days = 365; index on created_at)
  sync state:
    postevents                 backfill done (146 copied) | checkpoint 2026-10-01 12:39:55.03… | current as of 2026-10-01 12:39:55.00… | last run succeeded
    orders                     backfill done (8 copied) | checkpoint … | current as of … | last run succeeded
    recommendationrequests     backfill done (12 copied) | checkpoint … | current as of … | last run succeeded
    rec_serve_log              backfill done (0 copied) | checkpoint … | current as of … | last run succeeded
  reconciliation:
  ```
  Point out: E2 seen, E3 tapped, E4 added to cart, E5 ordered, E9 likes and follows (and their undos), E1 the served lists; `-` is a kind the pack gives no code. → [[Activity events]]

### 3. Run it again: nothing is copied twice
- **Say:** "Copies are filed under SOCO's own ID, and the bookmark moves only after a page is saved. Running again, or restarting after a crash, never makes duplicates."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs sync 2>&1 | grep "sync pass finished"
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py | head -1
  ```
- **They should see:** `"copied": {"postevents": 0, "orders": 0, "recommendationrequests": 0, "rec_serve_log": 0}`, then still `158 copies`.
- **Be upfront:** it copies 0 partly because SOCO's rows don't have their *last changed* time yet (APP-12), so the 5-minute read can't see changes. Steps 4 and 5 show how the daily audit covers that meanwhile.

### 4. The daily audit: yesterday (check a)
- **Say:** "Every day the engine audits yesterday against SOCO: the same IDs on both sides, and the same values in the fields that change. Equal counts alone don't pass."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs reconcile_sync 2>&1 | grep "reconciliation finished"
  ```
- **They should see:**
  ```
  ... "message": "sync reconciliation finished", ... "passed": true, "sources": {"postevents": true, "orders": true, "recommendationrequests": true}}
  ```
  (Yesterday, 30 Sep, had no rows on dev, so take a busier day next.)

### 5. The audit on a busy day, and catching damage (check a)
- **Say:** "24 September had 96 activity rows. First a clean audit; then I'll break two copies and watch the audit find them and fix them."
- **Run:**
  ```bash
  PYTHONPATH=. ML_MONGO_DB=reco_demo .venv/bin/python /tmp/soco-audit.py 2026-09-24 2>/dev/null
  ```
- **They should see:**
  ```
  2026-09-24 postevents              ids 96/96  missing 0  mismatched 0   re-read 0  PASSED
  2026-09-24 orders                  ids 0/0  missing 0  mismatched 0   re-read 0  PASSED
  2026-09-24 recommendationrequests  ids 2/2  missing 0  mismatched 0   re-read 0  PASSED
  ```
- **Run:** damage two copies, then audit twice:
  ```bash
  PYTHONPATH=. ML_MONGO_DB=reco_demo .venv/bin/python /tmp/soco-damage.py 2>/dev/null
  PYTHONPATH=. ML_MONGO_DB=reco_demo .venv/bin/python /tmp/soco-audit.py 2026-09-24 2>/dev/null
  PYTHONPATH=. ML_MONGO_DB=reco_demo .venv/bin/python /tmp/soco-audit.py 2026-09-24 2>/dev/null
  ```
- **They should see:**
  ```
  deleted one copy; changed undone_at on another
  2026-09-24 postevents              ids 96/95  missing 1  mismatched 1 undone_at  re-read 2  NOT PASSED
  ...
  2026-09-24 postevents              ids 96/96  missing 0  mismatched 0   re-read 0  PASSED
  ```
  Point out: the counts were nearly equal (96 vs 95), but the audit found **which** row was missing and **which field** was wrong, copied both again, and passed on the next run.

### 6. The alert when the sync falls behind (check f)
- **Say:** "If any collection is more than 15 minutes behind, or a run fails, the engine alerts me. I'll pretend the orders copy stalled 20 minutes ago."
- **Run:**
  ```bash
  PYTHONPATH=. ML_MONGO_DB=reco_demo .venv/bin/python /tmp/soco-behind.py 2>/dev/null
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs sync_check 2>&1 | grep '"alert": true'
  ```
- **They should see:**
  ```
  orders: last good pass moved to 20 minutes ago
  {... "level": "CRITICAL", "logger": "reco.alert", "message": "engine sync is behind or its last run failed; restart from the last checkpoint", ... "alert": true, "reason": "sync_lag", "owner": "Allen", "source": "orders", "lag_minutes": 20.8, "limit_minutes": 15, ...}
  {... "level": "INFO", "logger": "reco.job", "message": "sync lag", ... "sources": [{"source": "postevents", "lag_minutes": 0.9, ..., "alert": false}, {"source": "orders", "lag_minutes": 20.8, "last_outcome": "succeeded", "alert": true}, ...]}
  ```
  The first line is the alert; the second is the job's summary of every collection (four since ENG-29).
- **Mention:** since 1 Oct the engine's API runs this same check by itself every 5 minutes (the *watcher*), so the alarm still sounds if the sync process itself has died.
- **Then restart** from the bookmark, and check again:
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs sync 2>&1 | grep -c '"job finished"'
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs sync_check 2>&1 | grep -c '"alert": true'
  ```
- **They should see:** `1` (the pass ran), then `0` (no alert). → [[Logs]]

### 7. The retention setting (check g)
- **Say:** "Copies are kept at least a year from when the event happened, under the engine's own expiry. SOCO's 90 days never touch them."
- **Run** (since 1 Oct, the sync's window script shows it; read-only):
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py | grep retention
  ```
- **They should see:**
  ```
  retention: copies kept 365 days from the original event time (setting events.retention_days = 365; index on created_at)
  ```
  The first number is read from the database's own expiry rule; the second is the setting in force. They agree.
- *Optional:* the settings behind it:
  ```bash
  grep -n "sync_\|retention" settings/engine.toml
  ```
  ```
  60:sync_interval_minutes = 5                # 1-15. ENG-04 engine sync (replaces the retired SOCO_BE forward)
  61:sync_overlap_minutes = 2                 # fixed: each read re-reads a 2-minute overlap
  62:sync_lag_alert_minutes = 15              # fixed: alert when a source is more than 15 minutes behind
  63:retention_days = 365                     # fixed: engine copies kept at least this long from the event time (SD-29)
  ```
  (The `1-15` comment is the pack's range for later waves; since 1 Oct the interval is locked at 5 for Wave 1A.) → [[Settings file]], [[Indexes]]

### 8. The whole check, as automatic tests (checks a to g)
- **Say:** "The checks that need SOCO's rows to change on cue, an undo, an hour's outage, a crash at the wrong moment, run on made-up rows in a throwaway database."
- **Run:**
  ```bash
  TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest tests/test_sync.py -p no:cacheprovider -v \
    -k "undo or hour_stopped or page_boundary or failure_before or alert_fires or retention or reconciliation" 2>&1 | grep -E "PASSED|FAILED|passed"
  ```
- **They should see** (about 30 seconds):
  ```
  tests/test_sync.py::test_retention_is_the_setting PASSED
  tests/test_sync.py::test_an_undo_updates_the_existing_copy PASSED
  tests/test_sync.py::test_an_hour_stopped_loses_and_duplicates_nothing PASSED
  tests/test_sync.py::test_same_updated_at_across_a_page_boundary PASSED
  tests/test_sync.py::test_a_failure_before_the_checkpoint_rereads_the_batch PASSED
  tests/test_sync.py::test_the_alert_fires_when_the_sync_is_behind PASSED
  tests/test_sync.py::test_the_alert_fires_when_a_run_fails PASSED
  tests/test_sync.py::test_reconciliation_passes_when_ids_and_fields_match PASSED
  tests/test_sync.py::test_reconciliation_finds_and_rereads_what_the_sync_missed PASSED
  tests/test_sync.py::test_every_sync_and_reconciliation_run_is_recorded PASSED
  ====================== 10 passed, 9 deselected in 42.06s =======================
  ```
  In order: (g) retention, (b) an undo, (c) an hour stopped, (d) a page boundary, (e) a failure before the bookmark, (f) the alert twice (behind, and a pretend outage), (a) the audit twice, and every pass and audit written in the run diary (its name contains "reconciliation"). Re-run 1 Oct after the audit fixes.

### 9. (Optional) The real copy in my dev database
- **Say:** "This is the copy that's actually kept, made on 1 October. This only reads."
- **Run:**
  ```bash
  .venv/bin/python scripts/show_events.py
  ```
- **They should see:** `ml_events in SoCo (dev): 158 copies`, the same codes as step 2, `ml_orders: 8 orders`, the retention line, and all three collections `backfill done` (re-checked 1 Oct after the audit).

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The 5-minute read picking up a real change | SOCO's rows have no *last changed* time yet (0 of 146 activity rows) | Aravinth's APP-12 → [[People]] |
| The checks on the **test** server | It doesn't exist yet | The test server and its made-up data (ENG-01, ENG-29) |
| The sync running every 5 minutes on its own | No server to run it on; the timer comes with the nightly jobs | ENG-07, the servers |
| The audit passing 7 days in a row (for SOCO's migration, DB-16) | Needs 7 real days after APP-12 | APP-12, then 7 days |
| SOCO's serve log (`rec_serve_log`) in the copy | The collection doesn't exist yet | ENG-29, APP-15 |
| An alert as a message, not a log line | No channel chosen yet | A decision |

## Clean up
```bash
rm -f /tmp/soco-audit.py /tmp/soco-damage.py /tmp/soco-behind.py
.venv/bin/python -c "
import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
async def m():
    c=AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database('reco_demo'); await c.close(); print('reco_demo dropped')
asyncio.run(m())"
```

## How this connects
- Proves → [[ENG-04 - Engine sync]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-03]]
