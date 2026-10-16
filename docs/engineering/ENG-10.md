# ENG-10: Interest score on live data, both methods

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days) |
| **Waits on** | ENG-03, ENG-04, ENG-07, ENG-29 (all built) |
| **Needed by** | ENG-11, ENG-12, ENG-14, ENG-16, ENG-19 |
| **Status** | **Built** (14 Oct 2026, on dev). M1 reads only the engine's copies, with every v1.3 source and weight; both methods are written nightly. Its check ("All M1 checks in ENG-11 pass") passes: 11 of 11. Becomes Passed when it runs on **test** (ENG-01 §4.4) |
| **Spec** | Build List v1.3 ENG-10 (and Settings sheet "M1 interest" rows: action weights, declared floor, half-life, windows; "Events / Qualified view"); ENG-03 (ids, actors, categories, undo fields); ENG-04 (the copies); ENG-29 items 3–5 (test accounts, order history, returns); SDA v1.6 SD-17; Definitions "Seen, and a qualified view" |

---

## 1. What the item requires

The Build List v1.3 row (abridged; full text in `Tracing/pack_text/`):

> Sources, all from the engine's copies (ENG-04). Each action is read from one place only, so nothing is counted twice: qualified views (postevents view rows with dwell_ms of 3,000 or more, one per viewer per post); likes, saves, comments, shares and add-to-carts; clicks (product_click from older builds counts as a click); purchases and reversals (the order itself: created_at, order_status and tracking_info); business follows (follows, followingReference businessRegister; the business's category must match one of the 23 by name, or the follow adds nothing); Not interested and Hide (postevents feedback rows).
>
> Impressions are not used by M1. remove_from_cart and the other new platform events are stored but carry no weight.
>
> Weights: qualified view 2; click 5; like 3; save 4; share 4; comment 4; add to cart 10; purchase 20, applied at order creation; follow of a business 5 on that business's category; Not interested or Hide −5 on the item's category.
>
> Purchase reversal: the same 20 is taken off, aged from the original order time, when the order becomes Cancelled or Rejected, or reaches Return Requested or Returned. An order is reversed once only, so it nets to exactly zero. Orders placed in incognito count for the buyer's own profile.
>
> Declared sign-up interests add a floor of 10 per category. The floor never decays. Method one, recency decay: half-life 30 days. Method two, time windows: 0–7, 8–30, 31–90 days, weighted 0.5, 0.3, 0.2. An action falls in exactly one window.
>
> Write both methods for every user into ml_user_interest_scores, with the method name. Delete any old time-windows rows that carry no method name, and recompute them.
>
> Undo (unlike, unsave, uncomment, unfollow) removes the weight of the action it undoes, aged from the original action's time. Apply each undo once.
>
> Order of calculation: add the weighted actions per category, add the declared floor, then clip each category at 0. Share = raw / the user's total raw. If every category comes to 0, write no scores for that user, and let the ladder (ENG-09) serve them. Per category, write raw, share (summing to 1 per user) and event_count (qualified actions only).

*How to check it is done:* "All M1 checks in ENG-11 pass."

## 2. What was built, subtask by subtask

Until now the nightly `interest` job read SOCO's **live** `postevents` through the M1 demo's reader, with the demo's five action types. On the live profile it now reads only the engine's copies. The demo profile (`DATA_PROFILE=demo`) keeps the demo's reader and coherence rule, which its pinned checks (`tests/test_method_a_expected.py`, `tests/test_refresh.py`) depend on.

### 1. Sources from the engine's copies, each from one place — done

`reco/slots/interest/copies.py` `read_inputs(settings, anchor)`, called by `reco/jobs/refresh.py` on the live profile. Reads:

| Action | Read from | Function |
|---|---|---|
| views, clicks (incl. `product_click`), likes, saves, comments, shares, add-to-carts, feedback | `ml_events` postevent copies | `writers.read_m1_event_copies` |
| purchases | `ml_orders` | `writers.read_order_copies` |
| business follows | platform `follows` (businessRegister) and `businessregisters.category` | `fetch.read_records("follow")`, `fetch.read_business_categories` |
| declared interests; the user list | platform `users` (`interest`, matched to the 23) | `fetch.read_records("user")` |
| categories | posts (`categories`), products (category tree) | `fetch.read_post_categories`, `fetch.read_product_categories` |

Postevent `purchase` and `follow` rows are not read (the order and `follows` are the one place for each). Impressions, `remove_from_cart` and the other native types are not read.

Only user accounts are scored. A row's actor comes from `user_model`; older platform rows have none (actor `unknown`, 42 of 46 M1 rows on dev). Those count when the id is a known user and are skipped otherwise. Business actors are skipped.

