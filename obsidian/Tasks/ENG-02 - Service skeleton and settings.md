---
tags: [task, step-1]
task: ENG-02
status: Built
owner: Allen
---
# ENG-02: Service skeleton and settings

> [!note] Status: **Built** (24 Sep 2026; realigned to the new pack on 1 Oct 2026)
> All 6 parts are built, and the task's official check **passed on my laptop**, first on 24 Sep and again on 1 Oct after the update. The pack says every check must also be run on the **test** server. Once that server exists and the check passes there, this becomes **Passed**.

> [!tip] What changed on 1 Oct (pack v1.3)
> The engine **no longer receives events**. SOCO_BE used to post them to the engine's event door (`/v1/events`). That door is closed. Instead, the engine fetches the events itself, every few minutes, with its read-only login. → [[Engine sync]]
> So for this task:
> - the part called **events** is now called **sync**;
> - the event door is gone, and the password SOCO_BE used for it is now the password for asking for recommendations;
> - the settings file follows the new pack: new numbers for the sync, a new "internal" mode, and a new section of **lists**.

**In one line:** tidy the engine into 12 clearly labelled parts, give it two ways to run, a health check that tells the truth, clear logs, and one settings file that can change without a restart.

## Why this task
Every later task adds code into one of the 12 parts, reads its numbers from the settings file, and is watched through the logs. This is the frame everything else hangs on. → [[Build Steps]]

## What came before
- [[ENG-01 - Engine home and databases]] gave the engine its home and databases.
- The code from [[Before Wave 1A - the M1 demo]] was organised for a demo: folders like "data", "domain" and "methods". The pack wants 12 specific parts instead. → [[The Pack]]

## Subtasks, one by one
The Build List splits ENG-02 into six numbered parts (1–6). There are three extras (A, B and C).

### 1. One engine, two ways to run ✅ laptop
- **What it asks:** the same code can start as the **API** (answering requests: recommendations, fraud cases and the health check) or in **jobs mode** (doing heavy work on a timer, then stopping). The engine sync is one of those jobs.
- **What we did:** the API starts as before, and it no longer has an event door. Jobs mode now has five jobs: `interest` works out interest scores for both methods; `sync`, `sync_loop`, `sync_check` and `reconcile_sync` copy SOCO's events, keep copying every 5 minutes, raise the alarm when copying falls behind, and double-check yesterday's copies. Each job reports success or failure with an exit code (a number a scheduler reads: 0 means it worked), so a scheduler can tell.
- **Why it matters:** heavy work never slows down a user's request, and if a job crashes, the feed keeps working. → [[Recommendation Engine]]
- **Status:** done. The 2 AM scheduler that runs the nightly jobs automatically comes in ENG-07.

### 2. Twelve labelled parts, and two gatekeepers ✅
- **What it asks:** split the engine into 12 parts (api, config, slots, store, platform, eligibility, ranking, fallback, **sync**, jobs, fraud, monitoring). Only **platform** may read SOCO's data. Only **store** may write.
- **What we did:** moved every existing file into its proper part, keeping its history. Parts with nothing in them yet are labelled with the task that fills them.

  We also split the database connection in two:
  - SOCO's read-only connection now lives **only** in platform.
  - The engine's own connection lives in store.

  A new automatic check reads the code and fails if anything outside platform touches SOCO's data, or anything outside store writes.

  On 1 Oct the part called **events** became **sync**. "Events" held the code that received SOCO_BE's events; that code is gone with the event door. "Sync" holds the code that fetches them instead: it reads through platform and writes its copies through store, so the two gatekeepers still hold.
- **Why it matters:** like a building where only one door leads to the vault. Nobody can wander in by accident, and the automatic check is the guard at that door. → [[Platform Database]], [[Engine Database]]
- **Status:** done. 16 automatic checks guard the layout, now with sync in the list.

