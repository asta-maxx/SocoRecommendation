---
tags: [task, step-2]
task: ENG-06
status: In progress
owner: Allen
---
# ENG-06: Serve a recommendation list

> [!note] Status: **In progress** (1 Oct 2026)
> The engine now has its serving door. SOCO's backend can ask it for a list, gets one back in well under a fifth of a second, and every list is written down first. Since 1 Oct the **full safety rules** (ENG-08) decide what may be shown, and every item is checked once more just before the answer leaves. But the order is still a **stand-in**: the newest suitable posts (or products), not yet a ranked list. The real ordering and the "plan B" ladder are later tasks. Until then, both surfaces stay **off** in production.
>
> **On SOCO's dev data today:** the feed gives 3 posts; the product rail gives **none**, because every seller on dev has no status, and the rules treat that as "not active". That's a question for Aravinth (question 17), not an engine bug.

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

> [!note] A missing session id: my choice (1 Oct 2026)
> The API contract calls the session id "required", but its own list of reasons to refuse a request (400) leaves it out, and Aravinth's task says it may be empty. The pack doesn't say what to do, so the engine accepts the request and writes "no session" on the receipt.

### 3. The answer ✅ (the "plan B" step waits on ENG-09)
- **What it asks:** the answer carries a fresh ID for the list (`request_id`), a label saying which settings version and which method in each slot made it (`policy_id`), the model and settings versions, which plan-B step was used (if any), whether it's an exploration list, and the items, numbered from 1.
- **What we did:** exactly those fields. The label reads like `cfg2.interest-recency_decay.promoter_score-cohort_percentile`: settings version 2, the *recency decay* interest method, the *cohort percentile* promoter method. It names the methods rather than numbering them, so old labels still make sense after a method is swapped out later (ENG-26). The pack's API contract shows numbers in its example, but the Build List, which comes first, asks for names. The feed uses two slots (interest and promoter score); product rails use one (product ranking). The plan-B field is always empty for now, because nothing is ranked yet, so no plan B is needed.
- **Why it matters:** the label is how every later measurement knows which method a shopper saw. The list ID is how a tap is joined back to the list it came from.
- **Status:** done. The plan-B step arrives with ENG-09 (the fallback ladder).

### 4. The receipt ✅
- **What it asks:** for every list, write one record (called E1) in `ml_events`: who, which surface, the session, the label, the exact time, everything that **could** have been shown (never sent to the app), exactly what **was** shown, the settings version, each slot's intended method, and a sample of items for the models to learn from.
- **What we did:** the receipt is written **before** the answer leaves. If it can't be written, the engine answers 503 and sends no list. No receipt, no list. The "what was shown" part is the very same list that goes out, so the two can't differ. The receipt also says `interim_newest_first`, so nobody mistakes today's stand-in lists for ranked ones.
  - **Each slot's method** is a short list, one line per slot: which slot, which method, which plan-B step (field `slot_methods`).
  - **What was passed over** (field `scored_not_served`): on about **1 list in 10**, picked at random, and on **every** exploration list, the receipt lists every item the engine considered, with its place, its score and whether it was shown. On the other 9 in 10 it's empty. The score itself is empty until the real rankings exist; the item's place in the stand-in order sits beside it.
- **Why it matters:** this receipt is the engine's memory of what it did. Every comparison between the two methods starts from it, and "what was passed over" is how we'll learn whether the engine skipped good items.
- **Status:** done. On my laptop, 19 of 19 feed receipts matched their answers. → [[Activity events]], [[Served list record]]

> [!note] Fixed on 1 Oct 2026 (audit)
> Two field names on the receipt didn't match the pack's Capture Register. The per-slot methods were one block keyed by slot, called `slots`; the register asks for a list called `slot_methods` (F71). And the "passed over" items were on **every** receipt, called `scored_sample`; the register asks for `scored_not_served` on about 1 in 10 receipts, plus every exploration one (F72). Both now follow the register, and a new test sends 400 requests to check the 1 in 10.

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
- **Status:** done. **My choice:** the pack says shuffle "among eligible items"; I shuffle **within the page**, so a page always holds the same items and scrolling stays steady. Checked against the pack again on 1 Oct (question 15): it stays a choice the pack allows. Tested: top 3 kept, product never explores.

