---
tags: [task, step-2]
task: ENG-10
status: Passed
owner: Allen
---
# ENG-10: Interest score on real data

> [!note] Status: **Built** (14 Oct 2026, on my laptop)
> The interest score (M1) now learns from the engine's **own copy** of what people did, using every action and weight in the pack, for both methods. Its official check (all of ENG-11's checks) passes, 11 of 11. It becomes **Passed** once that runs on the test server.

> [!success] Passed (16 Oct 2026)
> Kala: this task's check names no environment, so the run on my laptop is the evidence. Its check is ENG-11's, which passes. It covers this task's own check, not the later ENG-30 changes. → [[Answers 16 Oct]]

> [!tip] Pack v1.4 (15 Oct 2026)
> A purchase now comes off the score only when the order's **status** is Cancelled, Rejected or Returned. The history lines no longer decide it, and "Return Requested" doesn't exist. Taking a purchase off *while a return request is open* is the next step, in [[ENG-30 - Adapting to the October platform facts]]. On dev: 8 of 16 people scored; 2 orders taken back (one returned, one rejected).

> [!tip] 16 Oct 2026: M1 finished to pack v1.4
> - A purchase now comes off **while its return request is open**, and comes back if the request ends without a return. → [[ENG-30 - Adapting to the October platform facts]]
> - Actions on **seed posts** (test data) are left out.
> - Each person's **qualified actions** (last 90 days; not hides, not likes on your own post) are counted once, the same way the ladder counts them, and kept with the score, as Kala asked. Likes on your own posts still count towards *what you're into*; whether they should is a question back to Kala.

> [!tip] 16 Oct 2026 (later): likes on your own posts
> Kala decided: they don't count towards what you're into at all, not just towards the 5 actions. Done; a person who only likes their own posts now gets no score from it.

**In one line:** every night, work out what each person is into, as a share per category, from everything they did on SOCO, counting each thing once and in the right way.

## Why this task
The interest score is the first model and the base of the feed: finding posts (ENG-12, ENG-14), the promoter score (ENG-16) and the feed's order (ENG-19) all read it. The M1 demo built the maths, but read SOCO's live log and knew only five kinds of action. → [[Before Wave 1A - the M1 demo]], [[Build Steps]]

> [!example] The idea in one picture
> A tally sheet per person, one column per category. Every like adds 3 to its post's column, a purchase adds 20, a "hide" takes 5 away. Old ticks fade (method one) or count less once they're in an older week-band (method two). Sign-up interests get a fixed 10 that never fades. At the end, each column is turned into a percentage.

## What came before
- [[ENG-04 - Engine sync]] copies SOCO's activity and orders into the engine every 5 minutes. M1 now reads only those copies. → [[Engine sync]]
- [[ENG-03 - Reading SOCO's data correctly]] and [[ENG-29 - Adapting to the platform as built]] taught the engine SOCO's quirks: categories, undo marks, order history.
- [[ENG-07 - Nightly jobs]] runs it at 2 AM as a "finish first, then swap" batch. → [[Nightly batches]]
- [[ENG-09 - Fallback ladder]] decides who has enough history to use their score.

## Subtasks, one by one
The Build List row's parts (1–9), in its order.

### 1. Each action from one place ✅
- **What it asks:** read everything from the engine's copies, and each kind of action from exactly one place, so nothing counts twice.
- **What we did:** activity (views, clicks, likes, saves, comments, shares, add-to-carts, "not interested" and "hide") comes from the copied activity log; purchases from the copied **orders**, never from the activity log too; business follows from SOCO's follows list. Only real people are scored, not businesses.
- **Why it matters:** if a purchase were counted from the order *and* the activity log, every purchase would count double.
- **Status:** done. **Found and fixed on dev:** most older activity rows don't say who acted (person or business). They were being skipped; now the account id decides.

→ [[Activity events]]

### 2. A view counts once, and only if it lasted ✅
- **What it asks:** a view counts if it was on screen for at least **3 seconds**, and only once per person per post.
- **What we did:** exactly that. If someone views a post several times, the latest proper view counts.
- **Why it matters:** scrolling past something isn't interest, and re-watching shouldn't inflate it.
- **Status:** done. On dev, **no view has an on-screen time yet** (Aravinth's APP-02), so none counts. → [[Aravinth's tasks]]

### 3. The pack's weights ✅
- **What it asks:** view 2, click 5, like 3, save 4, share 4, comment 4, add to cart 10, purchase 20, following a business 5, "not interested" or "hide" −5.
- **What we did:** all ten, read from the settings file. The demo knew only five. → [[Settings file]]
- **Status:** done.

### 4. Purchases, and taking them back ✅
- **What it asks:** a purchase adds 20 when the order is placed. If it's cancelled, rejected or returned, the same 20 comes off, aged from the same moment, so it nets to exactly zero, once. Incognito orders still count for the buyer.
- **What we did:** a reversed order simply adds nothing (+20 and −20 at the same age is zero). Incognito orders count.
- **Status:** done.

### 5. Following a business ✅
- **What it asks:** +5 on the business's category, if it's one of the 23; otherwise nothing.
- **Status:** done.

### 6. "Not interested" and "hide" ✅
- **What it asks:** −5 on the item's category.
- **What we did:** exactly that. "Mute" and "report" don't change the score (they're filters, ENG-08). A "hide" on a *person* is skipped, because a person has no one category.
- **Status:** done.

