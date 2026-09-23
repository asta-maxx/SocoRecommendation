---
tags: [task, step-1]
task: ENG-02
status: In progress
owner: Allen
---
# ENG-02: Service skeleton and settings

> [!note] Status: **In progress** (24 Sep 2026)
> 4 of the 6 parts are built and checked on my laptop. The settings file (parts 3 and 4) is next.

**In one line:** tidy the engine into 12 clearly labelled parts, give it two ways to run, a health check that tells the truth, clear logs, and one settings file that can change without a restart.

## Why this task
Every later task adds code into one of the 12 parts, reads its numbers from the settings file, and is watched through the logs. This is the frame everything else hangs on. → [[Build Steps]]

## What came before
- [[ENG-01 - Engine home and databases]] gave the engine its home and databases.
- The code from [[Before Wave 1A - the M1 demo]] was organised for a demo: folders like "data", "domain" and "methods". The pack wants 12 specific parts instead. → [[The Pack]]

## Subtasks, one by one
The Build List splits ENG-02 into six numbered parts (1–6). There's one extra (A).

### 1. One engine, two ways to run ✅ laptop
- **What it asks:** the same code can start as the **API** (answering requests) or in **jobs mode** (doing the heavy nightly work, then stopping).
- **What we did:** the API starts as before. A new command, `python -m reco.jobs interest`, runs the interest-score job for both methods and then exits. It reports success or failure with an exit code, so a scheduler can tell.
- **Why it matters:** heavy work never slows down a user's request, and if a job crashes, the feed keeps working. → [[Recommendation Engine]]
- **Status:** done. The 2 AM scheduler that runs jobs automatically comes in ENG-07.

### 2. Twelve labelled parts, and two gatekeepers ✅
- **What it asks:** split the engine into 12 parts (api, config, slots, store, platform, eligibility, ranking, fallback, events, jobs, fraud, monitoring). Only **platform** may read SOCO's data. Only **store** may write.
- **What we did:** moved every existing file into its proper part, keeping its history. Six parts are empty for now, each labelled with the task that fills it.

  We also split the database connection in two:
  - SOCO's read-only connection now lives **only** in platform.
  - The engine's own connection lives in store.

  A new automatic check reads the code and fails if anything outside platform touches SOCO's data, or anything outside store writes.
- **Why it matters:** like a building where only one door leads to the vault. Nobody can wander in by accident, and the automatic check is the guard at that door. → [[Platform Database]], [[Engine Database]]
- **Status:** done. 16 automatic checks guard the layout.

### 3. One settings file that reloads itself ⏳ next
- **What it asks:** every tunable number (weights, time limits, thresholds) lives in **one** file with a version number. The engine re-reads it at least once a minute. If someone breaks the file, the engine keeps using the last good version. If there has never been a good one, it uses the pack's default values.
- **What we did:** not started yet.
- **Why it matters:** numbers can be tuned without restarting or redeploying, and a typo can never crash the engine.
- **Status:** next. → [[Settings file]]

### 4. A diary of every settings change ⏳ next
- **What it asks:** every change to the settings file is written down in `ml_config_changes`: when it happened, what the old value was, what the new value is, and who changed it.
- **What we did:** not started yet. It's built together with part 3.
- **Why it matters:** if results suddenly change, you can see exactly which number moved, when, and who moved it. → [[Collections]]
- **Status:** next.

### 5. A health check that tells the truth ✅
- **What it asks:** the `/health` page answers **200 (OK)** only when both databases can be read, and **503 (not OK)** when either can't.
- **What we did:** before, it always said OK, even with a database down. Now it checks both databases every time and answers honestly. It also says which environment it's in.
- **Why it matters:** the servers (and people) watching the engine find out straight away when something's wrong. → [[Environments]]
- **Status:** done. Checked live: 200 with both databases up. The tests prove 503 for each failure case.

### 6. Clear logs for every request and job ✅
- **What it asks:** everything the engine does is written to the log in a tidy, machine-readable way.
- **What we did:** every log line is now one small record with labelled fields: time, level, what happened, environment. Every request gets a line with its path, result and how long it took. Every job gets a "started" line, then a "finished" or "failed" line with its duration.
- **Why it matters:** like a flight recorder. When something goes wrong, the log says exactly what happened and when, and tools can count and filter it. → [[Logs]]
- **Status:** done. Checked live: a `/health` request was logged taking about 60 ms.

### A. Extra: every file updated to the new layout ✅
- **What we did:** every piece of code, script and test now points at the files' new homes. All 398 automatic checks pass.
- **Why it matters:** the tidy-up didn't break anything the demo already did.

## Coming in part 3: values that change
Moving to the pack's settings changes a few interest-score numbers. The pack says so, so this is expected, not a bug:
- A score counts as "too old" after **48 hours** instead of 24.
- "Not interested" and "Hide" now **lower** a category's interest (−5), where before they did nothing.
- Searches no longer count, because search tracking isn't part of Wave 1A.

## Still to do
| What | Waiting on |
|---|---|
| Parts 3 and 4: the settings file and its change diary | Next, on my laptop |
| Run the ENG-02 check and save the result | Parts 3 and 4 |

## How this connects
- **Before it:** [[ENG-01 - Engine home and databases]]
- **Built on:** [[Recommendation Engine]], [[Platform Database]], [[Engine Database]], [[Logs]], [[Settings file]]
- **Next:** [[ENG-03 - Reading SOCO's data correctly]]. It teaches the platform part exactly how SOCO stores things, so nothing is missed or counted twice.
- **Technical version:** `docs/engineering/ENG-02.md` in the repo.
