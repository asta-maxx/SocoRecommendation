---
tags: [task, step-1]
task: ENG-02
status: Built
owner: Allen
---
# ENG-02: Service skeleton and settings

> [!note] Status: **Built** (24 Sep 2026)
> All 6 parts are built, and the task's official check **passed on my laptop**. The pack says every check must also be run on the **test** server. Once that server exists and the check passes there, this becomes **Passed**.

**In one line:** tidy the engine into 12 clearly labelled parts, give it two ways to run, a health check that tells the truth, clear logs, and one settings file that can change without a restart.

## Why this task
Every later task adds code into one of the 12 parts, reads its numbers from the settings file, and is watched through the logs. This is the frame everything else hangs on. → [[Build Steps]]

## What came before
- [[ENG-01 - Engine home and databases]] gave the engine its home and databases.
- The code from [[Before Wave 1A - the M1 demo]] was organised for a demo: folders like "data", "domain" and "methods". The pack wants 12 specific parts instead. → [[The Pack]]

## Subtasks, one by one
The Build List splits ENG-02 into six numbered parts (1–6). There are two extras (A and B).

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

### 3. One settings file that reloads itself ✅ laptop
- **What it asks:** every tunable number (weights, time limits, thresholds) lives in **one** file with a version number. The engine re-reads it at least once a minute. If someone breaks the file, the engine keeps using the last good version. If there has never been a good one, it uses the pack's default values.
- **What we did:**
  - Wrote the file, `settings/engine.toml`. It holds all **144 numbers** from the pack's Settings sheet, each with a note of its allowed range.
  - The engine checks every number when it reads the file. A number outside its range, or a "fixed" number that was changed, gets the whole file rejected.
  - Every change needs a **new version number** and the **name of whoever made it**. A file that changes numbers but keeps the old version is rejected too.
  - The engine looks at the file every 30 seconds.
  - If the file is broken, the engine keeps its last good settings. That still works after a restart, because the last good settings are saved in the database.
- **Why it matters:** numbers can be tuned without restarting or redeploying, and a typo can never crash the engine.
- **Status:** done. Checked live: a change was picked up in **29 seconds**. A deliberately broken file was rejected, and the engine kept running. → [[Settings file]]

### 4. A diary of every settings change ✅ laptop
- **What it asks:** every change to the settings file is written down in `ml_config_changes`: when it happened, what the old value was, what the new value is, and who changed it.
- **What we did:** every time a new version goes into force, the engine writes one diary entry. It records the time, the new and old version numbers, who made the change, each changed number with its old and new value, and a full copy of all the settings. Each version number can appear in the diary only once. So if the engine and a job both notice the same change, it's written down only once.
- **Why it matters:** if results suddenly change, you can see exactly which number moved, when, and who moved it. → [[Collections]]
- **Status:** done. The live check wrote exactly this entry: *version 2, by "ENG-02 check", popularity window 30 → 45.*

### 5. A health check that tells the truth ✅
- **What it asks:** the `/health` page answers **200 (OK)** only when both databases can be read, and **503 (not OK)** when either can't.
- **What we did:** before, it always said OK, even with a database down. Now it checks both databases every time and answers honestly. It also says which environment it's in.
- **Why it matters:** the servers (and people) watching the engine find out straight away when something's wrong. → [[Environments]]
- **Status:** done. Checked live both ways: **200** with both databases up, and **503** with the engine's database switched off.

### 6. Clear logs for every request and job ✅
- **What it asks:** everything the engine does is written to the log in a tidy, machine-readable way.
- **What we did:** every log line is now one small record with labelled fields: time, level, what happened, environment. Every request gets a line with its path, result and how long it took. Every job gets a "started" line, then a "finished" or "failed" line with its duration.
- **Why it matters:** like a flight recorder. When something goes wrong, the log says exactly what happened and when, and tools can count and filter it. → [[Logs]]
- **Status:** done. Checked live: a `/health` request was logged taking about 60 ms.

### A. Extra: every file updated to the new layout ✅
- **What we did:** every piece of code, script and test now points at the files' new homes.
- **Why it matters:** the tidy-up didn't break anything the demo already did.

### B. Extra: the pack's numbers replace the demo's ✅
- **What we did:** the interest score now uses the pack's numbers instead of the old demo numbers. A few of them are different, so its behaviour changed slightly (see below). Tests that check against the **old demo data** still use the old numbers on purpose, because that data was made with them.
- **Why it matters:** the engine now follows the pack, not the demo.
- **Status:** done. All automatic checks pass: **432** on the laptop and **31** against the database.

## Values that changed
Moving to the pack's settings changed a few interest-score numbers. The pack says so, so this is expected, not a bug:
- A score counts as "too old" after **48 hours** instead of 24.
- "Not interested" and "Hide" are now set to **lower** a category's interest (−5), where before they were set to do nothing. The score starts using this in ENG-10, when those events are read in.
- Searches no longer count, because search tracking isn't part of Wave 1A.

## Result (24 Sep 2026)
The official ENG-02 check, run live on my laptop:
- **Change a setting:** it took effect in 29 seconds, and the change was written in the diary. ✅
- **Break the file:** the engine kept running on its last good settings. ✅
- **Switch a database off:** `/health` answered 503. ✅

The full record is in `Tracing/checks/ENG-02_2026-09-24.md`.

## Still to do
| What | Waiting on |
|---|---|
| Run the same check on the **test** server, then mark it Passed | The test server (see [[ENG-01 - Engine home and databases]]) |
| Copy the check record to the shared "Wave1A checks" folder | Access to the folder (Sanjai) |

## How this connects
- **Before it:** [[ENG-01 - Engine home and databases]]
- **Built on:** [[Recommendation Engine]], [[Platform Database]], [[Engine Database]], [[Logs]], [[Settings file]]
- **Next:** [[ENG-03 - Reading SOCO's data correctly]]. It teaches the platform part exactly how SOCO stores things, so nothing is missed or counted twice.
- **Demo:** [[Demo - ENG-02]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-02.md` in the repo.
