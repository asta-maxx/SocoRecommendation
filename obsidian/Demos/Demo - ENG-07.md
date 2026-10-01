---
tags: [demo]
task: ENG-07
duration: about 8 minutes
---
# Demo: ENG-07, nightly jobs that never show a half-finished batch

> [!note] Since 1 Oct (ENG-29) the settings file is **version 3**. Where the outputs below show version 2 (`cfg2…`, `config_version 2`), a rehearsal today shows 3. Nothing else changes.

## What this demo proves
The Build List's check for ENG-07: *"Kill a job halfway: requests keep reading the previous batch. ml_job_runs shows the failure."*

It also shows the 2 AM timer, a real nightly run on SOCO's dev data, and the labels every score now carries. → [[ENG-07 - Nightly jobs]]

> [!important] Everything here writes, so it all runs against the **throwaway database** `reco_demo`. The kill script refuses to run anywhere else. The real engine database `SoCo` is never touched.

> [!note] Rehearsed on 1 Oct 2026. Run IDs (like `a36b1909`) are random and will differ each time. How many users the slow batch writes before the kill (one or two) varies too.

## Setup (before the audience watches)
One terminal, in the repo folder. Make sure `reco_demo` starts empty, so the diary only shows this demo:
```bash
.venv/bin/python -c "
import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
async def m():
    c=AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database('reco_demo'); await c.close(); print('reco_demo dropped')
asyncio.run(m())"
```
Nothing needs to be running: nightly jobs are started from the command line and stop when they're done.

## Steps

### 1. One timer, one list, 2 AM India time
- **Say:** "Every night at 2 AM India time, the engine runs its heavy jobs in a fixed order. The time lives in the settings file."
- **Run:**
  ```bash
  .venv/bin/python -m reco.jobs --list
  grep refresh_time_ist settings/engine.toml
  .venv/bin/python -c "
  from reco.config import live
  from reco.jobs.scheduler import NIGHTLY, next_run, IST
  from reco.store.scores import utc_now
  at = live.current().interest.refresh_time_ist
  print('nightly jobs:', NIGHTLY); print('next run:', next_run(utc_now(), at).astimezone(IST))"
  ```
- **They should see:**
  ```
  interest
  nightly
  reconcile_sync
  scheduler
  sync
  sync_check
  sync_loop
  79:refresh_time_ist = "02:00"
  nightly jobs: ('interest', 'reconcile_sync')
  next run: 2026-10-02 02:00:00+05:30
  ```
  `nightly` runs the list once, now; `scheduler` waits for 2 AM and repeats every day. The list has the interest score (M1) and the sync's daily audit, which the pack says runs **after** the refreshes. The other models join it as they're built. → [[Settings file]]

### 2. Kill a job halfway (the Build List's check)
- **Say:** "Here's a batch everyone reads, then a new batch that I'll force-kill halfway, the way a crash or a power cut would. Watch what a request reads."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/demo_kill_job.py 2>&1 | grep -v '^{"ts"'
  ```
  (The `grep` hides the engine's start-up log lines.)
- **They should see:**
  ```
  1. a complete batch (everyone 'fashion')
     a request reads: DEMO-U1=fashion, DEMO-U2=fashion
  2. a slow batch ('beauty'), killed halfway
      wrote DEMO-U1
      wrote DEMO-U2
     killed (SIGKILL: nothing in the job could run after it)
  3. straight after the kill
     a request reads: DEMO-U1=fashion, DEMO-U2=fashion
      a36b1909  succeeded CURRENT
      1f82b556  running
  4. the next night's batch ('travel')
  earlier runs never finished; recorded as failed
     a request reads: DEMO-U1=travel, DEMO-U2=travel
      a36b1909  succeeded
      1f82b556  failed             abandoned: stopped before it finished
      f529f074  succeeded CURRENT
  ```
- **Point out:**
  - In **3**, the killed job had already written a "beauty" score for DEMO-U1, yet the request still reads **fashion**. The half-batch was never marked current, so it's invisible. That's the first half of the check.
  - The killed run still says **running**: a force-kill gives it no chance to write anything.
  - In **4**, the next run notices that and records it as **failed: abandoned**. That's the second half of the check: the diary shows the failure.

> [!example] Like a restaurant's menus
> The new menu was being printed in the back when the printer died. Diners kept reading tonight's menu the whole time; the next night's menu replaced it only once fully printed.

### 3. The run diary
- **Say:** "Every run has one diary entry: what ran, whether it worked, how many rows, how long, and which batch is in use."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_job_runs.py
  ```
- **They should see:**
  ```
  ml_job_runs in reco_demo (dev), newest first:
    f529f074  interest  recency_decay   succeeded rows     4   0.195s  CURRENT
    1f82b556  interest  recency_decay   failed    rows     -       -s           abandoned: stopped before it finished
    a36b1909  interest  recency_decay   succeeded rows     4   0.205s
  score rows in ml_user_interest_scores by batch:
    recency_decay   a36b1909  4
    recency_decay   f529f074  4
  ```
  The killed run's half-batch is gone. The "fashion" batch is kept one more night, in case a request was still reading it at the moment of the swap. → [[Collections]]

