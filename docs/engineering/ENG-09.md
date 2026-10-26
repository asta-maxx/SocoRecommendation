# ENG-09: Fallback ladder

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days) |
| **Waits on** | ENG-03 (built: the platform reader), ENG-07 (built: nightly batches) |
| **Needed by** | ENG-06 (serving reports the rung), ENG-11 (M1 check 10: each rung reported for its test user). Also read by ENG-12 (source 1 uses "the interest method assigned to the user, or the fallback rung") and ENG-24 (cold start counted apart from fallback) |
| **Status** | **Built** (14 Oct 2026, on dev). All five rungs, "rung 3 empty", the rung on the response and the E1, and the nightly popularity job. The Build List check passes in tests and on the databases. Becomes Passed when the check runs on **test** (decided 14 Oct: the test server is being set up, ENG-01 §4.4) |
| **Spec** | Build List v1.3 ENG-09 (and Settings sheet rows "Score too old (ladder rung 4)", "Actions needed for a personal score", "Popularity window (ladder rung 3)"); SDA v1.6 SD-23, SD-17; DS-017 v2.5 §4.2 (`fallback_step`, "string or null"); Capture Register F71 (`slot_methods`); Definitions "Fallback", "Seen, and a qualified view"; AS-14; ENG-03 "Ignored" (`interestScores` only as the old score in the ladder); ENG-10 (sources, qualified views, floor); ENG-29 item 3 (test accounts) |

---

## 1. What the item requires

The Build List v1.3 row, *What to build*:

> For the interest score, check in order and use the first that applies. The rung used is reported on the response and the request record.
> 1. The user has at least 5 qualified actions in the last 90 days and a score computed in the last 48 hours: use their score.
> 2. The user has fewer than 5 qualified actions but has declared sign-up interests: use the floor for those interests, spread evenly, plus whatever actions they have.
> 3. The user has fewer than 5 qualified actions and no declared interests: use platform-wide category popularity over the last 30 days (qualified views per category).
> 4. The stored score is older than 48 hours or fails its checks: use the old delivered interest score.
> 5. The engine's own store is down: use the old delivered interest score.
>
> If the engine's own store cannot be read, go straight to rung 5. Where no old delivered score exists, rungs 4 and 5 fall back to rung 3. Each is logged separately.
>
> **When rung 3 has nothing either** (a new platform with no qualified views yet): serve eligible posts newest first, logged as rung 3 empty. No rung ever returns nothing.
>
> A rung below 1 is normal for a new user. It is cold start, not a failure, and is counted separately from operational fallback (ENG-24).
>
> At surface level, when the engine cannot answer at all, SOCO_BE shows its existing ordering (APP-15).
>
> A fallback is never counted as a result for a method that did not run.

*Waits on:* ENG-03, ENG-07. *Needed by:* ENG-06, ENG-11.

*How to check it is done:* "Test users for each rung get the right rung reported."

SD-23 says the same, and adds: "The response names the rung." DS-017 §4.2: `fallback_step` is "string or null … null if none was needed".

## 2. What was built, subtask by subtask

The demo ladder (`reco/fallback/`, M1 task 17) was the starting point. It had no 5-action test, never served the delivered score, had no "rung 3 empty", counted popularity from SOCO's live log on every request, and serving never called it. All of that is replaced.

### 1. Rung 1: five qualified actions and a fresh score — done

`reco/fallback/read_path.py` `get_profile(settings, user_id, method, reference_date)`.

- **Qualified actions** (`reco/store/writers.py` `count_qualified_actions`, plus `reco/platform/fetch.py` `read_business_follows`), over the last `interest.personal_window_days` (90, fixed), from the engine's copies only (ENG-04), as ENG-10 lists M1's sources:
  - `ml_events` postevent rows: a `view` with `dwell_ms` ≥ `events.qualified_view_seconds` × 1000 (3,000), **one per post**; or a `click`, `product_click`, `like`, `save`, `comment`, `share`, `add_to_cart`. Never an undo row (`undo_of` set) or an action later undone (`undone_at` set).
  - `ml_orders`: each order the user bought (`buyer_id`), unless cancelled, rejected (`cancelled_at`) or returned (`is_returned`): its purchase nets to zero (ENG-10).
  - business follows: `follows` with `followingReference` businessRegister (ENG-10 reads them from the platform).
  - Counting stops at `interest.personal_min_actions` (5, fixed): the aggregation is `$limit`ed, and orders and follows are only counted if events fall short.
