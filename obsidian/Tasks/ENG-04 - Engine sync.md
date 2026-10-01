---
tags: [task, step-1]
task: ENG-04
status: Built
owner: Allen
---
# ENG-04: Engine sync

> [!note] Status: **Built** (rebuilt 1 Oct 2026)
> On 29 Sep this task was a front door that SOCO would send events to. Pack v1.3 retired that door and rewrote the task: the engine now **goes and copies** SOCO's activity itself. All 9 parts are built, the checks pass on my laptop, and the first real copy of SOCO's data is done. It becomes **Passed** once the checks run on the test server.

**In one line:** every few minutes, the engine copies what shoppers did, their orders, and the lists SOCO showed them, from SOCO's database into its own, and keeps those copies for a year.

## Why this task
Every model learns from what people do. That record lives in SOCO's database, which deletes most of it after 90 days and which the engine may only read. This task gives the engine its **own copy**, kept up to date and kept for a year. Serving lists (ENG-06), the interest score (ENG-10), the weekly measurements (ENG-25) and SOCO's own migration (DB-16) all wait on it. → [[Build Steps]]

## What came before
- [[ENG-01 - Engine home and databases]] made the engine's drawers. Two of them hold these copies: `ml_events` (activity and served lists) and `ml_orders`. A third, `ml_sync_state`, holds the sync's bookmarks. ENG-01 also set the one-year expiry on the copies. → [[Collections]], [[Indexes]]
- [[ENG-02 - Service skeleton and settings]] gave the engine its *jobs* mode, where this sync runs, and the settings file where its timings live. → [[Settings file]]
- [[ENG-03 - Reading SOCO's data correctly]] taught the engine how to read each kind of SOCO row. Every copy is made through those readers.
- **The old version of this task** was a front door, `POST /v1/events`, that SOCO's backend would send events to, plus a daily comparison to pick a switch date. Pack v1.3 retired both (API Contract v2.5, section 7): SOCO just writes to its own activity log, and the engine reads it. → [[Activity events]], [[Event source switch]]

> [!example] The idea in one picture
> A clerk keeps an archive copy of a busy office's in-tray. First they photocopy the whole filing cabinet once. After that, every 5 minutes, they copy only what's new or changed, and once a day they audit the archive against the originals. → [[Engine sync]]

## Subtasks, one by one
The Build List splits ENG-04 into nine numbered parts (1–9). There are three extras (A–C).

### 1. The first full copy (backfill) ✅
- **What it asks:** copy everything SOCO holds in three collections (its activity log `postevents`, `orders`, and its record of served lists `recommendationrequests`) into the engine. Each copy is filed under SOCO's own ID for the row. If the copy stops halfway, restarting it must not create duplicates.
- **What we did:** the sync reads each collection in ID order, 500 rows at a time, and after every page it writes down the last ID it copied. If it stops, it carries on from there. When it finishes, the regular 5-minute reads start from the moment the backfill **began**, so anything that changed while it ran is read again. (The pack doesn't set a page size or this hand-over point; I chose them so nothing can fall between the two.)
- **Why it matters:** SOCO deletes most activity and served lists after **90 days**. Anything not copied before then is gone for good, so this part is urgent on every new server.
- **Status:** done. **Real run on 1 Oct:** 146 activity rows, 8 orders and 12 served lists copied into my dev engine database in about 3 seconds. The oldest copy is from 23 June.
- → [[Engine sync]]

### 2. Every 5 minutes, only what's new or changed ✅ built / ⏳ needs SOCO's change times
- **What it asks:** every 5 minutes (a setting), ask SOCO for rows changed since the last bookmark, using each row's *last changed* time (`updated_at`). Read in time order, and start 2 minutes before the bookmark, so nothing stamped at nearly the same moment is missed.
- **What we did:** exactly that. Rows are read in order of change time, then ID, so two rows with exactly the same time either side of a page break are both copied. The 5 minutes is re-read from the settings before every pass, so changing it needs no restart.
- **Why it matters:** the engine sees a new like, an undo or an order update within minutes, not the next day.
- **Status:** built and tested. But SOCO's rows **don't carry `updated_at` yet**: 0 of 146 activity rows, 3 of 8 orders, 0 of 12 served lists. Aravinth's task APP-12 adds it ("reported built", not in this database yet). Until then this read finds nothing new, and part 8 catches new rows the next day instead. → [[Platform Database]]

> [!warning] What APP-12 changes
> Without change times, a row **created** yesterday is still caught by the daily audit (part 8), about a day late. But a change to an **older** row (an undo of last week's like, a new step in an old order) can't be seen by either until APP-12 lands.

### 3. Update, never skip ✅
- **What it asks:** if the engine already holds a row, update it. Never skip it, so an undo, an order status change, a return request or new "seen" items all arrive.
- **What we did:** every copy is an **upsert**: update if held, insert if new. The time it was first copied is set once and never changes.
- **Why it matters:** SOCO's rows change after they're written. A sync that only added new rows would keep a like that was undone, or an order that was later returned.
- **Status:** done. Tested: a like undone after it was copied updates the one copy, and its original time doesn't move.

### 4. Move the bookmark only after the copy is saved ✅
- **What it asks:** save the bookmark (checkpoint) in `ml_sync_state` only after the batch it covers is written.
- **What we did:** for each collection, the engine keeps a small record: the bookmark, how far the backfill got, when the last good pass started, and how the last run went. The bookmark moves only after the page is written.
- **Why it matters:** if the engine crashes between writing and bookmarking, the next run simply reads that page again. Because of part 3, reading it twice does no harm.
- **Status:** done. Tested by making the bookmark save fail on purpose: the batch was read again and not duplicated.

### 5. What every copy keeps, and its event code ✅
- **What it asks:** each copy keeps where it came from (collection and ID), its event ID, the undo fields, the **original** event time and the last-changed time. Each kind of activity is mapped to the pack's event codes (E1, E2…).
- **What we did:** each copy holds the clean record from [[ENG-03 - Reading SOCO's data correctly]], those fields, and its E code. It also keeps the **whole SOCO row as read**, so the daily audit can compare values exactly. (My choice, since the clean record tidies some values.) A served list becomes an E1 record.
- **Why it matters:** the original time decides which day an event counts for and when the copy expires. The E code is how every model asks for "impressions" or "clicks".
- **Status:** done. On the real copy: 5 items seen (E2), 3 taps (E3), 6 add-to-carts (E4), 63 orders placed (E5), 50 likes, saves, follows and their undos (E9), 19 of a kind the pack gives no code, and 12 served lists (E1). → [[Activity events]]

### 6. Kept for a year from when it happened ✅
- **What it asks:** keep copies at least 365 days from the original event time, under the engine's own expiry. SOCO's 90-day expiry must never delete an engine copy, and an update must never restart the clock.
- **What we did:** the expiry set up in ENG-01 counts from the original event time, which comes from SOCO's row and never changes on an update. SOCO's expiry only touches SOCO's database.
- **Why it matters:** the models learn from months of history, and seasonal patterns need the whole year.
- **Status:** done. The setting reads 365 days, and a test checks the expiry itself. → [[Indexes]]

### 7. An alert when it falls behind or fails ✅
- **What it asks:** if any collection is more than 15 minutes behind, or a run fails, alert the service owner (me), who restarts from the last bookmark.
- **What we did:** after every pass, and on its own as a job, the engine works out how far behind each collection is: the time since its last good pass **started**. Over 15 minutes, or a failed run, writes an **alert** line in the log, marked as an alert and addressed to me. Restarting is just running the next pass; it carries on from the bookmark.
- **Why it matters:** a stuck sync means the engine is learning from stale data. Without an alert, no one would notice.
- **Status:** done. The pack says *who* gets the alert but not *how*, so for now it's a log line until we choose a channel. Tested: 16 minutes behind fires it, and so does a pretend outage. → [[Logs]]

### 8. A daily audit against SOCO ✅
- **What it asks:** once a day, for the day before, check each collection: the same set of IDs on both sides, and for changed rows, the same values in the fields that change. Equal counts alone don't pass. Every mismatch is logged and read again.
- **What we did:** the audit takes yesterday by **India time** (the nightly jobs run at 2 AM India time; the pack doesn't name the day boundary, so I matched it). It finds every SOCO row created or changed that day, and checks each against the engine's copy: undo fields for activity, status and delivery steps (`tracking_info`) for orders, and "seen" items for served lists. Anything missing or different is copied again straight away, and the result is saved.
- **Why it matters:** it proves the copy is complete and correct, not just the right size. 100 rows on each side could still be the wrong 100. It's also how APP-12 is verified, and SOCO's migration (DB-16) drops its old logs only after **7 passing days in a row**, which I have to confirm in writing.
- **Status:** done. **Real run on 1 Oct:** yesterday (30 Sep) passed on all three (no rows that day). On 24 Sep (96 activity rows, 2 served lists) it passed too, and when I damaged two copies on purpose it found both, re-copied them, and passed the next time.

> [!note] The pack's row names two order fields SOCO doesn't have (`statusLog`, `return_info`). ENG-29 says to compare `tracking_info` instead, which SOCO does have, and that's what the audit compares.

### 9. Each order's status history ✅ (a cross-check now)
- **What it asks:** whenever the sync sees a new order status, store it with its time, so the engine knows an order reached Delivered or Return Requested even if it changes later.
- **What we did:** each order copy carries a short history. A status is added only when it differs from the last one held.
- **Why it matters:** an order that was delivered and then returned must still count as returned.
- **Status:** done. Tested: Placed → Delivered → Return Requested gives three entries. ENG-29 makes SOCO's own `tracking_info` the order's history, so this list stays **as a cross-check only**. Before APP-12 it holds one entry per order.

### A. Extra: an alert helper ✅
- **What we did:** one small piece of code that every alert goes through, always marked the same way and addressed to me.
- **Why it matters:** when we pick a real alert channel (a message, an email), it plugs in at one place.

### B. Extra: a window onto the sync ✅
- **What we did:** a script that shows how many copies there are by collection and code, each collection's bookmark and last run, and the latest audits. It only reads, and shows no user IDs.
- **Why it matters:** one command answers "is the sync healthy?".

### C. Extra: the real backfill into my dev database ✅
- **What we did:** ran the sync for real against SOCO's dev data, with the read-only login, on 1 Oct.
- **Why it matters:** the tests use made-up rows; this proves it works on SOCO's real ones, and starts the year-long copy before SOCO's 90 days run out.
- **Status:** done. 146 + 8 + 12 rows; a second pass copied nothing and duplicated nothing.

### D. Extra: every run written in the run diary ✅
- **What we did:** each 5-minute pass, each daily audit and each lag check now gets a line in the engine's run diary (`ml_job_runs`): when it ran, what it covered, how many rows, and whether it worked. The daily audit also runs last in the 2 AM jobs.
- **Why it matters:** the pack wants every job run recorded (SD-21). A run that quietly stopped shows up as failed instead of vanishing.
- **Status:** done, 1 Oct. → [[Nightly batches]]

> [!note] Since ENG-29 (1 Oct 2026): a fourth source
> The sync now also copies SOCO's **serve log** (`rec_serve_log`), next to activity, orders and served lists ([[ENG-29 - Adapting to the platform as built]], part 7). SOCO hasn't created it yet, so it copies 0 rows. The checklist line 4.10 now expects **4** sources with their first full copy done.

## Result (1 Oct 2026)
- All nine parts are built. The pack's checks (a)–(g) each have a test, and all pass: **16 passed** in the sync's own tests (11 of them against a database).
- The whole test suite passed at the time of the change: **541 passed, 1 skipped**.
- The first real copy of SOCO's data is in my dev engine database, and yesterday's audit passed.

## Decided
| Date | Decision | Why |
|---|---|---|
| 1 Oct 2026 | Read 500 rows per page | The pack sets no size; one page is written and re-read as a whole |
| 1 Oct 2026 | After the backfill, the 5-minute reads start from when it began | Nothing changed during the backfill can be missed |
| 1 Oct 2026 | "Behind" = time since the last good pass started | A quiet collection with no new rows isn't "behind" |
| 1 Oct 2026 | The alert is a marked log line to me, until a channel is chosen | The pack names the person, not the channel |
| 1 Oct 2026 | The audit's day is the India-time day | The nightly jobs run on India time (ENG-07) |
| 1 Oct 2026 | Each copy keeps the whole SOCO row | The audit must compare values exactly |

## Still to do
| What | Waiting on |
|---|---|
| Change times on SOCO's rows, so the 5-minute read sees changes | Aravinth's APP-12 → [[People]] |
| Run the checks on the **test** server, then mark it Passed | The test server and its made-up data (ENG-01, ENG-29) |
| Run the backfill on test and production before SOCO's 90 days run out | Those servers → [[Environments]] |
| Copy SOCO's serve log (`rec_serve_log`) too | ENG-29, and Aravinth creating the collection |
| Use SOCO's `tracking_info` as the order history | ENG-29 |
| Run the sync and audit on a timer on the servers | ENG-07 and the servers |
| Confirm in writing: the audit passed 7 days in a row (for DB-16) | Me, after APP-12 |

## How this connects
- **Before it:** [[ENG-03 - Reading SOCO's data correctly]]
- **Built on:** [[Engine sync]], [[Activity events]], [[Collections]], [[Indexes]], [[Platform Database]], [[Engine Database]], [[Settings file]], [[Logs]]
- **Next:** [[ENG-05 - Same method for each user]]. It gives each user the same one of two methods every time, fairly and permanently.
- **Demo:** [[Demo - ENG-04]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-04.md` in the repo.
