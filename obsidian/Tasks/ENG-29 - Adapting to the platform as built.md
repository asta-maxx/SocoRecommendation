---
tags: [task, step-2]
task: ENG-29
status: Built
owner: Allen
---
# ENG-29: Adapting to the platform as built

> [!note] Status: **Built** (1 Oct 2026, on my laptop)
> All eight parts are built and the Build List's checks pass. Three things wait on others: **I** have to fill in the category map (42 SOCO categories don't match yet), **Aravinth** has to create SOCO's serve log, and the made-up test data moves to the test server once it exists. It becomes **Passed** once the checks run there.
>
> **1 Oct 2026, after checking every open question against the pack:** four of this task's questions are answered (3, 4, 5 and 12), so they're off the list. The serve log is now copied every 5 minutes instead of a day late, and a tracking step the engine doesn't recognise now leaves a warning in the log.

> [!tip] Pack v1.4 (15 Oct 2026): the rework on the built tasks
> v1.4 keeps ENG-29's words but its new sister task, [[ENG-30 - Adapting to the October platform facts]], replaces the "Return Requested" parts. The rework list, done on 15 Oct: order history read as events (ENG-03), returns only at "Returned" (ENG-10), the spelling list's first entry and new E-12 tests (ENG-08), and two new checks (ENG-11, 13 of 13). The settings file is now **version 4**. **Still yours to decide:** the category map (42 SOCO names), and the test-account and exemption lists (account ids needed).

**In one line:** the engine learns the quirks of SOCO's real database (its category names, its spellings, how it writes an order's steps, its new serve log) and gets a test database full of made-up SOCO data.

## Why this task
On 29 Sep the pack was reviewed against what SOCO has **actually** built. Rather than ask Aravinth to rebuild things, the engine adapts: 14 app and database tasks became *Not needed*, and their work landed here. The pack keeps ENG-01 to ENG-04 as they were and puts every adaptation in this one task. Serving (ENG-06), the filters (ENG-08), the interest score on live data (ENG-10), the promoter score (ENG-16), the fraud rules (ENG-21) and keeping eligibility current (ENG-27) all build on it. → [[Build Steps]]

> [!example] The idea in one picture
> You've moved into a house someone else built. You don't rebuild the kitchen; you label the drawers in your own words, learn which tap is hot, and keep a spare key for the cleaner. That's this task: the engine's own labels and notes for SOCO as it is.

