---
tags: [task, step-1]
task: ENG-03
status: Built
owner: Allen
---
# ENG-03: Reading SOCO's data correctly

> [!note] Status: **Built** (realigned 1 Oct 2026)
> First built on 29 Sep. The pack's v1.3 rewrote this task, so on 1 Oct it was rebuilt to the new row. All 10 parts are built, and the check **passed again on my laptop** on 1 Oct. It becomes **Passed** once the same check runs on the test server.

**In one line:** teach the engine exactly how SOCO stores things, so no model ever misses data, misreads it, or counts it twice.

## Why this task
Almost every model reads SOCO's data: interest, retrieval, promoter score, product ranker, fraud. If each one read SOCO's database its own way, they'd each make different mistakes. This task reads it **once, correctly**, and hands every model clean, identical records. ENG-29 (the adapters to SOCO as it is actually built) builds straight on top of it. → [[Build Steps]]

## What came before
- [[ENG-02 - Service skeleton and settings]] made one part of the engine, *platform*, the only door to SOCO's data. This task decides what comes through that door.
- SOCO's data is messy: the same kind of ID is stored two different ways, dates live in differently named fields, and "active" is spelled differently in different places. → [[Platform Database]]
- The first version (29 Sep) had a **switch** between SOCO's old logs and the engine's new one. Pack v1.3 dropped it. → [[Event source switch]]

> [!note] What changed on 1 Oct
> - **No more switch.** Before launch, SOCO moves its old logs into its main activity log (`postevents`). The engine copies that one log into its own database, and every model reads only that copy → [[Engine sync]].
> - **New rules:** who did something can be a person *or* a business; a card's post and product are kept apart; the card's position, undo marks and post-page visits are kept.
> - **A bigger check:** besides follows with text IDs, it now names a business acting, a product post on SOCO's feed, and an order with a history and a return request.

> [!tip] Later on 1 Oct: a check against the pack, and answers to questions
> - A post-page visit is now recognised **whatever its capital letters**. → part 10
> - Three questions are answered from the pack itself, so they're off my list: which cards a person has seen (11), how a post card showing a product is labelled (4), and where business follows come from (6). → parts 5, 6, 10
> - The records gained a few fields that the "may this be shown?" rules (ENG-08) need, including a **guessed** shape for SOCO's block list, which is still a question for Aravinth. → part 2

## Subtasks, one by one
The v1.3 Build List splits ENG-03 into ten parts (1–10). There are two extras (A and B).

### 1. Every ID written the same way, and who's acting ✅
- **What it asks:** SOCO stores IDs in two formats (a special database format, and plain text). The engine must treat them as one. And an action can be done by a person *or* a business; a label on each row says which.
- **What we did:** every ID is turned into the same plain-text form as it's read. Each activity row, order and cart line now also says whether a person or a business did it. Some IDs, like an event's or a basket's, are kept exactly as written, because they aren't database IDs at all.
- **Why it matters:** otherwise "user 123" stored one way and "user 123" stored the other would look like two different people. And a business's like would be looked up among people and lost.
- **Status:** done. On the real data, all 93 follows use plain text, and 6 of 146 activity rows were done by a business.

→ [[Platform Database]]

### 2. The right field for each fact ✅
- **What it asks:** use exactly the fields the pack names. An order's value is `total_price`, a post's time is `timestamp`, stock is quantity minus reserved, how long something was on screen is `dwell_ms`, and so on. If a record has no time, work it out from its ID.
- **What we did:** made one clean "record" for each of the 11 kinds of SOCO data (users, businesses, posts, activity, follows, orders, cart lines, products, variants, categories, and served lists). Each fills in only the fields the pack names. A missing time is recovered from the ID, which secretly contains the moment it was created.
- **Orders** get the most care. Their history is the list of steps SOCO keeps on each order (`tracking_info`: placed, delivered, cancelled…). From it the record works out whether the order was **returned** and **who cancelled** it, and keeps any cancel reason (stored, never scored). Orders placed in **incognito** still count for the buyer: incognito only hides who bought, it doesn't hide the purchase.
- **Why it matters:** every model now reads "order value" or "was it returned" from the same place, so no model can use the wrong field.
- **Added 1 Oct (for ENG-08):** a "not interested" or "hide" now keeps **what it was about** (a post, a product or an author); people and businesses keep their **restriction level** once SOCO adds it; and a reader for **blocks** in SOCO's `followers` collection. That collection is empty on dev and its fields aren't documented, so the block reader **assumes** "this user blocked that follower". Question 16 to Aravinth confirms or corrects it. → [[People]]
- **Status:** done. All **8,682 real documents** were read with **no failures**.

→ [[Platform Database]]