- **Fresh score:** the current batch of `ml_user_interest_scores` for the user's assigned method (ENG-05, ENG-07), oldest `computed_at` within `interest.stale_after_hours` (48; 1 to 72).
- **Its checks** (`score_problem`): shares within 0 to 1 summing to 1 (±1e-6), no raw below 0, no category twice. These are the ENG-11 checks a single request can see (2 and 3).

**Where the pack is silent (decided 14 Oct 2026):**
- *Which actions qualify.* The pack names M1's sources (ENG-10) and that `event_count` holds "qualified actions only" without views under 3 s (ENG-11 check 8). Feedback (`not interested`, `hide`) is left out: it lowers a score (−5) rather than building one, and ENG-10 sends a user whose categories all come to 0 to the ladder. Impressions are left out: M1 doesn't use them.
- *Five or more actions but no score at all* (e.g. the refresh hasn't run, or ENG-10 isn't built yet): treated as rung 4, a score that "fails its checks". Rungs 2 and 3 apply only below 5 actions.

### 2. Rung 2: declared interests, the floor plus actions — done

Fewer than 5 actions, and `users.interest` matched to the 23 (ENG-03, `UserRecord.declared_interests`) is not empty.

- With a usable stored score: served as is. ENG-10's nightly score is exactly "the floor (10 per declared category) plus the weighted actions", so it *is* rung 2's answer.
- Without one: the floor alone, spread evenly across the declared categories (`evenly_spread`), logged.
- Rung 2 comes before rung 4: a new user with a stale score is rung 2, not 4 (first match wins).

### 3. Rung 3: platform popularity, computed nightly — done

Fewer than 5 actions and nothing declared (also any user with no platform record).

- **The nightly job** `python -m reco.jobs popularity` (`reco/fallback/popularity.py`), now in `NIGHTLY` after `interest`: every (viewer, post) pair with a qualified view in the last `interest.popularity_window_days` (30; 7 to 365) from `ml_events` (`read_qualified_views`), test accounts left out (ENG-29 item 3), each post's categories matched to the 23 (`fetch.read_post_categories`), counted per category.
- Written as an ENG-07 batch (`run_batch`, job `popularity`, method `platform_popularity`) into `ml_measurements` (`measure: category_popularity`, `category`, `qualified_views`, `window_days`, `data_window`, `computed_at`, `config_version`, `model_version`, `job_run_id`). A request reads only the current batch (`read_popularity`).
- **Where the pack is silent:** where rung 3's numbers live. Computing them per request would read the whole activity copy on every list, and SD-17 says a request never calculates, so it's a nightly batch like every score. `ml_measurements` is used because the 16 collections are fixed (ENG-01) and none other fits a platform-wide count.

### 4. Rung 3 empty — done