## What came before
- [[ENG-03 - Reading SOCO's data correctly]] taught the engine to read every kind of SOCO row the same way. It already matched categories by name (and dropped the rest), compared statuses ignoring case, read an order's steps from `tracking_info` and kept post and product ids apart. This task adds the settings-driven parts on top.
- [[ENG-04 - Engine sync]] copies SOCO's activity, orders and served lists into the engine every few minutes. This task adds a fourth thing to copy. → [[Engine sync]]
- [[ENG-02 - Service skeleton and settings]] gave the engine its settings file, where all of this task's lists live, and its log of every settings change. → [[Settings file]]
- [[ENG-07 - Nightly jobs]] gave the 2 AM list of jobs; the category check joined it. → [[Nightly batches]]

## Subtasks, one by one
The Build List splits ENG-29 into eight numbered parts (1–8). There are three extras (A–C).

### 1. A category map, checked every day ✅ built / ⏳ the map is mine to fill
- **What it asks:** the engine scores 23 categories, but SOCO uses its own names ("Fashion", not "Fashion & Apparel"). Keep a map in the settings from SOCO's names to the 23. It must cover every category in use. Every day, report any SOCO category that isn't covered; until it is, things in it are left out of category scoring, **never guessed**.
- **What we did:** the map was already in the settings file (from ENG-03), and it's only trusted if it points at one of the 23. New: a **daily check** that looks at every place SOCO stores a category (post categories, people's interests, business categories, and the top of each product's category) and lists every name that matches neither one of the 23 nor the map. It runs every night at 2 AM, alerts me if anything is unmapped, writes the list into the engine's measurements, and leaves a line in the job diary. A product with no category at all shows up as "(no category id)".
- **Why it matters:** without it, a whole section of SOCO quietly counts for nothing. With it, I see exactly which names need a decision.
- **Status:** the check is done. **Real run, 1 Oct:** **42 names don't match**. The two biggest are product categories called "Menswear catimp…" (2,005 products between them, nearly all of SOCO's); then names like "Fashion", "Sports", "Food" from people's interests. The map is empty, so **filling it is my decision**. The pack's "older seller categories" turned out to be the free-text category on each business and SOCO's category tree (question 12, answered 1 Oct); the check already reads both, so nothing changed.
- → [[Settings file]]

### 2. Spellings and order statuses in the settings ✅
- **What it asks:** compare status words ignoring case and spelling variants ("Activate" and "Activated"), and know the exact stored words for order outcomes, like "Return Requested".
- **What we did:** three lists in the settings file:
  - **Spellings:** "stored word → the word the engine means". Empty today, because SOCO only uses "Activate"; if it starts writing "Activated", one line makes it count. The list of products that may be shown now uses it too.
  - **Order statuses:** the exact stored words (Delivered, Cancelled, Rejected, Return Requested, Returned). Already there from ENG-03.
  - **New: tracking steps.** SOCO writes an order's steps as short sentences: "Order created by Rahul", "Shipped by seller", "Delivered (Urban Vogue Fashion Studio)", "Cancelled by seller". The engine recognises a step by how the sentence **begins** ("order created", "shipped", "delivered"…), ignoring case; if two beginnings fit, the longer one wins. The pack doesn't say how to read these sentences; putting the beginnings in the settings is my choice, so a new wording is a settings change, not a code change.
- **Why it matters:** a status spelled a bit differently must never make a product disappear or an order look undelivered.
- **Status:** done. The settings file is now **version 3**. On SOCO's real orders, **all 14 steps** in 8 orders were recognised.
- **Added 1 Oct 2026 (audit):** if a step's sentence matches none of the beginnings, the engine still keeps it (with no step name) and now also writes a **warning** in the log with the order and the sentence. The API contract says an unknown value is "stored and logged, never rejected"; before, it was only stored, so a new wording could go unnoticed. → [[Logs]]
- → [[Settings file]]

### 3. Lists of exempt and test accounts ✅
- **What it asks:** two lists in the settings: accounts **exempt** from fraud action, and **test** accounts. Each entry says which account, why, until when, and who added it, and every change is logged. Exempt accounts are flagged but never acted on. Test accounts are left out of learning, measurement and fraud.
- **What we did:** the two lists were already in the settings file. New: one small helper that every part of the engine asks "is this a test account?" or "is this account exempt?". An entry counts up to and including its expiry day. Adding or removing one is a settings change, so it's written in the settings change log with who did it. **The interest score now skips test accounts** and says how many it skipped. The front door's "test accounts only" mode (ENG-06) asks the same helper.
- **Why it matters:** Aravinth's checks on the live app use test accounts. Their made-up activity must never teach the models, skew the weekly numbers, or trigger fraud rules.
- **Status:** done. Both lists are empty until the test accounts are named. The weekly measurements (ENG-25), the fraud rules (ENG-21) and the "popular items" step of the plan-B ladder (ENG-09) will use the same helper when they're built. **Answered 1 Oct (question 5):** test accounts are left out of fraud **entirely**; only exempt accounts are "flagged, never acted on". The Build List says so, and it comes first in the pack.

### 4. Each order's history, from its tracking steps ✅
- **What it asks:** SOCO's `tracking_info` (the order's list of steps) is its history: when it was **first** delivered, a return request, a cancellation, and who acted. Cancel reasons are kept but never scored. The sync's own history (ENG-04 part 9) stays as a cross-check, and the daily audit compares the tracking steps.
- **What we did:** when the engine reads an order, it puts the steps in time order, names each one (part 2), and notes who acted when the sentence says "by buyer" or "by seller". It then keeps four times: first delivered, return requested, returned, cancelled. **Who cancelled** comes first from the order's own status fields (the rule in the API contract), and from the step's "by buyer / by seller" when those don't say.
- **Why it matters:** "this order was delivered on 12 Sep and returned on 15 Sep" is what the product ranker, the promoter score and the fraud rules need. Reading it from SOCO's own record is more complete than what the sync happened to see.
- **Status:** done. On SOCO's dev data: 1 delivered order, 1 cancelled by the seller. The sync's own history and the audit were already in place (ENG-04).