### 2. Qualified views, one per viewer per post — done

`dwell_ms` ≥ `events.qualified_view_seconds` × 1000 (3,000); the threshold is applied by the method (`view_duration_seconds`). Per (viewer, post) the reader keeps one view: **the most recent qualified one**; if none qualifies, the most recent view, which the method then counts as below the threshold. A view with no `dwell_ms` is counted as `views_without_duration` and not scored.

**Where the pack is silent:** *which* view of a post counts. The most recent qualified one is used, so a re-watch keeps the interest current (decided 14 Oct 2026).

### 3. The v1.3 weights — done

`reco/slots/interest/events.py` `EventType` gains `like`, `save`, `share`, `comment`, `business_follow`, `feedback`; `common.WEIGHT_KEY` and `Tunables.m1()` P-06 carry every Settings-sheet weight (view 2, click 5, like 3, save 4, share 4, comment 4, add to cart 10, purchase 20, business follow 5, Not interested / Hide −5). Search stays 0 (deferred).

### 4. Purchases, reversals and incognito — done

A kept order is one `purchase` at the order's `created_at`, on the product's category (else the post's). A **reversed** order (`order_status` Cancelled or Rejected, `cancelled_at` set, or `is_returned`: reached Return Requested or Returned, now or in `tracking_info`, ENG-29 item 5) contributes nothing. That is the row's +20 and −20 both aged from the original order time: exactly zero, once. Incognito orders count for the buyer.

### 5. Business follows — done

`follows` with `followingReference` businessRegister, at the follow's `createdAt`, +5 on the business's category if it is one of the 23 by name; otherwise nothing (counted `business_follow_no_category`).

### 6. Not interested and Hide — done

Feedback rows with `feedback_type` `not_interested` or `hide` (any case): −5 on the item's category (`target_id` / `target_type`, else the row's post or product). `mute_author` and `report` are filters (ENG-08) and carry no weight. Feedback on an author is skipped: an author has no one category. Feedback is never a qualified action, so it is not in `event_count` (`common.NOT_QUALIFIED`).

### 7. Undo — done

An action with `undone_at` set, and an undo row (`undo_of` set), contribute nothing: the original's weight minus the same weight at the same age, applied once.

### 8. The floor, the methods, the clip and the share — done