### 4. A real nightly run on SOCO's dev data
- **Say:** "Now the real thing: the jobs that will run at 2 AM, run right now, on SOCO's dev data."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs nightly; echo "exit $?"
  ```
- **They should see** (log lines, trimmed; takes a few seconds):
  ```
  "message": "job started", "job": "nightly", "jobs": ["interest", "reconcile_sync"]
  "message": "job started", "job": "interest", "method": "recency_decay"
  "message": "read 146 events for 5 users; dropped 113 (unresolved category 58, … unknown type 55)"
  "message": "recency_decay v1.0.0: 15 of 38 users scored, 54 scores written in 1.1s. …", "job_run_id": "64a466da-…"
  "message": "job finished", "job": "interest", "outcome": "succeeded", "method": "recency_decay"
  "message": "job started", "job": "interest", "method": "time_windows"
  "message": "time_windows v1.0.0: 15 of 38 users scored, 54 scores written in 0.7s. …", "job_run_id": "2bd6c6cb-…"
  "message": "job finished", "job": "interest", "outcome": "succeeded", "method": "time_windows"
  "message": "job started", "job": "reconcile_sync"
  "message": "sync reconciliation finished", "job": "reconcile_sync", "passed": true, "sources": {"postevents": true, "orders": true, "recommendationrequests": true}
  "message": "job finished", "job": "nightly", "outcome": "succeeded", "duration_ms": 2755.2
  exit 0
  ```
  Both interest methods ran, then the sync's audit of yesterday. The "dropped 113" is because M1 still reads SOCO's activity the old way; ENG-10 fixes that. → [[Logs]], [[Engine sync]]

### 5. The diary again: both methods current
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_job_runs.py
  ```
- **They should see:**
  ```
  ml_job_runs in reco_demo (dev), newest first:
    fefff609  reconcile_sync None            succeeded rows     0   0.427s
    2bd6c6cb  interest  time_windows    succeeded rows    54   0.819s  CURRENT
    64a466da  interest  recency_decay   succeeded rows    54   1.154s  CURRENT
    f529f074  interest  recency_decay   succeeded rows     4   0.195s
    1f82b556  interest  recency_decay   failed    rows     -       -s           abandoned: stopped before it finished
    a36b1909  interest  recency_decay   succeeded rows     4   0.205s
  score rows in ml_user_interest_scores by batch:
    recency_decay   f529f074  4
    recency_decay   64a466da  54
    time_windows    2bd6c6cb  54
  ```
- **Point out:**
  - For recency decay, only the current batch and the one it replaced are kept. The two oldest batches are gone.
  - The audit is in the diary too (top line): it re-read 0 rows and has no batch, so it is never "CURRENT". Its entry also records the day it checked (30 Sep) and that all three sources passed. Every 5-minute sync pass gets an entry the same way.

### 6. Every score carries its label
- **Say:** "Any score can be traced back to the exact run, settings version and data period that made it."
- **Run** (user ID hidden):
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -c "
  import asyncio; from reco.config import get_settings; from reco.store import connection as c
  async def m():
      s=get_settings(); c.init_client(s)
      row=await c.ml_db(s)[s.scores_collection].find_one({'method':'time_windows'},{'_id':0,'user_id':0})
      for k,v in row.items(): print(f'{k:15} {v}')
      await c.close_client()
  asyncio.run(m())"
  ```
- **They should see:**
  ```
  category        Fashion & Apparel
  method          time_windows
  job_run_id      2bd6c6cb-3674-4b06-a023-fda2a65de505
  model_version   1.0.0
  computed_at     2026-10-01 09:27:45.657000+00:00
  confidence      None
  config_version  2
  data_window     {'from': datetime.datetime(2026, 7, 3, 9, 27, 45, …), 'to': datetime.datetime(2026, 10, 1, 9, 27, 45, …)}
  event_count     10
  raw             35.8
  score           0.4698162729658793
  share           0.4698162729658793
  slot            interest
  window          90d
  ```
  (The order of the lines can vary.) The data window is the last 90 days, for the time-windows method. `confidence` is empty: interest scores have none. The `job_run_id` matches the current run in step 5.

### 7. (Optional) The automatic checks
- **Run:**
  ```bash
  TEST_MONGO_DB=reco_demo .venv/bin/python -m pytest -q tests/test_nightly.py
  ```
  (`TEST_MONGO_DB=reco_demo` keeps the database tests in the throwaway database too.)
- **They should see:** `11 passed`. They include a job that fails halfway with an ordinary error (the previous batch stays current and the half-batch is deleted), and one interest method failing while the other still runs.

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The other nightly jobs (M2, M5, M8 and its monthly copy, M6, fraud rules) | Not built yet; each joins the list when it is | ENG-14, ENG-17, ENG-16, ENG-18, ENG-21 |
| A served list changing after the swap | The front door serves newest-first lists for now; it starts using these scores later | ENG-09, ENG-19 |
| Waiting for a real 2 AM | Nobody wants to stay up. `scheduler` does exactly what `nightly` does, at 2 AM | Nothing |
| The check on the **test** server | It doesn't exist yet | The test server ([[ENG-01 - Engine home and databases]]) |

## Clean up
Drop the throwaway database:
```bash
.venv/bin/python -c "
import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
async def m():
    c=AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database('reco_demo'); await c.close(); print('reco_demo dropped')
asyncio.run(m())"
```

## How this connects
- Proves → [[ENG-07 - Nightly jobs]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-06]]
