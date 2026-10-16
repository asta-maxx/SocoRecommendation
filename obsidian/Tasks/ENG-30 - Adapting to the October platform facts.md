---
tags: [task, step-3]
task: ENG-30
status: In progress
owner: Allen
---
# ENG-30: Adapting to the October platform facts

> [!note] Status: **In progress** (15 Oct 2026)
> New in pack v1.4. Three of its eleven points are done, with the rework of the built tasks: order history read as events (5), returns only at "Returned" (6), and the E-12 check (11). The rest is still to build.

> [!tip] 16 Oct 2026
> The order-history list gained the app's other lines ("Order placed", "Rejected by buyer", replacements and exchanges, information only). Kala settled the commission defaults (on 10%, no minimum). ENG-30 is Passed only once the ENG-03, 04, 10, 11 and 29 checks re-run on its code. → [[Answers 16 Oct]]

**In one line:** SOCO's app team explained how their database really works (8–13 Oct), and Kala checked it (13–14 Oct). This task makes the engine fit those facts, without asking the app to change anything.

## Why this task
v1.4 keeps the words of ENG-01 to ENG-11 and ENG-29, and puts every correction here instead, naming exactly which old sentences it replaces. The promoter score (ENG-16), opportunities (ENG-18), the fraud rules (ENG-21) and the final checks (ENG-23) need it. → [[The Pack]], [[Build Steps]]

> [!example] The idea in one picture
> Like [[ENG-29 - Adapting to the platform as built]], a second round of "learning the house": this time which drawer holds the return slips, how to read the order diary, and that a person and their shop are the same person.

## What came before
- [[ENG-29 - Adapting to the platform as built]] did the first round (29 Sep facts).
- [[ENG-10 - Interest score on real data]] built the interest score; point 10 here changes how it treats returns.

## Subtasks, one by one

### 5. Order history as events ✅ (15 Oct)
- **What it asks:** read each line of an order's history ("Order created by …", "Delivered (…)", "Refund of ₹…", "Returned to seller") as an event, from its opening words. The order's **status** is the truth; a history line never changes it. Anything unrecognised is reported, never guessed; a history that contradicts itself is flagged.
- **What we did:** a ten-entry word list in the settings file (version 4). Every history line on SOCO's dev database is recognised.
- **Why it matters:** the promoter score and fraud rules time things from "Delivered", and must never mistake a refund note for a return.
- **Status:** done. → [[Settings file]]

### 6. Returns only at "Returned" ✅ (15 Oct)
- **What it asks:** there is no "Return Requested" status. An order is returned only when its status is "Returned"; its time comes from the order's return details.
- **What we did:** exactly that, everywhere: the order record, the interest score and the ladder's action count.
- **Status:** done.

### 11. The "pushed down or removed" rule, checked ✅ (15 Oct)
- **What it asks:** a check only: E-12 hides only deranked and removed posts.
- **What we did:** tests for ok, review, fix requested and no mark at all.
- **Status:** done. → [[ENG-08 - Filters]]

### 1–4 and 7–10. Still to build ⏳
| # | In plain words |
|---|---|
| 1 | Who promoted an order: the order says; if not, the post's author |
| 2 | A person and their stores count as one person (for self-purchase) |
| 3 | A repost leads back to the original post (up to 10 steps; loops stop) |
| 4 | Commission settings for opportunities, layered platform → store → product |
| 7 | Copy SOCO's return requests (no addresses, phones or photos), and treat a copy over 24 hours old as stale |
| 8 | Each product's return window (7 days if unknown, plus 2 days' buffer) |
| 9 | Posts tagged as seed data are test data |
| 10 | The interest score takes a purchase off while a return request is open, and puts it back if the request ends without a return |

## Result (15 Oct 2026)
- All automatic checks pass (601). The interest-score check script: 13 of 13.
- The engine's read-only login can see the two new collections (`returnrequests`, `commissionconfigs`) on dev.

## Still to do
| What | Waiting on |
|---|---|
| Points 1–4 and 7–10 | Me |
| Run its check on the **test** server | The test server → [[Environments]] |

## How this connects
- **Before it:** [[ENG-29 - Adapting to the platform as built]]
- **Built on:** [[ENG-10 - Interest score on real data]], [[ENG-03 - Reading SOCO's data correctly]], [[Engine sync]], [[Settings file]]
- **Next:** [[ENG-12 - Candidate sources]]. Finding candidate posts (M2).
- **Technical version:** `docs/engineering/ENG-30.md` in the repo.