### 3. One settings file that reloads itself ✅ laptop
- **What it asks:** every tunable number (weights, time limits, thresholds) lives in **one** file with a version number. The engine re-reads it at least once a minute. If someone breaks the file, the engine keeps using the last good version. If there has never been a good one, it uses the pack's default values.
- **What we did:**
  - Wrote the file, `settings/engine.toml`. It holds every value on the pack's Settings sheet, each with a note of its allowed range: **155 values** since the 1 Oct update (it was 144).
  - The engine checks every value when it reads the file. A number outside its range, or a "fixed" number that was changed, gets the whole file rejected.
  - Every change needs a **new version number** and the **name of whoever made it**. A file that changes values but keeps the old version is rejected too. The file is at **version 2** now (the 1 Oct update was the change from 1 to 2).
  - The engine looks at the file every 30 seconds.
  - If the file is broken, the engine keeps its last good settings. That still works after a restart, because the last good settings are saved in the database.
- **What the 1 Oct update changed in the file:**

  | What | Before | Now |
  |---|---|---|
  | Each surface (feed, product page) | off or live | off, **internal** or live. Internal shows the engine's lists to our test accounts only, so we can check it on the real app before launch |
  | How events arrive | SOCO_BE forwards them (batch size, time limit) | The engine fetches them: every **5 minutes**, re-reading the last **2 minutes**, with an alarm when **15 minutes** behind |
  | Keeping events | 365 days | Still 365 days, now counted from when the event happened, on the engine's own copies |
  | New session | after 30 minutes in the background | after 30 minutes or more away (background or closed) |
  | Re-checking what may be shown | not there | every **15 minutes** (5 to 60) |
  | **Lists** | not there | a new section (below) |

  The **lists** section holds things I keep up to date by hand, like a staff noticeboard:
  - a **category map**: SOCO's own category names, matched to the pack's 23;
  - **status spellings**: the different ways SOCO spells "active" and friends, mapped to one;
  - the exact **order status** words SOCO stores (Delivered, Cancelled, Rejected, Return Requested, Returned);
  - **exemptions**: accounts the fraud rules may flag but never act on;
  - **test accounts**: accounts left out of learning and measurement, and the ones "internal" mode serves.

  Each exemption or test account must say which account, why, until when, and who added it. The maps and lists start empty; they get filled as later tasks need them.
- **Why it matters:** values can be tuned without restarting or redeploying, and a typo can never crash the engine. Because lists live in the same file, adding a test account is recorded like any other change.
- **Status:** done. Checked live on 1 Oct: a change was picked up within **30 seconds**. A deliberately broken file was rejected, and the engine kept running. → [[Settings file]]

