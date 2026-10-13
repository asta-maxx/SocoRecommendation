---
tags: [task, step-2]
task: ENG-07
status: Built
owner: Allen
---
# ENG-07: Nightly jobs

> [!note] Status: **Built** (1 Oct 2026, on my laptop)
> The machinery is done: the 2 AM timer, the "finish first, then swap" rule, the job diary and the labels on every score. The interest score (M1) already runs on it, then the daily category check (from ENG-29), and the engine sync's daily audit last. The other nightly jobs join as their own tasks are built. It becomes **Passed** once the check runs on the test server.
>
> **Audit fixes, 1 Oct 2026:** a job that gets stuck or is killed now raises an alert within about 2 hours, instead of waiting for the next night; a failed run writes "0 rows" in the diary; and the 2 AM time is locked, as the pack says.

**In one line:** every night at 2 AM, the engine works out fresh scores in the background, and only swaps them in once they're completely finished.

## Why this task
The pack's rule is that a request **never calculates anything**. It only reads scores that were worked out earlier (SD-17). That earlier work happens here, at night. Almost every model task plugs into it: similar posts (ENG-14), the promoter score (ENG-16), the product ranker (ENG-17), opportunities (ENG-18), the fraud rules (ENG-21), and the interest score on live data (ENG-10). The fallback ladder (ENG-09) and the weekly measurements (ENG-25) read what it records. → [[Build Steps]]

> [!example] The idea in one picture
> A restaurant prepares tomorrow's menu overnight. The new menu is printed in the back room, while diners keep reading tonight's menu. Only when **every** page of the new one is printed are the menus on the tables swapped. If the printer jams halfway, nobody ever sees half a menu: tonight's menu simply stays on the tables, and the jam is written in the kitchen log.

## What came before
- [[ENG-02 - Service skeleton and settings]] gave the engine its **jobs mode**: the same code, started as a task that does heavy work and stops, instead of answering requests. It also gave the settings file and tidy log lines. Nightly jobs are jobs-mode tasks. → [[Settings file]], [[Logs]]
- [[ENG-04 - Engine sync]] built the daily audit of the copies (the *reconciliation*). The pack says it runs after the 2 AM refreshes, so it became the last nightly job. → [[Engine sync]]
- Before this task, the interest score job **overwrote** its scores in place. For a moment during each run, some users had new scores and some old, and a crash left a mix. That's exactly what this task forbids.
- [[ENG-06 - Serve a recommendation list]] is the front door that will read these scores.

## Subtasks, one by one
The Build List splits ENG-07 into six numbered parts (1–6). There are three extras (A–C).

### 1. A timer that runs everything at 2 AM IST ✅ laptop / ⏳ servers
- **What it asks:** once a day, at 2 AM India time, start all the nightly jobs.
- **What we did:** a scheduler that waits until 2 AM India time, runs the jobs one after another, then waits for the next 2 AM. The time comes from the settings file (`refresh_time_ist`, "02:00"), which it re-reads before each wait, as the pack says the times are settings. Before each night it also re-reads all the other settings. If one job fails, an alert is raised and **the other jobs still run**. There are two ways to start it: `scheduler` (wait and repeat forever) or `nightly` (run everything once, right now).
- **Why it matters:** fresh scores every morning, with no one having to remember.
- **Status:** works on my laptop. On the servers it can run either as that endless loop or from the server's own timer (cron) calling `nightly`. Not decided yet: it waits on the servers. → [[Environments]]

> [!note] Locked at 2 AM, daily (fixed 1 Oct 2026)
> The pack's Settings sheet says the refresh is "daily, 2 AM IST … Fixed for Wave 1A". Before, the settings file would accept another time or "weekly". Now the time and the "daily" stay in the settings file (the pack says the times are settings), but any other value is refused, and the engine keeps the settings it had.