### 7. Undo ✅
- **What it asks:** an unlike, unsave, uncomment or unfollow removes what the original added, once.
- **What we did:** an undone action, and the undo itself, add nothing.
- **Status:** done.

### 8. The floor, the two methods, and no negatives ✅
- **What it asks:** sign-up interests add 10 each, never fading. Method one fades by half every 30 days; method two counts the last 7 days at 0.5, 8–30 days at 0.3, 31–90 at 0.2. Then any category below 0 is set to 0, and each becomes a share of the total. If everything is 0, store nothing.
- **What we did:** the demo's two methods, unchanged, plus the new "set to 0" rule. A "hide" can now push a category below 0; that's expected, not an error.
- **Status:** done. → [[Two methods per slot]]

### 9. Both methods, named; old unnamed rows removed ✅
- **What it asks:** write both methods for everyone, each row saying its method. Delete old rows with no method name.
- **What we did:** both are written every night; rows with no method are deleted first.
- **Status:** done. → [[Engine Database]]

## Result (14 Oct 2026)
- The official check (all of ENG-11's checks) passes: **11 of 11**. → [[ENG-11 - Interest score checks]]
- The reader's own tests: 15 pass.
- **On SOCO's dev data:** 8 of 15 users now have a score under both methods, and 2 of them now get their own score on the feed (rung 1 of the ladder) for the first time.

## Decided
- **14 Oct 2026:** when someone views a post several times, the latest proper view counts.
- **14 Oct 2026:** activity rows that don't say who acted are counted when the account is a known person.
- **14 Oct 2026:** a "hide" on a person (not a post or product) changes no score.

## Still to do
| What | Waiting on |
|---|---|
| On-screen times on views, so views count | Aravinth, APP-02 → [[Aravinth's tasks]] |
| Change times on activity and orders, so an unlike or a cancellation reaches the engine within 5 minutes | Aravinth, APP-12 |
| Every order status change written to the order's history | Aravinth, APP-08 |
| Fill the category map (42 SOCO names) | Me (ENG-29) |
| Run on the **test** server, then mark Passed | The test server → [[Environments]] |

## How this connects
- **Before it:** [[ENG-09 - Fallback ladder]]
- **Built on:** [[ENG-04 - Engine sync]], [[ENG-07 - Nightly jobs]], [[Activity events]], [[Engine sync]], [[Nightly batches]], [[Two methods per slot]], [[Settings file]], [[Engine Database]]
- **Next:** [[ENG-11 - Interest score checks]]. One script that checks all of this on made-up users, PASS or FAIL.
- **Demo:** [[Demo - ENG-10]]. M1 running on SOCO's real data.
- **Technical version:** `docs/engineering/ENG-10.md` in the repo.