### 5. Returns ✅
- **What it asks:** an order that has reached Return Requested or Returned counts as returned. Partial refunds aren't modelled.
- **What we did:** an order counts as returned if its current status says so **or** its history ever had a return request or a return. So an order that was returned and later moved on still counts.
- **Why it matters:** a sale that came back mustn't count as a happy sale.
- **Status:** done. No real order has been returned yet; the made-up data has one.

### 6. Items in the shape the app already uses ✅
- **What it asks:** on the feed, a post that shows a product keeps the **post's** id as the item id, and every item also carries the post id and product id separately, so the two are never confused. Product rails carry product ids.
- **What we did:** ENG-03 already reads them apart, and ENG-06 already returns them apart. The Build List's check for it is now one of this task's tests.
- **Why it matters:** if a post id were read as a product id, a like on a post would count for the wrong thing.
- **Status:** done. **Answered 1 Oct (question 4):** the "item type" word for a post card showing a product is **`product`** (the pack's Capture Register says SOCO's own feed lists write it that way, and SOCO's real clicks on dev agree). The item id and post id are still the post's, and the product id is the product's. The front door (ENG-06) now sends exactly that. → [[Served list record]]

### 7. SOCO's serve log joins the sync ✅ built / ⏳ waits on SOCO
- **What it asks:** SOCO shows engine lists exactly as returned, so there's no "delivered list" record. Instead SOCO keeps a small **serve log** (`rec_serve_log`): one line per list request, saying whether the list came from the engine, a fallback or a cache, whether it worked, and how long it took. Copy it the same way as the served lists.
- **What we did:** the engine can now read a serve-log line, and the sync copies `rec_serve_log` as its **fourth** source, next to activity, orders and served lists. The daily audit checks it too.
- **Why it matters:** this is how we'll know how often SOCO fell back to its own ordering, and how fast the engine looked from SOCO's side (the monitoring in ENG-24).
- **Status:** built and tested on made-up rows (3 copied). On SOCO's dev data it copies **0**, because the collection doesn't exist yet: Aravinth creates it in APP-15. → [[Engine sync]]
- **Fixed 1 Oct 2026 (question 3 answered):** the serve log has no "last changed" time, and at first that meant the 5-minute read couldn't see new lines, so they arrived about a day late. But the pack says SOCO writes **one line per request, once**: lines are never changed afterwards. So the sync now simply carries on from the last line it copied, in the order lines were added, every 5 minutes. Because several SOCO servers write to it, a line can land a few seconds "late"; the sync looks back 2 minutes each time to catch those, and copying a line twice does no harm (the copy is replaced, not doubled). The engine also reads the line's time from its `at` field first, the name the pack gives it (F80). The daily audit compares where the list came from, whether it worked and how long it took.

### 8. A test database full of made-up SOCO data ✅ on the dev cluster / ⏳ the test server
- **What it asks:** fill the engine's test environment with made-up data shaped exactly like SOCO's, in every SOCO collection the engine reads, for the engine tests in ENG-23.
- **What we did:** a set of **56 made-up records** across all **13** SOCO collections the engine reads, written in SOCO's own field names. Each one exists to test one rule: **41 named cases**, such as a hidden post, a private author, a blocked viewer, a test account, an under-18 user, an out-of-stock product, a product spelled "Activated", an order delivered then returned, one cancelled by the seller, a like and its unlike, and three serve-log lines. A script writes them into a test database and reads every one back through the engine's readers. It refuses to write anywhere whose name doesn't contain "test", or into the real databases.
- **Why it matters:** the pack decided there's no SOCO test server. So the engine's failure tests need their own SOCO-shaped data, and the same data every time.
- **Status:** done: "56 documents in soco_engine_test; 41 named cases; all parse". It sits on my **dev** engine cluster for now and moves to the test server when that exists ([[ENG-01 - Engine home and databases]]). One guess in it: the field names of SOCO's `followers` (where blocks live) aren't documented and the collection is empty on dev, so I assumed them (question 16, still open: Aravinth or SOCO's backend code can answer). → [[Environments]]

### A. Extra: settings file version 3 ✅
- **What we did:** adding the tracking steps (part 2) raised the settings file to **version 3**, as every change must. Everything worked out since then is labelled with version 3.
- **Why it matters:** any score can be traced back to the exact settings that made it. → [[Settings file]]

### B. Extra: the category check is a proper nightly job ✅
- **What we did:** the daily check isn't just a log line: its result is saved for each day, and the run is in the job diary like every other job.
- **Why it matters:** a night it didn't run, or a number that grows, is easy to spot. → [[Nightly batches]]

### C. Extra: the test data checks itself ✅
- **What we did:** after writing the made-up data, the script reads every record back through the engine's readers, and fails if any don't read.
- **Why it matters:** the test database can never hold data the engine would reject without us knowing.

## Result (1 Oct 2026)
- All eight parts are built, and every check the Build List names has a test that passes: **14 passed** in this task's own tests (3 of them against a database).
- The whole test suite: **598 passed, 1 skipped**.
- On SOCO's real dev data: the category check runs and finds **42** unmapped names; every one of the 14 order steps is recognised; the sync now has four sources (the serve log is empty until SOCO creates it).
- The made-up SOCO data is in `soco_engine_test`: 56 records, 41 cases, all read cleanly.
- The checklist has a new section 8 (lines 8.1–8.9) for this task.
- **After the audit fixes (1 Oct):** two new checks (a serve-log line that lands late is still copied; an unrecognised tracking step is logged). The whole test suite: **634 passed, 1 skipped**.

## Decided
| Date | Decision | Why |
|---|---|---|
| 1 Oct 2026 | Order steps are recognised by how their sentence begins, from a list in the settings | SOCO's steps are free text; the pack doesn't say how to read them. A setting keeps a new wording out of the code |
| 1 Oct 2026 | Who cancelled: the order's status fields first, the step's "by buyer / by seller" second | The API contract's rule uses the status fields; the step fills the gaps |
| 1 Oct 2026 | An account entry counts up to and including its expiry day | "Expiry 31 Dec" should still count on 31 Dec |
| 1 Oct 2026 | The made-up data lives on the dev engine cluster until the test server exists | The test server isn't built yet (ENG-01) |
| 1 Oct 2026 | The made-up `followers` records assume `userId`, `followerId`, `status: "blocked"` | The real fields aren't documented (question 16, still open) |
| 1 Oct 2026 | The serve log is copied every 5 minutes in the order lines were added, looking back 2 minutes each time | It's written once per request and never changed (API contract 4.3), so it needs no "last changed" time (question 3) |
| 1 Oct 2026 | A post card showing a product is item type `product` | Capture Register F10 and X-16 (question 4) |
| 1 Oct 2026 | Test accounts are left out of fraud entirely | Build List ENG-29 and X-21, which outrank the Fraud Policy (question 5) |

> [!note] Where "the 23" come from (15 Oct 2026)
> The pack says "the 23 categories" many times but never lists them. The engine's list comes from the SOCO app's own post-category picker (saved during the M1 demo). Asked Aravinth to confirm it's still the app's current list.

## Still to do
| What | Waiting on |
|---|---|
| Fill the category map (42 names, including the two "Menswear catimp…" product categories) | **Me**: a decision per name |
| SOCO's serve log (`rec_serve_log`) to exist | Aravinth, APP-15 → [[People]] |
| The real field names in `followers` | Question 16: Aravinth or SOCO's backend code |
| Leave test accounts out of "popular items" in the plan-B ladder | ENG-09 |
| Leave test accounts out of the weekly measurements | ENG-25 |
| Leave test accounts out of the fraud rules (exempt accounts: flag, never act) | ENG-21 |
| Move the made-up data to the test server and re-run the checks there, then mark Passed | The test server ([[ENG-01 - Engine home and databases]]) |

## How this connects
- **Before it:** [[ENG-07 - Nightly jobs]] (built just before it; in the pack it builds on ENG-03 and ENG-04)
- **Built on:** [[ENG-03 - Reading SOCO's data correctly]], [[ENG-04 - Engine sync]], [[Settings file]], [[Engine sync]], [[Nightly batches]], [[Platform Database]], [[Engine Database]], [[Environments]], [[Logs]]
- **Next:** [[ENG-08 - Filters]]. It applies the rules no model can override (blocks, hidden posts, out of stock), and its tests run on this task's made-up data.
- **Demo:** [[Demo - ENG-29]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-29.md` in the repo.
