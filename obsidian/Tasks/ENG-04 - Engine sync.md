---
tags: [task, step-1]
task: ENG-04
status: Built
owner: Allen
---
# ENG-04: Receiving activity events

> [!note] Status: **Built** (29 Sep 2026)
> The engine can now receive what shoppers do, and the task's check **passed on my laptop**. Two things are left before it's really in use: I generate the real password (token) and give it to Aravinth, and Aravinth connects SOCO's backend to it (APP-12).

**In one line:** give the engine its own **event log**. It accepts what shoppers did (saw, tapped, added to cart, ordered), checks each entry, never stores anything twice, and tells SOCO's backend what happened to every entry.

## Why this task
Every model learns from what people do. Until now, that record lived only in SOCO's old logs. This task builds the engine's own log, the one every later model reads. Aravinth's side (APP-12) can't start until it exists, which is why it comes first. → [[Build Steps]]

## What came before
- [[ENG-01 - Engine home and databases]] created the empty `ml_events` drawer, with a lock that stops the same entry being saved twice.
- [[ENG-03 - Reading SOCO's data correctly]] wrote the rule for switching from SOCO's old logs to this new one, day by day. It needed a **switch date**, and this task is what sets it. → [[Event source switch]]

## Subtasks, one by one
The Build List splits ENG-04 into seven numbered parts (1–7). There are two extras (A and B).

### 1. A front door for events, with a password ✅
- **What it asks:** SOCO's backend sends events in batches of up to 100, with a secret password (a "token") in the request.
- **What we did:** built the door, `POST /v1/events`. Without the right password, it answers "unauthorized" and stores nothing. A batch of more than 100, or one that isn't in the right shape, is turned away with a clear reason.
- **Why it matters:** only SOCO's backend should ever be able to write into the engine's log.
- **Status:** done. Checked live: no password gets **401 (unauthorized)**. → [[Activity events]]

### 2. The password itself ⏳
- **What it asks:** generate the token and give it to Aravinth **privately**.
- **What we did:** a small script makes a new random token and saves it nowhere, so it can't leak into a file.
- **Why it matters:** the token is what lets SOCO's backend in and keeps everyone else out.
- **Status:** the script is ready. **I still need to generate the real one**, put it in my `.env`, and give it to Aravinth one to one. → [[Secrets and passwords]]

### 3. Turning away bad entries, with a reason ✅
- **What it asks:** refuse an entry if its position is 0, its screen isn't the feed or a product page, its item isn't a post or product, or a request/view/tap is missing the list it came from. Every entry must say who, what and which event.
- **What we did:** exactly those rules, and nothing more. Each refused entry is listed back with its reason. The good entries in the same batch are still stored, so one bad entry never loses the rest.
- **Why it matters:** bad entries would confuse every model that reads the log. Saying *why* lets SOCO fix the sender.
- **Status:** done. Checked live: a position-0 entry came back with *"position 0 is not allowed: positions count from 1"*.

### 4. Never storing the same thing twice ✅
- **What it asks:** remove duplicates by each entry's ID.
- **What we did:** if the same entry arrives twice, whether in one batch or because SOCO's backend retried after a network blip, the second copy is counted as a duplicate and not stored.
- **Why it matters:** retries are normal. Without this, every retry would count a view or tap twice.
- **Status:** done. **This is the task's official check:** the same batch sent twice came back the second time as **all duplicates**.

### 5. Kept for at least a year ✅
- **What it asks:** store entries in `ml_events`, findable by person, time and list, never deleted in under 365 days.
- **What we did:** entries are stored exactly as sent, plus the time they arrived. The drawer and its indexes were already set up in ENG-01. → [[Collections]], [[Indexes]]
- **Why it matters:** the models learn from months of history.
- **Status:** done.

### 6. A clear answer every time ✅
- **What it asks:** reply with how many entries were accepted, how many were duplicates, and which were refused and why.
- **What we did:** exactly that reply, plus a line in the engine's log for every batch. → [[Logs]]
- **Status:** done.

### 7. A daily comparison that sets the switch date ✅
- **What it asks:** every day, compare the new log with SOCO's old logs for requests, views, taps and feedback. The counts must be within 1%, and a sample of 100 entries must match one to one. After **7 days in a row** of agreement, fix the switch date and tell Aravinth to stop writing the old logs.
- **What we did:** built that comparison as a job. Each day's result is saved. On the 7th good day in a row, the switch date is fixed once and never moved, and the log tells me to tell Aravinth.
- **Why it matters:** it proves the new log is complete **before** the old one is switched off, so no history is lost. → [[Event source switch]]
- **Status:** done and tested. It starts counting once Aravinth's backend is writing to both logs.

### A. Extra: a window onto the log ✅
- **What we did:** a small script shows what's in the event log (counts by kind, the newest entries) and whether the switch date is fixed. It only reads.

### B. Extra: added to the checklist ✅
- **What we did:** the one-command checklist now also checks this task, live. → [[Checklist]]

## Result (29 Sep 2026)
- The task's check **passes**: the same batch twice gives all duplicates, and position 0 is refused with a reason.
- All automatic checks pass: **529** on the laptop and **37** against the database.
- The record is in `Tracing/checks/ENG-04_2026-09-29.md`.

## Two things Aravinth needs to know
> [!warning] Before the switch date can ever be fixed
> 1. **SOCO's feedback log (`contentfeedbacks`) doesn't exist.** The daily comparison needs it for "not interested / hide / report / mute".
> 2. **SOCO's backend must stamp each event with one time, and write that same time to both logs.** The comparison matches entries to the second.

## Still to do
| What | Waiting on |
|---|---|
| Generate the real token; give it to Aravinth privately | Me |
| Connect SOCO's backend to this door (APP-12) | Aravinth → [[People]] |
| Run the daily comparison automatically every night | ENG-07 |
| Re-run the check on the **test** server, then mark it Passed | The test server |

## How this connects
- **Before it:** [[ENG-03 - Reading SOCO's data correctly]]
- **Built on:** [[Activity events]], [[Event source switch]], [[Engine Database]], [[Secrets and passwords]]
- **Next:** [[ENG-05 - Same method for each user]]. It gives each user the same one of two methods every time, fairly and permanently.
- **Demo:** [[Demo - ENG-04]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-04.md` in the repo.