### 8. If a database can't be read ✅
- **What it asks:** answer with an error at once. Never retry inside a request.
- **What we did:** if SOCO's database can't be read, or the receipt can't be saved, the answer is **503** straight away, and the log says why (with the list ID, never a password).
  - **No hidden retries.** The database library quietly retries a failed read once by itself unless told not to. It's now told not to, on both connections (fixed 1 Oct 2026).
  - **A stopwatch on every request.** The whole request (all reads and the receipt) must finish within a time limit, or it's a 503. On the servers the limit is a quarter of a second (250 ms), the same time SOCO's backend waits before giving up; on my laptop, far from the database, it's 2 seconds. The pack doesn't give the engine its own limit; I chose SOCO's, because a list finished after SOCO has given up is never shown, and its receipt would describe a list nobody saw.
  - **Connections ready in advance.** The engine opens 10 connections to each database when it starts, so the first shoppers don't wait for them to be set up.
- **Why it matters:** SOCO's backend waits at most a quarter of a second. Retrying would just make the shopper wait for SOCO's own list anyway.
- **Status:** done. Tested: one attempt, then 503; both connections have retries switched off; the limit is 250 ms on test, 2 s on dev. → [[Logs]]

### 9. The stand-in order ✅ laptop / ⏳ the real ranking
- **What it asks:** until the feed ranking (ENG-19) and the product ranker (ENG-17) exist, keep both surfaces off in production; on test, return suitable posts newest first, so Aravinth can test his side.
- **What we did:** feed: suitable posts, newest first. Product: suitable products, newest first, never the product being viewed. The pack only describes the feed's stand-in; I chose the same for products, which is also the product ranker's own last resort.
- **Why it matters:** Aravinth can build and test APP-15 against a real door now, instead of waiting for the models.
- **Status:** done on my laptop. With the full rules (1 Oct): **3 posts** on the feed (5 others belong to private accounts the test user doesn't follow) and **0 products** on a rail (question 17, see the status note above). Before the full rules it was 8 posts and 10 products. Real ranking waits on ENG-17 and ENG-19.

### 10. Error messages ✅
- **What it asks:** 400 for bad input, 401 for a bad password, 503 for off or a database fault, always shaped `{"error": "<code>", "detail": "<text>"}`.
- **What we did:** every refusal has that shape, with one short code (`invalid_surface`, `unauthorized`, `surface_off`, `database_unavailable`…) and a sentence.
- **Why it matters:** Aravinth's code can log and fall back by the code, without parsing sentences.
- **Status:** done.

### 11. Items in the app's shape ✅
- **What it asks:** items look the way the app already expects. A post card that shows a product keeps the **post's** ID as its item ID, and every item also carries its post ID and product ID separately, so one is never mistaken for the other.
- **What we did:**

  | Card | Item ID | Type | Post ID | Product ID |
  |---|---|---|---|---|
  | A plain post | the post | `post` | the post | empty |
  | A post showing a product | the post | **`product`** | the post | the product |
  | A product on a rail | the product | `product` | empty | the product |
- **Why it matters:** if a post ID were read as a product ID, a tap would be credited to the wrong thing, and the models would learn nonsense.
- **Status:** done. **Answered 1 Oct 2026 (question 4):** a post card showing a product is type `product`. The pack's Capture Register says so (note on F10: *"item_type product with a post id is a post card showing a product"*), and SOCO's own feed clicks on dev are written that way. Before, the engine sent `post`; one line changed.

### A. Extra: the full safety rules (ENG-08) ✅ since 1 Oct
- **What we did:** the small stand-in check (public, not hidden, not removed; product active and in stock) is gone. Every list now goes through ENG-08's twelve rules, E-01 to E-12: blocks either way, muted authors, items the user hid or reported, hidden or non-public posts, private accounts the user doesn't follow, products that can't be sold, inactive or suspended sellers, the user's own posts, adult content for under-18s, and removed posts. Each item left out writes one log line saying which rule. Then, **just before the answer leaves**, the items on the page are checked once more against SOCO's data; any that fail now are swapped for the next suitable ones.
- **Why it matters:** the pack says the engine applies every rule itself and SOCO's backend shows the list exactly as returned. Nothing it shouldn't show can slip through, even if it changed a second ago. → [[Platform Database]]
- **Fixed on 1 Oct 2026 (audit):** the engine used to skip obviously hidden posts and unsellable products already inside the database query, to read fewer rows. That meant those items never got a log line saying why they were left out, and ENG-08 wants one for **every** item left out. The shortcut is gone: every row is read and every exclusion is logged.

### B. Extra: a try-it script ✅
- **What we did:** one command that asks a running engine for 20 lists, times them, and checks every receipt against its answer. It prints item IDs only, never the password.
- **Why it matters:** the Build List's check, in one command, on any machine.

### C. Extra: section 6 of the checklist ✅ / ❌ two lines need attention
- **What we did:** six lines in the checklist script: the contract tests, the database tests, feed and product over the network, a wrong password, and switching the feed off without a restart.
- **Why it matters:** re-checking this task is part of re-checking everything.
- **Status (1 Oct):** line 6.1 still expects "14 passed", but there are now 17 contract tests, so it needs a one-line update. Line 6.4 (product over the network) fails on dev because no product passes the rules there (question 17).

## Result (1 Oct 2026, after the audit fixes)
- **Tests:** 19 of 19 pass: 17 without a database, 2 on made-up SOCO data. The whole test suite: **634 pass, 1 skipped**.
- **Over the network, laptop to Atlas, on SOCO's dev data** (8 posts, 2,011 products), now with the full rules:

  | Surface | Items | 95 in 100 answers within | Receipts matching |
  |---|---|---|---|
  | feed | 3 (was 8) | 129 ms (was 69 ms) | 19 of 19 |
  | product | 0 (was 10) | 354 ms: **over** 200 ms | 19 of 19 |

  The feed got slower because each list now also reads who the user follows, blocks and muted, who wrote each post, and checks the page once more at the end. It's still within 200 ms from my laptop. The product rail reads its full 1,000-product limit every time and finds nothing it may show, hence the slow, empty answer; it waits on question 17. The 200 ms limit is officially measured on the test server.
- Asking for the `opportunity` surface gets 400. Switching the feed off without a restart gets 503 within 30 seconds, while product keeps answering.

## Decided
| Date | Decision | Why |
|---|---|---|
| 1 Oct 2026 | Build now, to the row's own stand-in rule, instead of waiting for ENG-09 and ENG-29 | Aravinth needs a real door to build APP-15 against |
| 1 Oct 2026 | Product rails, for now: suitable products newest first, the viewed product left out | The pack only gives the feed's stand-in; this matches the product ranker's own last resort |
| 1 Oct 2026 | Plan-B step left empty; each slot records the method it **would** use | No score is read, so no plan B is used |
| 1 Oct 2026 | Exploration shuffles within the page | Pages stay steady while scrolling |
| 1 Oct 2026 | The list's label names each method (`interest-recency_decay`), not its number | The Build List (ENG-05, ENG-26) outranks the API contract's numbered example; names stay readable after a swap |
| 1 Oct 2026 | ~~A post card is type `post`, with its product alongside~~ Replaced the same day: a post card showing a product is type **`product`** | Question 4 answered from the pack (Capture Register F10, X-16) |
| 1 Oct 2026 | Both surfaces off in the real settings | The pack: off in production until the rankings exist |
| 1 Oct 2026 | A missing session id is accepted and written down as empty | The contract says "required" but doesn't list it as a reason to refuse; Aravinth's task says it may be empty |
| 1 Oct 2026 | Each request has a time limit: 250 ms on the servers (SOCO's own wait), 2 s on my laptop | The pack gives no limit for the engine, only "an error at once, no retry" (SD-26) |
| 1 Oct 2026 | At most 1,000 rows are read to fill one list | The pack gives no limit; without one, a surface with nothing to show would read everything, every time |
| 1 Oct 2026 | The receipt's field names follow the Capture Register (`slot_methods`, `scored_not_served` on about 1 in 10) | Fix from the audit (F71, F72) |

## Still to do
| What | Waiting on |
|---|---|
| Products on dev: no seller has a status, so nothing can be shown | Aravinth, question 17 → [[People]] |
| The plan-B ladder, reported on each list | ENG-09 |
| Real feed ranking, and skipping what was shown in the last 24 hours | ENG-19 |
| Real product ranking, and a real score on the "passed over" items | ENG-17 |
| Checklist line 6.1 expects 14 tests; there are 17 | A one-line fix in the checklist script |
| The demo's receipt script still looks for the old field names | A small script fix (the demo uses a short command instead for now) |
| The check on the **test** server | The test server → [[Environments]] |
| Switch the surfaces live | ENG-24's go-live rule |

## How this connects
- **Before it:** [[ENG-05 - Same method for each user]]
- **Built on:** [[Settings file]], [[Platform Database]], [[Engine Database]], [[Collections]], [[Activity events]], [[Engine sync]], [[SOCO_BE]], [[Secrets and passwords]], [[Logs]]
- **Next:** [[ENG-07 - Nightly jobs]]. It runs the overnight work (scores and batches) that a real ranking will read from.
- **Demo:** [[Demo - ENG-06]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-06.md` in the repo.
