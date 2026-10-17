# ENG-16: Promoter score, both methods (M8)

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 3 (within 17 working days) |
| **Waits on** | ENG-03, ENG-29, ENG-30 (points 1, 2, 3, 5 to 9), ENG-07, ENG-10 |
| **Needed by** | ENG-18 (M6 opportunity), ENG-19 (feed ranking) |
| **Status** | **Built** (17 Oct 2026, dev). Becomes Passed when its check runs on the test server |
| **Spec** | Build List v1.4 ENG-16; ENG-30 points 1, 2, 3, 5 to 9; Settings "M8 promoter" (weights, strength 20, cohort 20, trust × 0.5, low confidence below 20, follower bands) and "Commerce" (completed sale, 14 days, return window fallback 7, buffer 2, copy current 24 h); Fraud Policy v1.4 6.1 (level 3 restricted, 4 suspended, 5 removed); Kala's answers of 16 Oct (Q6: followers and account age) |

## 1. What the item requires

The Build List row in full is in `Tracing/pack_text/` (ENG-16). In short: who is scored; orders through their posts (reposts to the original, self-purchases out); six components as percentiles within the main category; weights rescaled over the components whose data exists; method one (shrinkage toward the category average, strength 20, with confidence); method two (percentile within the cohort of category × follower band, falling back to the category, then everyone, marked small_cohort); empty denominators not scored; no peers 0.5 and no_peer_group; a confirmed case that led to a restriction × 0.5; write to `ml_promoter_scores`, copy monthly on the 1st.

*How to check it is done:* "Scores exist for every eligible promoter, both methods, with confidence. A test promoter with a confirmed case scores half. A sale through a repost counts for the original author; a self-purchase through a store the buyer owns counts for nobody; an order with an open return request is not a completed sale, and becomes one once the request ends without a return and the window has passed; a Returned order counts as fully returned (partial refunds are not modelled); an account with only reposts is not scored."

## 2. What was built

### ENG-30 points 1, 2 and 8 (built here; M8 needs them)

- **Point 1**, `reco/platform/people.promoter_of(order, post_authors)`: `orders.promoter_id`, else the author of the order's post. M8 itself credits the **original** post's author (point 3); the job counts the orders where the two differ (`credited_to_original_not_promoter_id`, reposts). ENG-21 uses `promoter_of`.
- **Point 2**, `reco/platform/people.People`: a store and the personal account in its `businessregisters.user_id` are one person (`person_of`, `same_person`). Used for self-purchases (and later ENG-18, ENG-21).
- **Point 8**, `ProductRecord.return_window_days` / `return_applicable` (`deliveryConfig.returnWindow`, `isReturnApplicable`) and `reco/slots/promoter/sales.return_window_days`: the product's window; 0 when not returnable; `commerce.return_window_fallback_days` (7, new, fixed) when missing, counted and logged as a fallback. `commerce.return_buffer_days` (2, new, 0 to 7).

### The completed sale: `reco/slots/promoter/sales.py`

`sale_outcome(order, now, window_days, rules, open_requests)` on the engine's order copy: `returned` (order_status Returned, in full), `cancelled`, `rejected`, `history_conflict` (ENG-30 point 5, also Delivered with no Delivered event), `open_return_request` (Delivered, a request open in `ml_return_requests`), `completed` (Delivered and now ≥ Delivered time + window + 2 days), `in_return_window`, `not_completed` (not delivered, older than `commerce.pending_open_days`, 14), `in_progress`. Final states for sales quality: completed, cancelled, rejected, returned; the others count on neither side.

### The maths: `reco/slots/promoter/score.py` (pure)

`score_promoters(inputs, settings, commerce_on)`. Components as in the row; percentiles within the main category, `(below + (equal − 1)/2) / (n − 1)`, a group of one 0.5; `own` = Σ rescaled weight × percentile; category average = mean `own` of the category (one member: 0.5, `no_peer_group`). Method one (`shrinkage`): `(n × own + 20 × average) / (n + 20)`, `n` = qualified views / 100; `confidence` = `n / (n + 20)`; `low_confidence` when `n` < 20. Method two (`cohort_percentile`): `own` as a percentile within (category, follower band) if ≥ 20, else the category if ≥ 20, else everyone with `small_cohort`; it stores method one's confidence. `trust_halved`: both × 0.5. Follower bands: under 1,000; 1,000 to 10,000; over 10,000.

### The job: `reco/slots/promoter/job.py` (`python -m reco.jobs promoter`, nightly after `similar_posts`)