When the current batch is empty or missing (or the store holding it can't be read), the profile has no categories and the step is `rung_3_empty` (or `rung_4_to_3_empty`, `rung_5_to_3_empty`), logged `RUNG 3 EMPTY`. The list is eligible posts newest first, which is what serving's interim ordering already is (ENG-06).

### 5. Rungs 4 and 5: the old delivered score — done

- **Rung 4:** 5 or more actions, and the score is over 48 hours old, fails its checks, or is missing. Logged as a REFRESH problem.
- **Rung 5:** the engine store read (score or action count) raised. Applied at once. Logged as a SERVING problem. The popularity batch isn't tried (it lives in the same store).
- **The old delivered score:** `users.interestScores` (a map of category name → number), read with the user record in one query (`fetch.read_user_with(..., extra=("interestScores",))`). The field name appears only in `reco/fallback` (ENG-03 "Ignored"; `tests/test_platform_records.py` enforces it). Names matched to the 23 (unmatched dropped), values below 0 clipped to 0, divided by the total.
- No usable delivered score: rung 3 (`fell_through_from` 4 or 5).
- A **platform** read failure is not a rung: it raises, and the request answers 503 (SD-26).

### 6. The rung on the response and the request record — done

`reco/api/recommendations.py`: on the **feed**, the ladder runs alongside candidate building (`asyncio.gather`, inside the request's time limit) for the user's assigned interest method.

- Response `fallback_step` and E1 `fallback_step`: `Profile.fallback_step`. `null` at rung 1; otherwise `rung_2`, `rung_3`, `rung_4`, `rung_5`, `rung_4_to_3`, `rung_5_to_3`, with `_empty` appended when rung 3 had nothing.
- E1 `slot_methods` (F71), interest entry: `fallback_step`, plus `rung`, `method_served` (true only at rung 1) and `cold_start`. The promoter_score entry keeps `fallback_step: null` (its own fallback is ENG-16/ENG-19).
- Product surface: the interest slot isn't touched, so no ladder; `fallback_step` stays null (ENG-17 owns M5's fallback).
- The served-list log line carries `fallback_step` and `cold_start`.

**Where the pack is silent:** the spelling of `fallback_step`. DS-017 says only "string or null"; the strings above name the rung and, where it fell through, both rungs, so ENG-24 can tell cold start from operational fallback without a second field.

### 7. Cold start apart from fallback — done (counting is ENG-24)

`Profile.cold_start` is true for rungs 2 and 3 reached directly; false for 4, 5 and their fall-throughs. Recorded on the E1 and logged. ENG-24 counts it.

### 8. Never credited to a method that didn't run — done

`method_served` is false on every E1 whose interest slot didn't serve from rung 1. The E1 keeps `ordering: "interim_newest_first"` until the rankers serve (ENG-06 §1.3).

### A. Extra: `scripts/show_ladder.py` — done

Walks the ladder for named users (in detail) or a sample of platform users, and prints the count per step. Reads only. Used by checklist 10.4 and the demo.

## 3. Configuration reference

No new settings. Read from `settings/engine.toml`:

| Setting | Value | Used for |
|---|---|---|
| `interest.personal_min_actions` | 5 (fixed) | Rung 1 threshold |
| `interest.personal_window_days` | 90 (fixed) | Action window |
| `interest.stale_after_hours` | 48 (1 to 72) | Rung 4 |
| `interest.popularity_window_days` | 30 (7 to 365) | Rung 3 job |
| `events.qualified_view_seconds` | 3 (1 to 10) | Qualified view |
| `lists.test_accounts` | (list) | Left out of rung 3 |
| `lists.category_map` | (map) | Delivered score names → the 23 |

New job: `popularity` (in `NIGHTLY`: `interest`, `popularity`, `category_check`, `reconcile_sync`).

## 4. Tests

| File | Covers |
|---|---|
| `tests/test_read_path.py` (20) | One user per rung; the 90-day/3-second/stop-at-5 count; business follows count; rung 2 with and without a score; rung 2 before 4; rung 3 and rung 3 empty; unknown user; rung 4 delivered (matched, dropped, clipped) and to 3; three failed checks; the 48 h setting; rung 5 at once, and to 3 empty without reading popularity; a platform fault raises |
| `tests/test_recommendations.py` (+9) | Every step string on the response and E1, `rung`, `method_served`, `cold_start`, the assigned method asked for; product doesn't walk the ladder |
| `tests/test_ladder_store.py` (4, MongoDB) | What counts as a qualified action (and stopping at 5); the popularity job end to end (once per viewer per post, test accounts out, 30 days, unmatched categories dropped, batch replaced whole); the platform reads; one user per rung on real reads |

Results, 14 Oct 2026, laptop (Windows, Python 3.12, Atlas build cluster, throwaway databases):

- `tests/test_read_path.py`: **20 passed**. `tests/test_ladder_store.py`: **4 passed**.
- Whole suite: **641 passed, 1 skipped** (the skip is the long-standing LEGACY_LABEL_MAP one).

Real data, 14 Oct 2026 (`scripts/show_ladder.py`, all 15 dev users, reads only): `rung_2` 6, `rung_3_empty` 7, `rung_4` 1, `rung_4_to_3_empty` 1. Rung 4: two users have 5+ actions but their scores date from 1 Oct (no nightly run since). Rung 3 is empty because the `popularity` job (run once on dev, 14 Oct, succeeded) found **0 qualified views**: none of the 17 view rows in dev's `ml_events` carries `dwell_ms`, and the newest copied activity is 24 Sep (the sync hasn't run since 1 Oct).

