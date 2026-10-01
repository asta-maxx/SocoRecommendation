---
tags: [task, step-2]
task: ENG-06
status: In progress
owner: Allen
---
# ENG-06: Serve a recommendation list

> [!note] Status: **In progress** (1 Oct 2026)
> The engine now has its serving door. SOCO's backend can ask it for a list, gets one back in well under a fifth of a second, and every list is written down first. But the list is a **stand-in**: the newest suitable posts (or products), not yet a ranked list. The real ordering, the full safety filters and the "plan B" ladder are later tasks. Until then, both surfaces stay **off** in production.

**In one line:** when SOCO's app needs a For You feed or a "you may also like" rail, it asks the engine; the engine answers with a list, and keeps a receipt of exactly what it answered.

## Why this task
This is the moment the engine starts **doing** something for shoppers. Everything before it (a home, settings, reading SOCO's data, copying it, choosing a method per user) was preparation. Aravinth's side of the call (APP-15) waits on this door. So do the load test (ENG-20) and the go-live rule (ENG-24), which decides when each surface is switched on. → [[Build Steps]]

## What came before
- [[ENG-02 - Service skeleton and settings]] gave the engine its settings file, which the engine re-reads every 30 seconds. The on/off switch for each surface lives there, so it can be flipped without a restart. → [[Settings file]]
- [[ENG-03 - Reading SOCO's data correctly]] taught the engine to read SOCO's posts and products. Every list is built from those readers. → [[Platform Database]]
- [[ENG-04 - Engine sync]] copies SOCO's activity into the engine. The receipts this task writes go into the same drawer, `ml_events`, so later tasks can join "what we showed" to "what the person did". → [[Engine sync]], [[Collections]]
- [[ENG-05 - Same method for each user]] decides which of the two methods each user gets, per slot. This task stamps that choice on every list.

> [!example] The idea in one picture
> A waiter (SOCO's backend) asks the kitchen (the engine) for today's tasting menu for table 12. The kitchen sends the plates in order, and **before** they leave, files a copy of the order ticket: who it was for, which chef's style, what was on the pass but not sent out. If the kitchen is closed, it says so at once ("503"), and the waiter serves the house menu instead (SOCO's own ordering).

## Subtasks, one by one
The Build List row has eleven parts (1–11). There are three extras (A–C).

### 1. The serving password ✅
- **What it asks:** every request must carry the engine's serving password (`INGEST_TOKEN`) in its header. Without it, or with the wrong one, refuse.
- **What we did:** the engine checks the password on every request, before anything else, and answers **401** if it's missing or wrong. If the engine itself was started without a password, it refuses everyone rather than letting everyone in.
- **Why it matters:** only SOCO's backend may ask for lists. A door that opens when the password is forgotten isn't a door.
- **Status:** done. Tested: no password and a wrong one both get 401. → [[Secrets and passwords]]

### 2. Checking the request ✅
- **What it asks:** the request says who it's for (`user_id`), which surface (`feed` or `product`; anything else is refused), which page, how many items (1 to 50), the app session, and, on product, which product is being viewed.
- **What we did:** a bad request gets **400** with a short code saying what was wrong: a surface like `opportunity`, a page of 0, a limit of 51, or a product request with no product. If `user_id` is ever missing, the user gets the default method in every slot, as the pack says. A missing session id isn't refused: the backend's own task says it may be empty.
- **Why it matters:** the backend learns at once what it did wrong, and nothing odd is ever written down.
- **Status:** done. 6 bad-request cases tested, and none of them left a receipt.

### 3. The answer ✅ (the "plan B" step waits on ENG-09)
- **What it asks:** the answer carries a fresh ID for the list (`request_id`), a label saying which settings version and which method in each slot made it (`policy_id`), the model and settings versions, which plan-B step was used (if any), whether it's an exploration list, and the items, numbered from 1.
- **What we did:** exactly those fields. The label reads like `cfg2.interest-recency_decay.promoter_score-cohort_percentile`: settings version 2, the *recency decay* interest method, the *cohort percentile* promoter method. It names the methods rather than numbering them, so old labels still make sense after a method is swapped out later (ENG-26). The pack's API contract shows numbers in its example, but the Build List, which comes first, asks for names. The feed uses two slots (interest and promoter score); product rails use one (product ranking). The plan-B field is always empty for now, because nothing is ranked yet, so no plan B is needed.
- **Why it matters:** the label is how every later measurement knows which method a shopper saw. The list ID is how a tap is joined back to the list it came from.
- **Status:** done. The plan-B step arrives with ENG-09 (the fallback ladder).

### 4. The receipt ✅
- **What it asks:** for every list, write one record (called E1) in `ml_events`: who, which surface, the session, the label, the exact time, everything that **could** have been shown (never sent to the app), exactly what **was** shown, the settings version, each slot's intended method, and a sample of items for the models to learn from.
- **What we did:** the receipt is written **before** the answer leaves. If it can't be written, the engine answers 503 and sends no list. No receipt, no list. The "what was shown" part is the very same list that goes out, so the two can't differ. The sample holds every shown item, plus 1 in 10 of the others at random, plus everything on an exploration list. The receipt also says `interim_newest_first`, so nobody mistakes today's stand-in lists for ranked ones.
- **Why it matters:** this receipt is the engine's memory of what it did. Every comparison between the two methods starts from it.
- **Status:** done. On my laptop, 19 of 19 receipts matched their answers, on both surfaces. → [[Activity events]]

### 5. Pages 🔨 (skipping already-seen items waits on ENG-19)
- **What it asks:** each page is a separate request. The ranking decides what a page holds, and later pages leave out what the user was shown in the last 24 hours.
- **What we did:** page 2 with 10 items holds items 11 to 20 of the stand-in order, numbered 1 to 10 again. A short last page comes back short rather than padded.
- **Why it matters:** scrolling must keep giving new things, without repeats.
- **Status:** paging works. "Leave out the last 24 hours" belongs to the ranking layer (ENG-19), which isn't built.

### 6. Off, internal, live ✅
- **What it asks:** each surface has a switch: **off** (answer 503, so SOCO shows its own list), **internal** (only the test accounts named in the settings get engine lists; everyone else gets 503), or **live**.
- **What we did:** the engine reads the switch on every request. Internal mode checks the test-account list, and an entry past its expiry date no longer counts. Changing the switch is a normal settings change: new version number, picked up within 30 seconds, written in the change diary.
- **Why it matters:** this is the engine's emergency brake, and the way to try it on real production with a few test accounts before any shopper sees it.
- **Status:** done. Both surfaces are **off** in the real settings, as the pack requires until the rankings exist. Tested: off gives 503; internal serves a listed account and refuses others and expired entries. → [[Settings file]]

> [!warning] Off is the safe default
> 503 sounds like an error, but here it's a polite "not me, use your own list". SOCO's backend falls back to its own ordering at once, and the shopper never notices.

### 7. Exploration ✅
- **What it asks:** on 5 in 100 feed requests, keep the top 3 as ranked and shuffle the rest, and mark the list as exploration. Never on product rails.
- **What we did:** a coin is tossed for each feed request, separately from the method choice. On an exploration list, positions 1–3 stay put and 4 onwards are shuffled. The list and its receipt say so.
- **Why it matters:** without a little shuffling, items low on the list never get a chance to be seen, so the models never learn whether they were good.
- **Status:** done. **My choice:** the pack says shuffle "among eligible items"; I shuffle **within the page**, so a page always holds the same items and scrolling stays steady. Tested: top 3 kept, product never explores.

### 8. If a database can't be read ✅
- **What it asks:** answer with an error at once. Never retry inside a request.
- **What we did:** if SOCO's database can't be read, or the receipt can't be saved, the answer is **503** straight away, and the log says why (with the list ID, never a password).
- **Why it matters:** SOCO's backend waits at most a quarter of a second. Retrying would just make the shopper wait for SOCO's own list anyway.
- **Status:** done. Tested: one attempt, then 503. → [[Logs]]

### 9. The stand-in order ✅ laptop / ⏳ the real ranking
- **What it asks:** until the feed ranking (ENG-19) and the product ranker (ENG-17) exist, keep both surfaces off in production; on test, return suitable posts newest first, so Aravinth can test his side.
- **What we did:** feed: suitable posts, newest first. Product: suitable products, newest first, never the product being viewed. The pack only describes the feed's stand-in; I chose the same for products, which is also the product ranker's own last resort.
- **Why it matters:** Aravinth can build and test APP-15 against a real door now, instead of waiting for the models.
- **Status:** done on my laptop: 8 posts on the feed, 10 products on a rail. Real ranking waits on ENG-17 and ENG-19.

### 10. Error messages ✅
- **What it asks:** 400 for bad input, 401 for a bad password, 503 for off or a database fault, always shaped `{"error": "<code>", "detail": "<text>"}`.
- **What we did:** every refusal has that shape, with one short code (`invalid_surface`, `unauthorized`, `surface_off`, `database_unavailable`…) and a sentence.
- **Why it matters:** Aravinth's code can log and fall back by the code, without parsing sentences.
- **Status:** done.

### 11. Items in the app's shape ✅ shape / ⏳ ENG-29 and a question for Kala
- **What it asks:** items look the way the app already expects. A post card that shows a product keeps the **post's** ID as its item ID, and every item also carries its post ID and product ID separately, so one is never mistaken for the other.
- **What we did:** a post card: item ID = post ID, type `post`, plus the product it shows (or empty). A product card: type `product`, post ID empty.
- **Why it matters:** if a post ID were read as a product ID, a tap would be credited to the wrong thing, and the models would learn nonsense.
- **Status:** the shape is done. **Open question for Kala:** for a post card showing a product, does the app expect type `post` or `product`? SOCO's own lists seem to use `product`. It's a one-line change once she answers. The full adapter is ENG-29.

### A. Extra: a stand-in safety check, until ENG-08 ✅
- **What we did:** a post is shown only if it's public, not hidden, and not rejected, removed, deranked or blocked. A product only if it's active and in stock.
- **Why it matters:** even the stand-in list must never show something SOCO has hidden or can't sell. The full rule set (blocks, mutes, private accounts, stock per variant…) is ENG-08. → [[Platform Database]]

### B. Extra: a try-it script ✅
- **What we did:** one command that asks a running engine for 20 lists, times them, and checks every receipt against its answer. It prints item IDs only, never the password.
- **Why it matters:** the Build List's check, in one command, on any machine.

### C. Extra: section 6 of the checklist ✅
- **What we did:** six lines in the checklist script: the contract tests, the database tests, feed and product over the network, a wrong password, and switching the feed off without a restart.
- **Why it matters:** re-checking this task is part of re-checking everything.

## Result (1 Oct 2026)
- **Tests:** 16 of 16 pass: 14 without a database, 2 on made-up SOCO data. The whole set without a database: 530 pass, 1 skipped (re-run after the method-name change).
- **Over the network, laptop to Atlas, on SOCO's dev data** (8 posts, 2,011 products):

  | Surface | Items | 95 in 100 answers within | Receipts matching |
  |---|---|---|---|
  | feed | 8 | 69 ms (re-run: 69 ms) | 19 of 19 |
  | product | 10 | 104 ms (re-run: 93 ms) | 19 of 19 |

  The 200 ms limit is officially measured on the test server; my laptop already beats it with room to spare, even with the trip to Atlas.
- Asking for the `opportunity` surface gets 400. Switching the feed off without a restart gets 503 within 30 seconds, while product keeps serving.

## Decided
| Date | Decision | Why |
|---|---|---|
| 1 Oct 2026 | Build now, to the row's own stand-in rule, instead of waiting for ENG-09 and ENG-29 | Aravinth needs a real door to build APP-15 against |
| 1 Oct 2026 | Product rails, for now: suitable products newest first, the viewed product left out | The pack only gives the feed's stand-in; this matches the product ranker's own last resort |
| 1 Oct 2026 | Plan-B step left empty; each slot records the method it **would** use | No score is read, so no plan B is used |
| 1 Oct 2026 | Exploration shuffles within the page | Pages stay steady while scrolling |
| 1 Oct 2026 | The list's label names each method (`interest-recency_decay`), not its number | The Build List (ENG-05, ENG-26) outranks the API contract's numbered example; names stay readable after a swap |
| 1 Oct 2026 | A post card is type `post`, with its product alongside | Until Kala says what the app expects |
| 1 Oct 2026 | Both surfaces off in the real settings | The pack: off in production until the rankings exist |

## Still to do
| What | Waiting on |
|---|---|
| The full safety filters | ENG-08 |
| The plan-B ladder, reported on each list | ENG-09 |
| Real feed ranking, and skipping what was shown in the last 24 hours | ENG-19 |
| Real product ranking | ENG-17 |
| Type `post` or `product` for a post card showing a product | Kala, in writing; then ENG-29 |
| The check on the **test** server | The test server → [[Environments]] |
| Switch the surfaces live | ENG-24's go-live rule |

## How this connects
- **Before it:** [[ENG-05 - Same method for each user]]
- **Built on:** [[Settings file]], [[Platform Database]], [[Engine Database]], [[Collections]], [[Activity events]], [[Engine sync]], [[SOCO_BE]], [[Secrets and passwords]], [[Logs]]
- **Next:** [[ENG-07 - Nightly jobs]]. It runs the overnight work (scores and batches) that a real ranking will read from.
- **Demo:** [[Demo - ENG-06]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-06.md` in the repo.