### 3. Categories must be one of the 23 ✅
- **What it asks:** a post's categories must match one of the pack's 23 categories **by name**. A product's category is found through SOCO's category tree, and its top name must be one of the 23. Anything else is dropped.
- **What we did:** built both rules. Capital letters and extra spaces are ignored, and nothing is guessed: "Fashion" is *not* treated as "Fashion & Apparel". If the name doesn't match, the engine looks in its own **category map** in the settings file (SOCO's name → one of the 23), which is empty for now. The old "legacy" map is never used.
- **Why it matters:** the models compare interests by category. A made-up or misspelled category would split one interest in two.
- **Status:** done. **But see the warning below: SOCO's products aren't in the 23 yet.**

→ [[Settings file]]

### 4. "Active" means active, however it's spelled ✅
- **What it asks:** status words are compared ignoring capital letters.
- **What we did:** "Activate", "activate" and "ACTIVATE" are treated as the same. Different words stay different: "Activate" on a product is not the same as "Activated" on a post.
- **Why it matters:** otherwise an active product could be hidden just because of a capital letter.
- **Status:** done.

→ [[Platform Database]]

### 5. One place for each kind of data, and no switch ✅
- **What it asks:** every activity (views, likes, clicks, feedback…) is read from one place: the engine's own copy of SOCO's activity log. SOCO's 26 kinds of activity are each tagged with the pack's event code. There is no switch between old and new logs any more.
- **What we did:**
  - wrote down the one place for every kind of data: activity and served lists from the engine's copy, orders from the engine's copy of orders, follows and blocks from SOCO (answered 1 Oct: business follows come from SOCO's `follows` too, not from the activity log);
  - built the table of SOCO's 26 activity types. Each gets its code and a flag: does a model use it, or is it just kept for later?
  - mapped SOCO's screens to the engine's two: the home feed is *feed*; the product page and the cart are *product*;
  - removed the old switch and the readers for SOCO's old logs. The engine now reads only the 13 SOCO collections its login is allowed to read.
- **Why it matters:** if purchases were counted from both the orders and the activity log, every purchase would count twice. One place each makes that impossible.
- **Status:** done. On the real data, 127 of 146 activity rows have an event code (the rest are kinds the pack keeps without a code, like plain views).

→ [[Engine sync]] · [[Event source switch]]

### 6. Keep the post and the product apart ✅
- **What it asks:** a card on the feed can be a post that *shows* a product. Its ID is the post's, but it's labelled "product". Read it as a post, and keep the product's ID next to it.
- **What we did:** every activity row now carries three things: the card that was shown, its post, and its product. On the feed, a "product" card with a post ID is read as that post, with the product kept alongside.
- **Why it matters:** without this, a post's ID would be looked up as a product and find nothing, or the wrong thing.
- **Status:** done. Tested with a post card showing a product on SOCO's feed. **Answered 1 Oct:** the pack (and SOCO's real feed clicks) confirm such a card is labelled "product", with the post's ID as the card and the product kept alongside, exactly as read here. The engine's own lists now label it the same way (ENG-06).

→ [[Activity events]]

### 7. Where the card was on the screen ✅
- **What it asks:** each event keeps the position the card was shown at.
- **What we did:** the position is kept on every activity row. SOCO shows the engine's lists unchanged, so that position is the engine's own position. (The pack's extra "delivered-list" record isn't needed.)
- **Why it matters:** later measurements compare how well the top of a list does against the bottom.
- **Status:** done.

### 8. Undo and own posts are kept, not hidden ✅
- **What it asks:** when someone unlikes, unsaves or unfollows, nothing is deleted. The original is marked "undone", and the undo points back at it. A like on your own post is marked too. Keep all of it; each model decides what to do.
- **What we did:** every record keeps these marks as they are. The event table also knows which action each undo reverses (unlike → like, and so on).
- **Why it matters:** the interest score must take a like back when it's undone. The fraud rules want to *see* likes that were undone quickly. If the reader threw them away, fraud would be blind.
- **Status:** done.

→ [[Activity events]]

### 9. Data the engine must not read ✅
- **What it asks:** a few fields must be ignored: an old interest list, SOCO's own feed score, and the old interest scores (allowed only as a last-resort fallback).
- **What we did:** a check reads the engine's code and fails if any of those fields is used where it shouldn't be.
- **Why it matters:** those fields are stale or belong to SOCO's own feed. Using them would quietly mix old answers into new ones.
- **Status:** done. (v1.3 no longer lists the unused events table, so it came off the list.)