## 5. Runbook

```bash
python -m reco.jobs popularity                # rung 3's batch, now (it also runs nightly)
python scripts/show_ladder.py                 # count per step over 20 platform users
python scripts/show_ladder.py <user id> ...   # one user's rung, step and categories
```

Checklist section 10 (`scripts/run_checklist.sh`): 10.1 the ENG-09 check through serving, 10.2 the ladder rules, 10.3 on a database, 10.4 on SOCO's real users.

## 6. Open

| What | Waits on |
|---|---|
| ~~Rung 1 and 2 on live scores~~ | Done 14 Oct 2026 (ENG-10): 2 dev users now reach rung 1 |
| Real qualified views on dev (no `dwell_ms` on any dev view row) | APP-02 data from Aravinth; the sync running |
| Count cold start apart from fallback in the weekly report | ENG-24 |
| ~~M1 check 10 (each rung reported for its test user)~~ | Done 14 Oct 2026 (ENG-11: passes) |
| Run the check on **test**, then mark Passed | The test server (ENG-01 §4.4) |

## 7. Files changed

| File | Change |
|---|---|
| `reco/fallback/read_path.py` | Rewritten to the v1.3 ladder |
| `reco/fallback/profile.py` | Rung meanings; `fallback_step`, `cold_start`; rung 4/5 may serve the delivered score |
| `reco/fallback/popularity.py` | New: the nightly popularity batch |
| `reco/store/writers.py` | `count_qualified_actions`, `read_qualified_views`, `write_popularity`, `read_popularity` |
| `reco/platform/fetch.py` | `read_user_with`, `read_business_follows`, `read_post_categories` |
| `reco/api/recommendations.py` | The ladder on the feed; `fallback_step`, `rung`, `method_served`, `cold_start` |
| `reco/jobs/__main__.py`, `reco/jobs/scheduler.py` | The `popularity` job, in `NIGHTLY` |
| `scripts/show_ladder.py` | Real users, steps, counts |
| `scripts/run_checklist.sh` | Section 10; 6.1 now 26 tests; 7.6 now 3 current batches |
| `tests/test_read_path.py` | Rewritten |
| `tests/test_recommendations.py` | Ladder stub; rung reporting tests |
| `tests/test_ladder_store.py` | New |

## Update, 16 Oct 2026

**16 Oct 2026:** Passed (Kala S1). Step strings confirmed; rung 5 with no delivered score raises `EngineStoreUnavailable` (503), no `rung_5_to_3`. The 5-action count's definition is back with Kala (`ANSWERS_2026-10-16.md` §6).

## Update, 16 Oct 2026: the count, Kala's way (2a), equal to ENG-10's

- `writers.qualified_action_rows(settings, user, since, view_ms, limit)` replaces `count_qualified_actions`: one row per qualified action from the engine's copies, with Kala's rules: a qualified view once per post (a view with no post counts on its own), click, product_click, like, save, comment, share, add-to-cart; never an undo row, an undone action, or **an action on your own post (`is_self`)**; orders unless Cancelled, Rejected, Returned **or with an open return request** (ENG-30 point 10).
- `read_path` leaves out **actions on seed posts** (ENG-30 point 9, from the platform's posts) and adds business follows. It reads `5 + 10` rows first and counts all of them only if seed posts took the count below 5.
- `read_path.count_qualified_actions(settings, user, now)`: the full count, the number ENG-10 stores on each score row as `qualified_actions`. ENG-11 checks the two are equal.
- Read errors keep their meaning: the engine store failing is rung 5; the platform failing is a 503.

Tests: `test_actions_on_seed_posts_do_not_count`; `tests/test_ladder_store.py::test_qualified_actions_count_what_the_pack_counts` now also leaves out an own-post like and an order with an open request. 53 ladder and serving tests pass (with MongoDB).

## Review of 26 Oct 2026, point 6

`scripts/show_ladder.py` adds two counts: users with `interest.personal_min_actions` (5) or more qualified actions in `personal_window_days` (90) (`read_path.count_qualified_actions`), and users with a score under `stale_after_hours` (48) old for the method. `--all` walks every platform user. To be re-run on the test server after a scheduled nightly into `soco_engine_test`.