Unchanged from M1: floor 10 per declared category, never decays; decay half-life 30 days; windows 0–7/8–30/31–90 at 0.5/0.3/0.2, disjoint. New for the live profile: `scores.clip_to_shares` clips each category at 0 and shares by the total. A negative is Not interested / Hide doing its job, not a fault (the demo path's `normalise_with_coherence` still treats one as a coherence failure). All zero: no rows; the ladder serves the user.

### 9. Both methods, named; unnamed rows deleted — done

The `interest` job writes `recency_decay` and `time_windows` as ENG-07 batches, each row with `method`, `model_version`, `config_version`, `job_run_id`, `data_window`. Before them it deletes rows with no method (`writers.delete_unnamed_scores`, logged), which the run then recomputes.

### 10. Test accounts — done (unchanged)

Left out of scoring (ENG-29 item 3), as before.

## 3. Configuration reference

No new settings. `interest.weights.*`, `interest.declared_floor`, `interest.half_life_days`, `interest.window_bounds_days`, `interest.window_weights`, `events.qualified_view_seconds`, `lists.order_status`, `lists.category_map`, `lists.test_accounts`.

## 4. Tests

| File | Covers |
|---|---|
| `tests/test_m1_copies.py` (15) | Every weighted action read with its category; a row with no user_model; undo; one view per post (qualified beats newer); feedback kinds and author feedback; product category; unmatched categories; the four reversal cases; a kept and an incognito order; business follows; future and timeless actions; declared interests |
| `scripts/check_m1.py` (ENG-11) | The whole path on real databases: 11 of 11 |
| `tests/test_tunables.py`, `tests/test_service_contract.py`, `tests/test_nightly.py` | Updated for the new weights and the unnamed-row step |

Results, 14 Oct 2026 (laptop, Windows, Atlas build cluster): `tests/test_m1_copies.py` **15 passed**; ENG-11 **11 of 11**. Whole suite: see ENG-11 §4.

Real data, 14 Oct 2026, dev (`python -m reco.jobs sync`, then `interest`): both methods, **8 of 15 users scored**, 17 rows each. Left out before scoring: 8 actions not by a known user, 1 reversed order, 2 business follows with no category in the 23; 5 actions with no category in the 23; **10 views with no `dwell_ms`** (APP-02). The ladder now puts **2 dev users on rung 1** (`scripts/show_ladder.py`: rung_1 2, rung_2 6, rung_3_empty 7).

## 5. Runbook

```bash
python -m reco.jobs sync          # bring the copies up to date first
python -m reco.jobs interest      # both methods, as nightly
python scripts/show_ladder.py     # who now has a score (rung 1)
python scripts/check_m1.py        # the ENG-11 checks (throwaway databases)
```

## 6. Open

| What | Waits on |
|---|---|
| `dwell_ms` on views (none on dev), so views can qualify | Aravinth, APP-02 data |
| `updated_at` on postevents and orders, so undos and status changes reach the copies within 5 minutes | Aravinth, APP-12 |
| Every status change written to `tracking_info` | Aravinth, APP-08 |
| The category map (42 platform names) | Allen, ENG-29 |
| Run on **test**, then mark Passed | The test server |

## 7. Files changed

| File | Change |
|---|---|
| `reco/slots/interest/copies.py` | New: M1's inputs from the copies |
| `reco/slots/interest/events.py`, `common.py` | Six action types; feedback not a qualified action |
| `reco/config/tunables.py` | `m1()` carries every ENG-10 weight |
| `reco/store/scores.py` | `clip_to_shares` |
| `reco/store/writers.py` | `read_m1_event_copies`, `read_order_copies`, `delete_unnamed_scores` |
| `reco/platform/fetch.py` | `read_product_categories`, `read_business_categories` |
| `reco/jobs/refresh.py` | The live profile reads the copies and clips |
| `reco/jobs/__main__.py` | Unnamed rows deleted before the run |
| `tests/test_m1_copies.py` | New |

## Pack v1.4 update (15 Oct 2026)

- ENG-30 point 6: there is no Return Requested status. A purchase now nets to zero only when **order_status** is Cancelled, Rejected or Returned (`copies._is_reversed`, and the ladder's count in `writers.count_qualified_actions`); a history event never decides it. Before, a "Return Requested" status or a cancellation event in the history also reversed it. Test: `test_only_the_order_state_reverses_a_purchase`.
- ENG-30 point 10 (leave a purchase out while a return request is open; restore it when the request ends without a return) is ENG-30 work, not yet built.
- Category map (including a followed business's category) and test accounts: already in place (ENG-29).
- Dev, 15 Oct (after `sync` and `interest`): 8 of 16 users scored; 2 orders reversed (one Returned, one Rejected).

## Update, 16 Oct 2026

**16 Oct 2026:** Passed (Kala S1); view rule (most recent qualified) and author feedback confirmed.

## Update, 16 Oct 2026: M1 completed to v1.4 (ENG-30 points 9, 10; Kala 2a)

| Change | Where |
|---|---|
| **Open return request (ENG-30 point 10):** an order whose id has an open request in `ml_return_requests` (isActive true) contributes nothing; when the request ends without a return the order counts again at the next refresh (`skipped.order_open_return_request`). If the return-request copy is not current (point 7), M1 runs on the last good copy and logs why; the run summary records it (`return-request copy: …`) | `copies.read_inputs` |
| **Seed posts (ENG-30 point 9):** actions on a post with `_seedTag`, and orders through one, are left out (`skipped.seed_post`) | `copies.read_inputs` (posts read once, with `is_seed`) |
| **Qualified actions (Kala 2a):** per user, in the last `interest.personal_window_days` (90): a qualified view (one per post), click, like, save, comment, share, add-to-cart, a kept order (not Cancelled, Rejected, Returned, or with an open request), a business follow (even one whose business has no category in the 23). Not: Not interested / Hide, impressions, undone actions, own-post actions (`is_self`), seed posts, older actions. **The total, whatever the category, is stored on every score row as `qualified_actions`; `event_count` is the same set per category** (it was the events that contributed, all ages). The ladder counts with the same rules (ENG-09) | `copies.read_inputs` → `CopyInputs.qualified`, `qualified_by_category`; `refresh.refresh`; `InterestScore.qualified_actions` |

Own-post actions still add weight to the score; only the count leaves them out. Whether they should stay in the score is back with Kala (`ANSWERS_2026-10-16.md` §6, point 1).

Tests: `tests/test_m1_copies.py` +4 (open request out and back; a stale copy used and said; seed posts; the count, rule by rule). Unit suite 614 passed, 1 skipped.

**16 Oct 2026 (Kala):** own-post actions are now left out of the score under both methods, not only the count. See ENG-30 'Clarification from Kala'. Method one keeps all retained history; the 90-day limit is the count's and method two's.
