---
tags: [task, step-2]
task: ENG-09
status: Built
owner: Allen
---
# ENG-09: Fallback ladder

> [!note] Status: **Built** (14 Oct 2026, on my laptop)
> All five rungs work, plus "rung 3 empty", and every feed list now says which rung it used. The Build List's check passes in the tests and on real databases. It becomes **Passed** once the check runs on the test server (being set up; decided 14 Oct).

**In one line:** when the engine doesn't know someone well enough yet, or its own data is old or out of reach, decide what to use instead of their interest score, and say on every list which choice was made.

## Why this task
The interest score (M1) only means something once a person has done a few things. On day one almost nobody has. This task gives every user *something* sensible, in a fixed order, and labels it honestly. Serving a list ([[ENG-06 - Serve a recommendation list]]) needed it to report its "plan B" step, and the interest-score check script (ENG-11) tests it. → [[Build Steps]]

> [!example] The idea in one picture
> A shop assistant suggesting things. For a regular, they go by what the regular usually buys (rung 1). For a new customer who filled in a "what do you like?" card, they go by the card (rung 2). For a stranger, they point to what's selling well this month (rung 3). If the regular's notes are out of date, or the notebook is locked away, they use last year's notes instead (rungs 4 and 5). And if the shop is brand new, they just show the newest arrivals ("rung 3 empty").

