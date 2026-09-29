---
tags: [task, step-1]
task: ENG-03
status: Built
owner: Allen
---
# ENG-03: Reading SOCO's data correctly

> [!note] Status: **Built** (29 Sep 2026)
> All 7 parts are built, and the task's check **passed on my laptop**. It becomes **Passed** once the same check runs on the test server.

**In one line:** teach the engine exactly how SOCO stores things, so no model ever misses data, misreads it, or counts it twice.

## Why this task
Almost every model reads SOCO's data: interest, retrieval, promoter score, product ranker, fraud. If each one read SOCO's database its own way, they'd each make different mistakes. This task reads it **once, correctly**, and hands every model clean, identical records. → [[Build Steps]]

## What came before
- [[ENG-02 - Service skeleton and settings]] made one part of the engine, *platform*, the only door to SOCO's data. This task decides what comes through that door.
- SOCO's data is messy: the same kind of ID is stored two different ways, dates live in differently named fields, and "active" is spelled differently in different places. → [[Platform Database]]

## Subtasks, one by one
The Build List splits ENG-03 into seven numbered parts (1–7). There are two extras (A and B).

### 1. Every ID written the same way ✅
- **What it asks:** SOCO stores IDs in two formats (a special database format, and plain text). The engine must treat them as one.
- **What we did:** every ID is turned into the same plain-text form as it's read, whichever format it was stored in.
- **Why it matters:** otherwise "user 123" stored one way and "user 123" stored the other would look like two different people, and searches would silently find nothing.
- **Status:** done. On the real data, all 93 follows use plain text, and they read the same as everything else.

### 2. The right field for each fact ✅
- **What it asks:** use exactly the fields the pack names. An order's value is `total_price`, a post's time is `timestamp`, stock is quantity minus reserved, and so on. If a record has no time, work it out from its ID.
- **What we did:** made one clean "record" for each of the 14 kinds of SOCO data (users, businesses, posts, activity, follows, orders, cart lines, products, variants, categories, and the four old recommendation logs). Each fills in only the fields the pack names. A missing time is recovered from the ID, which secretly contains the moment it was created.
- **Why it matters:** every model now reads "order value" from the same place, so there's no chance of one model using the wrong field.
- **Status:** done. All **8,741 real documents** were read with **no failures**.

### 3. Categories must be one of the 23 ✅
- **What it asks:** a post's categories must match one of the pack's 23 categories **by name**. A product's category is found through SOCO's category tree, and its top name must be one of the 23. Anything else is dropped.
- **What we did:** built both rules. Capital letters and extra spaces are ignored, and nothing is guessed: "Fashion" is *not* treated as "Fashion & Apparel".
- **Why it matters:** the models compare interests by category. A made-up or misspelled category would split one interest in two.
- **Status:** done. **But see the warning below: SOCO's products aren't in the 23 yet.**

### 4. "Active" means active, however it's spelled ✅
- **What it asks:** status words are compared ignoring capital letters.
- **What we did:** "Activate", "activate" and "ACTIVATE" are treated as the same. Different words stay different: "Activate" on a product is not the same as "Activated" on a post.
- **Why it matters:** otherwise an active product could be hidden just because of a capital letter.
- **Status:** done.

### 5. One place for each kind of data ✅
- **What it asks:** each kind of data is read from exactly one place. Orders come from orders; likes and views from the activity log; follows from follows.
- **What we did:** wrote down that one place for every kind of data, and made the engine refuse to read a few kinds the pack says are only stored for later.
- **Why it matters:** if purchases were counted from both the orders and the activity log, every purchase would count twice.
- **Status:** done. → [[Event source switch]]

### 6. Switching from the old logs to the new one, day by day ✅
- **What it asks:** views, clicks, requests and feedback are being moved from SOCO's old logs to the engine's new one. For days before the switch date, read the old logs; from the switch date on, read the new one. Never both for the same day.
- **What we did:** built that rule. A 90-day window that crosses the switch reads part from each, with no day missed and no day counted twice.
- **Why it matters:** nothing is lost in the move, and nothing is double-counted during it.
- **Status:** done. The switch date itself is set by ENG-04 (next), once the two logs agree for 7 days in a row. → [[Event source switch]]

### 7. Data the engine must not read ✅
- **What it asks:** a few fields must be ignored: an old interest list, an unused events table, SOCO's own feed score, and the old interest scores (allowed only as a last-resort fallback).
- **What we did:** a check reads the engine's code and fails if any of those fields is used where it shouldn't be.
- **Why it matters:** those fields are stale or belong to SOCO's own feed. Using them would quietly mix old answers into new ones.
- **Status:** done.

### A. Extra: readers that hand over clean records ✅
- **What we did:** two helpers fetch SOCO's data and return the clean records, so no model ever touches a raw SOCO field. One of them handles the day-by-day switch automatically.
- **Why it matters:** the rules in parts 1–7 can't be forgotten, because there's no other way in.

### B. Extra: a full check over the real data ✅
- **What we did:** a script reads every document in SOCO's database through the new records, without changing anything, and reports counts only, no personal details.
- **Why it matters:** the tests use examples; this proves the rules fit the **real** data.
- **Status:** done. 8,741 documents, 0 failures.

## ⚠️ What the real data showed
> [!warning] None of SOCO's 2,011 products is in one of the 23 categories yet.
> SOCO's top-level categories are a different list (e.g. "Fashion" instead of "Fashion & Apparel", "Books" instead of "Books & Education"). By the pack's rule, every product is dropped until **Aravinth fixes the categories (DB-07)**. My code is right; the data isn't ready yet.

Other things to raise with Aravinth:
- The feedback log (`contentfeedbacks`) doesn't exist.
- 6 of 8 orders have no checkout number.
- Cart lines don't carry the list's `request_id` yet (DB-05).

## Result (29 Sep 2026)
- The pack's check, *"read one of each record type, including a follows record with text IDs"*, **passes**.
- All automatic checks pass: **475** on the laptop and **33** against the database.
- The record is in `Tracing/checks/ENG-03_2026-09-29.md`.

## Still to do
| What | Waiting on |
|---|---|
| Re-run the check on the **test** server, then mark it Passed | The test server |
| Move the interest score onto these clean records | ENG-10 |
| Fix the categories; confirm the feedback log | Aravinth → [[People]] |

## How this connects
- **Before it:** [[ENG-02 - Service skeleton and settings]]
- **Built on:** [[Platform Database]], [[Event source switch]], [[Collections]]
- **Next:** [[ENG-04 - Receiving activity events]]. It builds the engine's own event log, and sets the switch date from part 6.
- **Demo:** [[Demo - ENG-03]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-03.md` in the repo.
