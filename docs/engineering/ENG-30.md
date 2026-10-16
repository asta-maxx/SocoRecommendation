# ENG-30: Adapt to the platform facts of 8 to 14 October

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 3 (within 17 working days; proposed estimate) |
| **Waits on** | ENG-10 (built), ENG-29 (built) |
| **Needed by** | ENG-16, ENG-18, ENG-21, ENG-23 |
| **Status** | **In progress** (15 Oct 2026). Points 5, 6 and 11 done with the ENG-29 rework; points 1–4 and 7–10 to build |
| **Spec** | Build List v1.4 ENG-30 (new in v1.4, 14 Oct 2026); API Contract v2.6; SDA v1.7; Capture Register 14 Oct (E6, F30, D12, X-23); AS-21 to AS-26 |

---

## 1. What the item requires

New in pack v1.4 (14 Oct 2026). It holds every adaptation to the App Team's ML Reference (8 Oct), its answers (13 Oct) and the database checks (13–14 Oct), so ENG-01 to ENG-11 and ENG-29 keep their text. It voids named clauses: ENG-03 "order outcome from statusLog and return_info" and its fourth check case; ENG-04 points 3, 8, 9 ("Return Requested"); ENG-10's "Purchase reversal" sentence; ENG-29 points 2 (Return Requested), 4 ("a return request", "who acted") and 5, and ENG-29's order check. Every other mention of Return Requested in ENG-03, ENG-04, ENG-10 and ENG-29 is void.

Points: (1) promoter on an order, with the post's author as fallback; (2) one person: an account and its stores; (3) repost chain to the original (10 steps, loops stop); (4) commission settings merge for M6; (5) order history as events from a history-text map, order_status the state; (6) returns at order_status Returned, time from return_info.returned_at; (7) copy `returnrequests` (no personal fields) into `ml_return_requests`, with a 24-hour freshness rule; (8) return window from the product; (9) `_seedTag` posts are test data; (10) M1 leaves a purchase out while a return request is open, restores it when the request ends without a return; (11) E-12 check (deranked and removed only).

*How to check it is done:* unit tests on the engine's test environment for each point, `findOne()` on `returnrequests` and `commissionconfigs` with the engine's login, the named platform order, and "ENG-11 passes again" (full text in `Tracing/pack_text/`).

## 2. What was built so far

### 5. Order history as events — done (15 Oct 2026)

`reco/config/tunables.py` `TRACKING_STAGES` and `settings/engine.toml` `[lists.tracking_stages]` (config_version 4): the history-text map, opening words → event: Order created → created, Order Accepted → accepted, Confirmed by buyer → confirmed, Shipped → shipped, Payment Completed → payment, Delivered → delivered, Cancelled → cancelled, Return requested → return_request, Refund of → refund, Returned to seller → returned. `records.tracking_stage` matches whole words, ignoring case; longest wins. `OrderRecord` gains `history_unmatched` (texts that match nothing: reported, never guessed) and `history_conflict` (a Delivered event after a Returned one; or Delivered / Returned with no Delivered event). A history event never changes the state. Every tracking_info text on the platform database on 15 Oct maps (10 openings; test `test_history_every_text_on_the_platform_maps`).

### 6. Returns at Returned — done (15 Oct 2026)

`OrderRecord.is_returned` is `order_status` Returned only; `returned_at` is `return_info.returned_at` (null values mean nothing); `returned_event_at` (the 'Returned to seller' event) is a cross-check. `OrderStatusValues.return_requested` removed (no such status). `is_reversed`: Cancelled, Rejected or Returned. M1 (`copies._is_reversed`) and the ladder's order count (`writers.count_qualified_actions`) read the state, never the history.

### 11. E-12 check — done (15 Oct 2026)

`tests/test_eligibility.py::test_e12_serves_every_other_compliance_status`: ok, review, fix_requested and no compliance record are served. ENG-08 unchanged.

### Not yet built