### 2. The list of nightly jobs ✅ M1 / ⏳ the rest
- **What it asks:** the nightly run covers six jobs: M1 (both methods), M2 method two, M5 (both methods), M8 (both methods, plus a monthly copy on the 1st), M6 and the fraud rules.
- **What we did:** a list of job names that the scheduler runs in order. Each task adds its job when it's built. Today the list is:

  | Job | Status |
  |---|---|
  | M1, the interest score, both methods | ✅ running |
  | M2 method two, similar posts | ⏳ ENG-14 |
  | M5, the product ranker, both methods | ⏳ ENG-17 |
  | M8, the promoter score, both methods + monthly copy | ⏳ ENG-16 |
  | M6, opportunities | ⏳ ENG-18 |
  | The fraud rules | ⏳ ENG-21 |
  | The daily check for SOCO categories with no match (not in this task's list, added by ENG-29) | ✅ running |
  | The sync's daily audit (always last) | ✅ running (from ENG-04) |
- **Why it matters:** one timer, one place to look, one alert route for everything heavy.
- **Status:** 1 of 6 model jobs runs now, plus the category check and the audit. The **monthly** copy of M8 on the 1st needs a "first of the month" trigger the timer doesn't have yet; it comes with M8 (ENG-16). M1 still reads SOCO's activity the old way: on 1 Oct it read 146 events for 5 users and had to drop 113 (58 with a category it couldn't match, 55 of a type it didn't know). ENG-10 moves it onto the engine's own copies.

### 3. Finish the whole batch, then swap it in ✅
- **What it asks:** each job writes a complete new set of scores (a *batch*), and only then marks it as the one to use. A request must never see a half-written batch.
- **What we did:**
  - Each run gets its own **run number** (`job_run_id`). Every score it writes is stamped with that number.
  - New scores are written **beside** the ones in use, never over them.
  - Only when the job has finished does it mark its run as **current**. From that moment, requests read the new batch.
  - Requests always ask "which run is current?" first, and read only that run's scores. Anything else in the drawer is invisible to them.
  - The batch that was just replaced is kept **one more night**, so a request that started reading it a split second before the swap can finish. Anything older is deleted.
- **Why it matters:** no user ever gets a list built from half old, half new scores.
- **Status:** done. Tested with three batches in a row: the newest is read, the one before is kept, the oldest is gone. → [[Collections]], [[Indexes]]

> [!tip] Why keep the old batch one more night?
> The pack says when a batch becomes current, but not when the old one may be thrown away. If we deleted it the instant the new one went live, a request already halfway through reading it would suddenly find nothing. Keeping it a day is cheap and makes that impossible. (Our choice, 1 Oct 2026.)

### 4. A failed job leaves yesterday's scores in use ✅
- **What it asks:** if a job fails, keep using the previous batch.
- **What we did:** if a job hits an error halfway, it writes the failure, the error and "0 rows written" in its diary entry (the "0 rows" since 1 Oct: the pack wants rows written on every run, and the half-batch is thrown away, so 0 is the truth), deletes the half-batch it wrote, and never marks anything current. Yesterday's batch simply stays in use. The scheduler raises an alert and goes on to the next job. The interest job has two methods; if one fails, the other still runs and swaps in its new scores, and the job is then reported as failed, naming the method that broke.
- **Why it matters:** a bad night means slightly older scores, never broken ones. The pack counts a score as fresh for 48 hours (after that, the fallback ladder in ENG-09 will step in), so one missed night is harmless.
- **Status:** done. Tested by making a job fail after 2 of 4 users: requests still read the old batch, the failure is recorded, and the half-batch is gone.

### 5. A diary of every run (`ml_job_runs`) ✅
- **What it asks:** record every run: which job, what period of data it looked at, how many rows it wrote, how long it took, whether it worked, and its run number.
- **What we did:** each run gets one entry in the `ml_job_runs` drawer, created as it **starts** (marked "running") and finished as it ends ("succeeded" or "failed"). The entry's own label *is* the run number. It also notes the settings version, the model version, and whether this is the current batch. Jobs that don't produce scores are in the diary too: every 5-minute copy of SOCO's data (the sync), the daily audit, and the lag check. Their entries say how many rows they copied or re-read and, for the audit, which day it checked and whether each source passed.
- **Why it matters:** "what ran last night, and did it work?" has a one-line answer. ENG-25's weekly measurements will use it to see if jobs finish late.
- **Status:** done, for every job (the sync, audit and lag check joined on 1 Oct, as the pack says "every job run"). A killed sync or audit is noticed the same way as a killed scoring job (extra A).

### 6. A label on every score ✅
- **What it asks:** every score row says what was scored, for which slot and method, by which model and settings version, the score itself, how sure it is (if the method knows), what period of data it used, when it was worked out, and which run made it.
- **What we did:** every interest-score row now carries all of those. The "score" is the user's share for that category. "How sure" is empty, because neither interest method has a confidence measure (the promoter score will, in ENG-16). The data period is "everything up to the run" for the decay method, and "the last 90 days" for the time-windows method.
- **Why it matters:** any number we serve can be traced back to the exact run, settings and data that produced it.
- **Status:** done for M1. Each later model fills the same labels.

### A. Extra: noticing a job that was killed ✅
- **What we did:** if the computer is switched off or the job is force-killed, it can't write "failed" in its diary; the entry is left saying "running" forever. So the next time the same job starts (normally the next night), it first looks for its own old entries still saying "running" and marks them **failed: "abandoned: stopped before it finished"**. Their half-written scores were never current, so nobody read them, and they're cleared at the next success.
- **Why it matters:** this is exactly the Build List's check: "Kill a job halfway: requests keep reading the previous batch. ml_job_runs shows the failure." The pack doesn't say *how* to notice a kill; this is our choice (1 Oct 2026).
- **Added 1 Oct 2026 (audit): a watchman.** Waiting for the next night had a gap: a killed job said "running" for up to a day with nobody told, and for ever if that job never ran again. Now the engine's always-on web process (the part that answers requests) looks at the diary every 5 minutes. Any entry still "running" more than **2 hours** after it started raises an alert ("job stuck"), naming the job and its run number. It only alerts; the next run still marks the entry as failed. The watchman lives in the web process on purpose: if it lived in the jobs process, a killed job would take its own watchman down with it. The pack doesn't say how long is "too long"; 2 hours is far beyond any job today (the whole night takes about 3 seconds on my laptop). → [[Logs]]

> [!warning] Only one timer per server
> If two copies of the scheduler ran at once, the second would think the first had been killed. So on each server, run **one** scheduler: either the loop or cron, not both.

### B. Extra: a script to read the diary ✅
- **What we did:** `scripts/show_job_runs.py` prints the diary, newest first: job, method, worked or failed, rows, seconds, and which batch is current. Then how many score rows each batch holds. It never prints user IDs.
- **Why it matters:** checking last night is one command.

### C. Extra: a real "kill it halfway" demo ✅
- **What we did:** `scripts/demo_kill_job.py` acts out the check with a real force-kill, using four made-up users in the throwaway database: a finished batch ("fashion"), a slow batch ("beauty") killed partway, what a request reads then, and the next night's batch ("travel").
- **Why it matters:** the check is shown for real, not just in a test. → [[Demo - ENG-07]]

## Result (1 Oct 2026)
- **The real nightly run** on my laptop, into a throwaway database: both interest methods ran, each scoring 15 of 38 users with 54 score rows in about a second, and both batches became current. Then the sync's audit of 30 Sep passed on all three sources.
- **The real kill:** after force-killing a job halfway, a request still read "fashion" (yesterday's batch). The diary showed the killed run as "running"; after the next batch it showed **failed: abandoned: stopped before it finished**, and the new batch was current.
- **The audit is in the diary too:** the same nightly run left an entry for the audit of 30 Sep: 0 rows re-read, all three sources passed.
- Automatic checks: the 11 checks for this task pass (6 without a database, 5 on Atlas), plus the sync's check that every sync and audit run is in the diary.
- **After the audit fixes (1 Oct):** 13 pass (the 11, plus the new watchman test and its neighbour in the same file). The whole test suite: **634 pass, 1 skipped**.

## Decided
- **Keep the replaced batch one more night (1 Oct 2026).** The pack is silent on when an old batch may go; a request already reading it must be able to finish.
- **A killed run is noticed by the next run of the same job (1 Oct 2026).** The pack is silent on how; this makes the diary show the failure without anything extra running.
- **The sync's daily audit runs last (1 Oct 2026),** following the pack: "the daily reconciliation runs after the 2 AM refreshes" (SD-22).
- **The 2 AM time and "daily" are locked (1 Oct 2026, audit).** The Settings sheet marks them "Fixed for Wave 1A"; they stay in the settings file with one allowed value each.
- **A run "running" for over 2 hours raises an alert (1 Oct 2026, audit).** The pack names no time; 2 hours is far beyond any job today.

## Still to do
| What | Waiting on |
|---|---|
| The other nightly jobs: M2 method two, M5, M8, M6, the fraud rules | ENG-14, ENG-17, ENG-16, ENG-18, ENG-21 |
| A "first of the month" trigger for M8's monthly copy | ENG-16 |
| ~~M1 reading the engine's own copies instead of the old way~~ | Done 14 Oct → [[ENG-10 - Interest score on real data]] |
| On the servers: the endless loop, or the server's own timer (cron)? | The servers → [[People]] |
| Two timers running at once aren't prevented (the second would mark the first's run as abandoned) | One timer per server; a lock if the server setup needs one |
| Run the check on the **test** server, then mark it Passed | The test server ([[ENG-01 - Engine home and databases]]) |

## How this connects
- **Before it:** [[ENG-06 - Serve a recommendation list]]
- **Built on:** [[ENG-02 - Service skeleton and settings]] (jobs mode), [[Settings file]], [[Collections]], [[Indexes]], [[Engine Database]], [[Logs]], [[Engine sync]]
- **Next:** [[ENG-08 - Filters]]. It applies the rules no model can override (blocks, hidden posts, out of stock) before and after scoring.
- **Demo:** [[Demo - ENG-07]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-07.md` in the repo.