## What came before
- The **M1 demo** already had a ladder, but an older, simpler one: no "5 actions" test, no use of SOCO's old score, and nothing told serving about it. → [[Before Wave 1A - the M1 demo]]
- [[ENG-03 - Reading SOCO's data correctly]] taught the engine to read a user's sign-up interests and match them to the 23 categories.
- [[ENG-04 - Engine sync]] gave the engine its own copy of what people did. The ladder counts actions from that copy. → [[Activity events]]
- [[ENG-07 - Nightly jobs]] gave the "finish first, then swap" overnight batches. Rung 3's numbers are one of them now. → [[Nightly batches]]
- [[ENG-05 - Same method for each user]] decides which of the two interest methods each user gets. The ladder looks at that one. → [[Two methods per slot]]

## Subtasks, one by one
The Build List lists five rungs, then four rules around them (1 to 8 below). One extra (A).

### 1. Rung 1: a regular with a fresh score ✅
- **What it asks:** if the person did at least **5 qualified things in the last 90 days**, and their score was worked out in the **last 48 hours**, use their score.
- **What we did:** the engine counts from its own copy: views of at least **3 seconds** (one per post), clicks, likes, saves, comments, shares, add-to-carts, orders that weren't cancelled or returned, and businesses they followed. It stops counting at 5, since that's all it needs to know. Anything later undone doesn't count. Then it checks the score is under 48 hours old and adds up properly.
- **Why it matters:** a score built on 1 or 2 actions is mostly noise. Five is the pack's line.
- **Status:** done.

→ [[Activity events]]

### 2. Rung 2: a newcomer who picked interests ✅
- **What it asks:** fewer than 5 actions, but they picked interests at sign-up: use those, plus whatever they've done.
- **What we did:** the nightly score already *is* "sign-up interests plus actions", so if it exists and is fresh, that's used. If not, the picked interests are shared out equally.
- **Why it matters:** this is most people on launch day: signed up, picked a few interests, done nothing yet.
- **Status:** done. On dev today, 6 of the 15 users land here.

### 3. Rung 3: a stranger: what's popular ✅
- **What it asks:** fewer than 5 actions and no sign-up interests: use what's popular across SOCO over the last **30 days** (qualified views per category).
- **What we did:** a new **nightly job** counts it, from the engine's copy, leaving out test accounts and counting each person's view of a post only once. A request just reads the latest finished count; it never works it out on the spot.
- **Why it matters:** counting the whole platform on every request would be far too slow (the engine has 0.25 seconds per request), and the pack says requests never calculate.
- **Status:** done. The job ran on dev on 14 Oct and found **0** qualified views (see below).

→ [[Nightly batches]]

### 4. Rung 3 empty: a brand-new shop ✅
- **What it asks:** if even "popular" has nothing, show the newest suitable posts, and log it as "rung 3 empty". No rung ever returns nothing.
- **What we did:** exactly that. The list labels it `rung_3_empty`.
- **Why it matters:** a new platform must still show a feed.
- **Status:** done. On dev today, 7 users land here, because there are no qualified views yet.

### 5. Rungs 4 and 5: SOCO's old score ✅
- **What it asks:** for a regular whose score is **too old or broken** (rung 4), or when the **engine's own database can't be read** (rung 5), use SOCO's old interest score. If there isn't one, drop to rung 3. Log the two separately.
- **What we did:** SOCO keeps an old score on each user (`interestScores`). The engine reads it, keeps only the 23 categories, and turns it into shares. Rung 4 is logged as a "refresh problem" (the overnight job didn't run), rung 5 as a "serving problem" (the database is down). A regular with no score at all also counts as rung 4.
- **Why it matters:** an out-of-date score or a database hiccup should never leave someone with a worse feed than SOCO's old one.
- **Status:** done. On dev, 1 user gets SOCO's old score (Fashion & Apparel), and 1 has none, so drops to rung 3 (empty).

### 6. The rung goes on every list ✅
- **What it asks:** report the rung on the answer and on the list's receipt.
- **What we did:** every feed list now carries a `fallback_step`: empty for rung 1, otherwise a name like `rung_2`, `rung_3_empty` or `rung_4_to_3` (rung 4 wanted, but fell to 3). The receipt says the same. Product lists don't use the interest score, so they don't walk this ladder. → [[Served list record]]
- **Why it matters:** anyone reading the numbers later can tell a real personal list from a stand-in.
- **Status:** done. The pack only says it's "a string"; the names were my choice (14 Oct).

### 7. A newcomer isn't a failure ✅
- **What it asks:** rungs 2 and 3 for a new user are normal ("cold start"), counted apart from real failures (ENG-24).
- **What we did:** each receipt says `cold_start: true` for rungs 2 and 3, and false for 4 and 5.
- **Why it matters:** otherwise launch day would look like the engine failing for everyone.
- **Status:** done. The weekly count itself is ENG-24.

### 8. Never credit a method that didn't run ✅
- **What it asks:** a plan-B list must never count as a result for the method the user was meant to get.
- **What we did:** each receipt says `method_served: true` only at rung 1.
- **Why it matters:** the comparison of the two methods (ENG-26) would be wrong otherwise.
- **Status:** done. → [[Two methods per slot]]

### A. Extra: a script that shows the ladder ✅
- **What we did:** `scripts/show_ladder.py` walks the ladder for real users and counts how many land on each rung. It only reads.
- **Why it matters:** proof on real data, not just on test examples.

## Result (14 Oct 2026)
- The Build List's check, *"Test users for each rung get the right rung reported"*, passes: one test user per rung in the ladder's own tests (20 pass), every rung reported on the answer and receipt (9 pass), and one user per rung on real databases (4 pass).
- The whole set of automatic checks: **641 passed, 1 skipped** (the same skip as before).
- SOCO's 15 dev users: rung 2: 6, rung 3 empty: 7, rung 4: 1, rung 4 → 3 empty: 1.

> [!warning] Why rung 3 is empty on dev
> None of the 17 views in the engine's copy has an **on-screen time** (`dwell_ms`), so none counts as a qualified view. Aravinth's APP-02 adds it; it's reported built, but no view on dev has it yet. Also, the copy's newest activity is from 24 Sep, because the copying job hasn't run since 1 Oct. → [[Aravinth's tasks]]

## Decided
- **14 Oct 2026:** "qualified actions" are the things M1 scores *up* (views of 3+ seconds, clicks, likes, saves, comments, shares, add-to-carts, orders kept, business follows). "Not interested" and "hide" don't count, because they lower a score.
- **14 Oct 2026:** someone with 5+ actions but no score at all is rung 4, like an out-of-date score.
- **14 Oct 2026:** rung 3's popularity is a nightly batch, kept in the engine's measurements drawer, not counted on each request.
- **14 Oct 2026:** the step names: `rung_2`, `rung_3`, `rung_4`, `rung_5`, `rung_4_to_3`, `rung_5_to_3`, plus `_empty` when "popular" had nothing.

## Still to do
| What | Waiting on |
|---|---|
| ~~Interest scores from the engine's own copy, so rungs 1 and 2 use live scores~~ | Done 14 Oct → [[ENG-10 - Interest score on real data]] |
| Real views with on-screen time on dev, so rung 3 has numbers | Aravinth's APP-02 data; the copying job running → [[Aravinth's tasks]] |
| Count newcomers apart from failures each week | ENG-24 |
| ~~The interest-score check script tests the rungs too~~ | Done 14 Oct (check 10) → [[ENG-11 - Interest score checks]] |
| Run the check on the **test** server, then mark Passed | The test server → [[Environments]] |

## How this connects
- **Before it:** [[ENG-08 - Filters]]
- **Built on:** [[ENG-03 - Reading SOCO's data correctly]], [[ENG-07 - Nightly jobs]], [[Nightly batches]], [[Activity events]], [[Engine sync]], [[Two methods per slot]], [[Settings file]], [[Platform Database]], [[Engine Database]]
- **Next:** [[ENG-10 - Interest score on real data]]. It moves the interest score onto the engine's own copy, so rungs 1 and 2 use live scores.
- **Demo:** [[Demo - ENG-09]]. How to show each rung, and the ladder on SOCO's real users.
- **Technical version:** `docs/engineering/ENG-09.md` in the repo.