Points 1–4, 7–10, the daily report of unmatched history texts, and the engine-login `findOne()` check. On 15 Oct both `returnrequests` and `commissionconfigs` are listed by the engine's read-only login on dev.

## 3. Tests

15 Oct 2026: unit suite 601 passed, 1 skipped. ENG-11's script (13 checks) 13 of 13.

## 4. Open

| What | Waits on |
|---|---|
| Points 1–4, 7–10 | Me |
| Run the check on test | The test server |

## Update, 16 Oct 2026

**16 Oct 2026:** history map adds the app's other texts (Order placed, Rejected by buyer, Replacement / Exchange delivered → `replacement`). Point 4 defaults confirmed (enabled true, poolPercent 10, minOrderAmount 0). Passed only when the ENG-03, 04, 10, 11, 29 checks re-run on the ENG-30 code (F7). See `ANSWERS_2026-10-16.md`.

## Points 7 and 9, 16 Oct 2026

### 7. Return requests copied — done

- `PLATFORM_COLLECTIONS["return_request"] = "returnrequests"`; engine collection **`ml_return_requests`** (17th, SDA v1.7), indexes `order_open` (order_id, is_active) and `retention` (365 days on created_at = the request's createdAt).
- Sync source (`reco/sync/copies.py`): read by **`updatedAt`** (`SyncSource.updated_field`), then _id, with the 2-minute overlap; upsert on _id; checkpoint after each page; daily reconciliation compares `status`, `isActive`, `updatedAt` as well as ids. Same code path as ENG-04, so items (a)–(g) hold.
- **Personal fields never read or kept:** every platform read of returnrequests is limited to `records.RETURN_REQUEST_FIELDS` (orderId, returnNumber, status, isActive, createdAt, completedAt, updatedAt, windowEndsAt, policySnapshot.windowDays), and `make_copy` keeps only those (of policySnapshot only windowDays). On dev the record also holds pickupAddress, comment, photos, refund and more; none reaches the engine.
- **Freshness:** `writers.return_requests_current(settings, now, hours)` is true only when the last sync of returnrequests completed within `commerce.return_request_current_hours` (24, fixed) and its last reconciliation passed; otherwise it says why. `writers.read_open_return_orders` gives the orders with an open request (isActive true).
- Tests: `test_a_return_request_copy_keeps_status_and_dates_only`; `test_return_requests_are_copied_by_updatedat_without_personal_fields` (MongoDB: copied, closed request updates the copy, not current before a passed reconciliation, current after, not current 25 h later).

### 9. Seed posts — record done

`PostRecord.is_seed` from `posts._seedTag` (read directly; `_FIELDS["post"]` includes it). Used by M1 and the ladder (ENG-10, ENG-09) and popularity: actions on a seed post are left out like a test account's.

## Clarification from Kala, 16 Oct 2026 (ENG-09 / ENG-10)

1. **Qualified actions** (confirmed): one common definition. The ladder counts `qualified_actions` as distinct actions over the last 90 days; `event_count` counts the same qualifying actions per category, so an action in two categories appears in both. The 90-day limit applies to the count and to method two; method one keeps scoring all retained history with its decay.
2. **Own-post actions** (`is_self`) are excluded from the interest score under both methods, as well as from the five-action threshold, consistent with ENG-03. Fraud detection (ENG-21) still reads them.

Applied: `copies.read_inputs` drops own-post actions before scoring (`skipped.own_post`); it keeps the qualifying set as distinct action ids per user and per category (`CopyInputs.qualified_ids`, `qualified_ids_by_category`). M1 check script: **17** (Kala's regression test: a user with no declared interests who only likes their own post has `qualified_actions = 0` and no score under either method) and **18** (every category-level action belongs to the user's qualifying set; the set's size is `qualified_actions`; each `event_count` is its category's share). Unit test `test_only_liking_your_own_post_scores_and_counts_nothing`. Result: **18 of 18**.