### 4. A diary of every settings change ✅ laptop
- **What it asks:** every change to the settings file is written down in `ml_config_changes` (the engine's settings-history drawer): when it happened, what the old value was, what the new value is, and who changed it.
- **What we did:** every time a new version goes into force, the engine writes one diary entry. It records the time, the new and old version numbers, who made the change, each changed value with its old and new value, and a full copy of all the settings. Each version number can appear in the diary only once. So if the engine and a job both notice the same change, it's written down only once.
- **Why it matters:** if results suddenly change, you can see exactly which value moved, when, and who moved it. The same goes for the new lists: you can see who added a test account, and when. → [[Collections]]
- **Status:** done. The 1 Oct check wrote exactly this entry: *version 2 → 3, by "Demo", popularity window 30 → 45.*

### 5. A health check that tells the truth ✅
- **What it asks:** the `/health` page answers **200 (OK)** only when both databases can be read, and **503 (not OK)** when either can't.
- **What we did:** before, it always said OK, even with a database down. Now it checks both databases every time and answers honestly. It also says which environment it's in.
- **Why it matters:** the servers (and people) watching the engine find out straight away when something's wrong. → [[Environments]]
- **Status:** done. Checked live both ways on 1 Oct: **200** with both databases up, and **503** with the engine's database switched off.

### 6. Clear logs for every request and job ✅
- **What it asks:** everything the engine does is written to the log in a tidy, machine-readable way.
- **What we did:** every log line is now one small record with labelled fields: time, level, what happened, environment. Every request gets a line with its path, result and how long it took. Every job, the sync jobs included, gets a "started" line, then a "finished" or "failed" line with its duration.
- **Why it matters:** like a flight recorder. When something goes wrong, the log says exactly what happened and when, and tools can count and filter it. → [[Logs]]
- **Status:** done. Checked live on 1 Oct: a `/health` request was logged taking about 50 ms.

### A. Extra: every file updated to the new layout ✅
- **What we did:** every piece of code, script and test now points at the files' new homes. Since 1 Oct, the tests and the checklist read the settings file's current version number instead of assuming one, so raising the version never breaks them.
- **Why it matters:** the tidy-up didn't break anything the demo already did.

### B. Extra: the pack's numbers replace the demo's ✅
- **What we did:** the interest score now uses the pack's numbers instead of the old demo numbers. A few of them are different, so its behaviour changed slightly (see below). Tests that check against the **old demo data** still use the old numbers on purpose, because that data was made with them.
- **Why it matters:** the engine now follows the pack, not the demo.
- **Status:** done. All automatic checks pass: **509** on the laptop on 1 Oct (432 on 24 Sep).

### C. Extra: the event door closed, its password reused ✅ (1 Oct)
- **What we did:** removed the event door (`/v1/events`), the code behind it, and its old once-a-day count check. The password SOCO_BE used on that door (`INGEST_TOKEN`) is kept, under the same name, as the password SOCO_BE will send when it **asks for recommendations**. The check that compares it is ready; the recommendation door itself arrives in ENG-06.
- **Why it matters:** the pack retired the door, so leaving it open would accept data from a route nobody should use. Keeping the password name means Aravinth doesn't need a new one. → [[SOCO_BE]], [[Secrets and passwords]]
- **Status:** done. Wired to the recommendation door in ENG-06.

## Values that changed
Moving to the pack's settings changed a few interest-score numbers. The pack says so, so this is expected, not a bug:
- A score counts as "too old" after **48 hours** instead of 24.
- "Not interested" and "Hide" are now set to **lower** a category's interest (−5), where before they were set to do nothing. The score starts using this in ENG-10, when those events are read in.
- Searches no longer count, because search tracking isn't part of Wave 1A.

## Result (24 Sep 2026, re-checked 1 Oct 2026)
The official ENG-02 check, run live on my laptop:
- **Change a setting:** it took effect within 30 seconds, and the change was written in the diary. ✅
- **Break the file:** the engine kept running on its last good settings. ✅
- **Switch a database off:** `/health` answered 503. ✅

The 24 Sep record is in `Tracing/checks/ENG-02_2026-09-24.md`. The whole checklist passed again on 28 and 29 Sep (`Tracing/checks/`), and the ENG-02 steps passed again on 1 Oct after the update to the new pack.

## Still to do
| What | Waiting on |
|---|---|
| Run the same check on the **test** server, then mark it Passed | The test server (see [[ENG-01 - Engine home and databases]]) |
| Copy the check record to the shared "Wave1A checks" folder | Access to the folder (Sanjai) |
| Use the password check on the recommendation door | ENG-06 |
| Fill in the lists: category map, spellings, test accounts, exemptions | ENG-29 (the adapters); test accounts from Aravinth |

## How this connects
- **Before it:** [[ENG-01 - Engine home and databases]]
- **Built on:** [[Recommendation Engine]], [[Platform Database]], [[Engine Database]], [[Logs]], [[Settings file]]
- **Next:** [[ENG-03 - Reading SOCO's data correctly]]. It teaches the platform part exactly how SOCO stores things, so nothing is missed or counted twice. Then [[ENG-04 - Engine sync]] fills the sync part.
- **Demo:** [[Demo - ENG-02]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-02.md` in the repo.