- **Return requests first (ENG-30 point 7):** if `returnrequests` can be read but the copy is not current (`writers.return_requests_current`), the job **does not run**: an error is logged with `alert: service_owner`, the run is recorded, the previous batches stay current. If it cannot be read at all (`fetch.can_read`), the commerce components stay off.
- **Who is scored:** authors of an original post (isRepost false, not seed) in the last 90 days; account found (user or store), active (`moderation.state`; store status), `restriction_level` not suspended/removed (DB-08, once it exists), no confirmed fraud case at level 4 or 5, not a test account or exemption, account at least 14 days old (users `createdAt`, else `timestamp` on dev, else `_id`; stores `timestamp`, else `_id`: Kala Q6), and qualified views in the last 30 days. Accounts with only reposts are counted as `only_reposts`.
- **Main category:** most frequent category on their original posts in 90 days; ties by name. None when their posts carry none of the 23 (`no_main_category`).
- **Views and engagement** (engine copy of postevents, not undone): qualified views (dwell ≥ 3 s, one per viewer per post) of their original posts; not the author's own (`is_self` or the same person), not test accounts, not business actors. Reach and quality use 30 days; conversion's denominator uses the same 90 days as its sales.
- **Followers (Kala Q6):** follows rows pointing at the account, leaving out self-follows (the same person), test accounts and pairs with a block between them (`followers`, status blocked); an unfollow deletes the row.
- **Orders through their posts:** orders created in the last 90 days with a post; the post led to its original (`reco.platform.reposts`); credited to the original's author; a broken chain credits nobody; seed posts, test-account buyers and self-purchases left out; each order's outcome from `sales.sale_outcome` with the product's return window.
- **Commerce components in use** once `returnrequests` can be read and any scored promoter has an order in a final state.
- **Trust:** `ml_fraud_cases` rows with `outcome` confirmed, `level_recorded` ≥ 3, decided, and `in_force_until` empty or later than now (`reco.store.promoter.read_confirmed_restrictions`). Level 3: × 0.5; 4 and 5: not scored. This is the shape ENG-21 must write.
- **Writes:** each method as one ENG-07 batch (`run_batch`, job `promoter`, slot `promoter_score`) into `ml_promoter_scores`; on the 1st of the month both are copied into `ml_promoter_scores_monthly` (unique on month, method, promoter; a re-run replaces that month). `reco.store.promoter.read_promoter_score(settings, promoter_id, method)` reads the current batch (ENG-19).

**Where the pack is silent (decided 17 Oct 2026):** a promoter with no order in a final state takes 0.5 for sales quality (neutral, not 0); commerce components switch on together; conversion's views and sales share the 90-day window; ties for main category by name; DB-08's restriction_level read when present; the fraud-case shape above.

## 3. Configuration

New: `commerce.return_window_fallback_days` (7, fixed), `commerce.return_buffer_days` (2, 0 to 7). Existing: `promoter.*`, `slots.promoter_score` (`shrinkage`, `cohort_percentile`), `commerce.pending_open_days`, `commerce.return_request_current_hours`, `lists.order_status`, `lists.test_accounts`, `lists.exemptions`, `events.qualified_view_seconds`.

## 4. Tests

`tests/test_promoter.py`, 17: one person; the promoter fallback; the return window (window, not returnable, fallback); completed only after window + 2 days; an open request is not completed until it ends; returned, cancelled, rejected, conflicts; 14 days; percentiles and a group of one; launch weights 0.40/0.40/0.20; method one's formula, confidence and low_confidence; method two's band → category → everyone and small_cohort; follower band edges; no peers 0.5; no views not scored; a restriction halves both; commerce components. MongoDB (the Build List's check): A, a store owned by B, C, a reposts-only R and a 5-day-old account: both methods for A, the store and C with confidence; R and the young account not scored; o1 through R's repost credited to A; o2 Returned (sales quality 0.5); o4, B buying through B's own store, counted for nobody; o3 with an open request not completed, then completed when the request ends; C with a confirmed level-3 case scores half under both methods; a copy that is not current leaves the batches as they were.

Results, 17 Oct 2026: 17 passed (16 unit, 1 MongoDB); unit suite 717 passed, 1 skipped.

**Dev, 17 Oct:** synced into a throwaway database (47,385 postevents, 726 orders, 51 return requests). Before the reconciliation the job refused to run ("returnrequests has no reconciliation yet"), as point 7 requires. After it: 137 authors with original posts, 12 reposts only, 1 not active, 28 with no qualified views; **108 scored**, both methods, commerce on. 144 orders through posts: 43 completed, 26 in their return window, 51 in progress, 6 older than 14 days, 1 open request, 1 returned, 6 cancelled, 7 rejected; 36 reached through a repost and credited to the original's author. Every row is `low_confidence` (n below 20: dev's views are few); method one sits near 0.5 (0.49 to 0.56), method two spreads 0 to 1; 81 rows `small_cohort`, 5 `no_peer_group`.

## 5. Runbook

```bash
python -m reco.jobs promoter
python -m pytest -q tests/test_promoter.py
```

## 6. Open

| What | Waits on |
|---|---|
| ENG-21 writes `ml_fraud_cases` in the shape above | ENG-21 |
| DB-08's restriction fields | Aravinth (dates) |
| ENG-19 reads the scores (and its fallback for authors with none, Kala Q8) | ENG-19 |
| The check on the test server | The test server |

## 7. Files changed

| File | Change |
|---|---|
| `reco/platform/people.py` | New: one person, the promoter fallback (ENG-30 points 1, 2) |
| `reco/platform/records.py`, `fetch.py` | Product return window (point 8); user age from `createdAt` first; all blocks; `can_read` |
| `reco/slots/promoter/` | New: `sales.py`, `score.py`, `job.py` |
| `reco/store/promoter.py` | New: reads, batches, the monthly copy |
| `reco/config/tunables.py`, `settings/engine.toml` | `commerce.return_window_fallback_days`, `commerce.return_buffer_days` |
| `reco/jobs/__main__.py`, `scheduler.py` | Job `promoter`, nightly after `similar_posts` |
| `tests/test_promoter.py` | New |
| `scripts/run_checklist.sh`, `scripts/make_proofs.py` | Section 15; the M8 proof folder |

## Update, 17 Oct 2026 (ENG-19)

With each method's batch the job now writes the medians an author with no score falls back to (Kala Q8): each main category's median score and the platform median, in `ml_measurements` (measure `promoter_medians`, one document per method, valid only while its `job_run_id` is the current batch; `reco.store.promoter.write_medians` / `read_medians`). `read_promoter_scores` reads many authors' scores at once for ENG-19.