### 10. A visit to a post's page isn't a card view ✅
- **What it asks:** when someone opens a post's own page, that counts as a page visit. It must never count as seeing a card in a list.
- **What we did:** activity on the post page is marked as a page visit, and it isn't put on the feed or product screen.
- **Why it matters:** otherwise every post-page visit would look like a card that was shown and seen, which would inflate the numbers.
- **Fixed 1 Oct (audit):** SOCO might write the page's name as `post_detail` or `Post_Detail`. Both now count as a page visit; before, only the exact lower-case spelling did, so a capitalised one could have slipped through as a card view.
- **Status:** done. None of today's 146 rows are page visits. **Answered 1 Oct** (no longer a question for Kala): the pack says paging leaves out what the engine **served** in the last 24 hours, from its own records (ENG-19). SOCO's own seen list is for measurement.

### A. Extra: readers that hand over clean records ✅
- **What we did:** a helper fetches SOCO's data and returns the clean records, so no model ever touches a raw SOCO field. The same file also has the reads the [[Engine sync]] uses to copy SOCO's logs; those belong to ENG-04.
- **Why it matters:** the rules in parts 1–10 can't be forgotten, because there's no other way in.

### B. Extra: a full check over the real data ✅
- **What we did:** a script reads every document in SOCO's database through the new records, without changing anything, and reports counts only, no personal details.
- **Why it matters:** the tests use examples; this proves the rules fit the **real** data.
- **Status:** done on 1 Oct. 8,682 documents, 0 failures. (Fewer than 29 Sep's 8,741 because SOCO's two old click and impression logs aren't read any more.)

## ⚠️ What the real data showed
> [!warning] None of SOCO's 2,011 products is in one of the 23 categories yet.
> SOCO's top-level categories are a different list (e.g. "Fashion" instead of "Fashion & Apparel"). The pack no longer asks Aravinth to restructure them (DB-07 is now *Not needed*). Instead, **I fill in the engine's category map** (ENG-29). Until then, products are dropped from category scoring, as the pack says.

Other things the data showed on 1 Oct:

| What | Seen | Why it matters |
|---|---|---|
| Activity rows with a change time (`updated_at`) | 0 of 146 | The sync's 5-minute read needs it (APP-12) |
| Orders with a change time | 3 of 8 | Same |
| Orders with a history | 8 of 8 | Returns and cancellations read fine |
| Products with the new category path | 0 of 2,011 | The engine falls back to the product's single category field |
| Orders with a basket number | 2 of 8 | Older test orders |
| SOCO's serve log, and its blocks list | missing, empty | Nothing to read yet |

## Result (1 Oct 2026)
- The pack's check, *"read one of each record type, including a follows record with text IDs, a businessRegister actor, a product post on a platform feed list, and an order with a status log and a return request"*, **passes**. All four named cases have their own test.
- This task's tests: **60 passed**, none failed (59 plain tests, plus 1 against a throwaway database).
- Every real SOCO document reads: **8,682, 0 failed**.
- Re-run after the audit fixes (1 Oct): this task's tests **60 passed** again; the whole suite **634 passed, 1 skipped**. The real-data check gives the same counts, plus one line for SOCO's serve log, which doesn't exist yet.

## Decided
- **1 Oct 2026:** rebuilt to the v1.3 row; the event source switch and the old-log readers are removed.
- **1 Oct 2026:** where a product has no category path yet, its single category field is used, under the same "one of the 23 or dropped" rule.
- **1 Oct 2026:** the order history comes from `tracking_info`, as ENG-29 says, since SOCO has no separate status log or return record.
- **1 Oct 2026 (audit):** a post-page visit is matched ignoring capital letters, like every other status word.
- **1 Oct 2026:** blocks are read as "`userId` blocked `followerId`, status blocked" until Aravinth confirms the real shape (question 16).

> [!note] Added on top since (1 Oct 2026)
> [[ENG-29 - Adapting to the platform as built]] built on these readers: status **spellings** from the settings, the **steps** of an order's tracking (each one named, with who acted and when it was first delivered, returned or cancelled), a reader for SOCO's **serve log**, and one helper for the **test and exempt account** lists.

## Still to do
| What | Waiting on |
|---|---|
| Fill the category map so products count | ENG-29 (me) |
| Confirm the shape of SOCO's block list (the reader guesses it today) | Aravinth, question 16 → [[People]] |
| Move the interest score onto these clean records. Today it still reads SOCO's **live** activity log through the old demo reader, not the engine's copy | ENG-10 |
| Re-run the check on the **test** server, then mark it Passed | The test server |

## How this connects
- **Before it:** [[ENG-02 - Service skeleton and settings]]
- **Built on:** [[Platform Database]], [[Collections]], [[Settings file]]
- **Next:** [[ENG-04 - Engine sync]]. It copies SOCO's activity and orders into the engine, and these records are how each copy is read.
- **Demo:** [[Demo - ENG-03]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-03.md` in the repo.
