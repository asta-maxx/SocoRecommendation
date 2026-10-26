# ENG-11: M1 check script

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days) |
| **Waits on** | ENG-10 (built 14 Oct), ENG-09 (built 14 Oct), ENG-05 (built) |
| **Needed by** | ENG-24 (go-live rule: ENG-11 must pass) |
| **Status** | **Built** (14 Oct 2026). All 11 checks pass on the laptop; output saved. Becomes Passed when it passes on **test** (ENG-01 §4.4) |
| **Spec** | Build List v1.3 ENG-11; Home sheet (save results as `<item ID>_<date>`); ENG-05, ENG-09, ENG-10 |

---

## 1. What the item requires

> Write one script that loads the constructed test users and prints PASS or FAIL for each check: 1. Scores exist for every user with a mappable category. 2. Share sums to 1 per user. 3. Raw is never below 0. 4. With decay on, the user built to prefer Home & Living scores it above Electronics. With decay off, the order flips. 5. The declared floor is present and not decayed. 6. A bought-then-cancelled order nets to exactly zero. 7. Unmappable and malformed categories are dropped. 8. event_count excludes views under 3 seconds. 9. Both methods are written with method name and model_version. 10. Each fallback rung (ENG-09) is reported for its test user. 11. Method assignment is stable across restarts, and the split is within 2 points. Fix anything that fails. Save the full output (see the Home sheet).

*How to check it is done:* "All 11 checks pass, and the output is saved."

## 2. What was built

### 1. The constructed test users — done

`tests/m1_dataset.py` `build_m1_dataset(now)`: 14 platform users and 62 documents in platform shapes (users, posts, a product and its category tree, a business, a follow, postevents, orders). One user per check (its docstring lists them): `decay`, `floor`, `cancelled`, `unmappable`, `views`, `negative`, `undo`, `rung1`–`rung5`, `nothing`, and the posts' `author`.

### 2. The script — done

`scripts/check_m1.py`:

1. Loads the dataset into a throwaway **platform** database `reco_m1_check_platform`, on the engine cluster (`ML_MONGO_URI`; the platform login is read-only and is never used). The engine database is the throwaway `reco_m1_check`. Both are dropped first and at the end (`--keep` keeps them).
2. Runs the engine as the servers will, each as its own process: `python -m reco.jobs sync` (ENG-04 copies), `interest` (ENG-10, both methods), `popularity` (ENG-09 rung 3).
3. Prints PASS/FAIL for the 11 checks, each with what it saw:

| # | How it is checked |
|---|---|
| 1 | The 10 users with a mappable action or declared interest have rows under both methods; the 4 without have none |
| 2 | Shares sum to 1 (±1e-9) for every user and method |
| 3 | No raw below 0; the Hide user's Home & Living (3 − 5) is stored at 0 and Pets keeps share 1 |
| 4 | Stored decay raws: Home & Living (liked yesterday ×2) above Electronics (liked 60 days ago ×3); the same inputs with decay off (`ScoringContext(decay_enabled=False)`) put Electronics first |
| 5 | Declared Pets with no Pets action: raw exactly 10 under both methods |
| 6 | A Cancelled and a Returned Electronics order: Electronics raw 0; 2 orders reversed |
| 7 | "Cricket" and malformed category values (`None`, `5`, `""`, an object) dropped; no stored category outside the 23 |
| 8 | Views of 2.0 s, 2.999 s, then 4 s and 5 s on one post: Pets `event_count` 1 |
| 9 | Every row has `method` recency_decay or time_windows and the running `model_version`; every scored user has both |
| 10 | `get_profile` per ladder user: rung1 → none, rung2 → `rung_2`, rung3 → `rung_3`, rung4 (read 49 hours later) → `rung_4`, rung5 (engine store read made to fail) → `rung_5` |
| 11 | Two separate Python processes assign 10,000 ids in all three slots: identical; each slot's share on method two within 2 points of its split |

4. Saves the full output to `Tracing/checks/ENG-11_<date>.md`. Exit 0 only if all 11 pass.

## 3. Results

14 Oct 2026, laptop (Windows, Python 3.12, Atlas build cluster): **11 of 11 passed** (`Tracing/checks/ENG-11_2026-10-14.md`). Nothing needed fixing beyond what ENG-10 built; while bringing ENG-10 up on dev, one reader fault was found and fixed first (rows with no `user_model` were skipped; ENG-10 §2 item 1).

## 4. Tests and checklist

Checklist section 11 (`scripts/run_checklist.sh`): 11.1 the ENG-10 reader tests, 11.2 this script, 11.3 M1 on SOCO's real data into `reco_demo`.

## 5. Open

| What | Waits on |
|---|---|
| Run on **test**, save the output to "Wave1A checks", then mark Passed | The test server; the shared folder (Sanjai) |

## 6. Files changed

| File | Change |
|---|---|
| `scripts/check_m1.py` | New |
| `tests/m1_dataset.py` | New: the constructed users |
| `scripts/run_checklist.sh` | Section 11 |

## Pack v1.4 update (15 Oct 2026)

The ENG-29 rework adds two checks to the script: **12. A test account is left out of scoring** (a constructed user with six likes, on the test_accounts list of the run's own settings copy, has no rows) and **13. An unmapped category is reported** (the daily `category_check` job, run on the constructed data, records "Cricket"). The script runs on a copy of `settings/engine.toml` with that test account added; the real file is untouched. Result, 15 Oct 2026: **13 of 13 passed**. ENG-30 asks for ENG-11 to pass again after ENG-10's change: it does.

## Update, 16 Oct 2026

**16 Oct 2026:** Passed (Kala S1).

## Update, 16 Oct 2026: 16 checks (pack v1.4 and Kala's answers)

Three checks added to `scripts/check_m1.py`, with constructed users in `tests/m1_dataset.py`:

| # | Check | How |
|---|---|---|
| 14 | An open return request leaves the purchase out; it comes back when the request ends (ENG-30 points 7, 10) | `returner`: a Delivered Electronics order with an open returnrequests record (with a comment and a phone number planted). After sync + interest: Electronics raw 0, and no personal field in `ml_return_requests`. The request is then set inactive (rejected) with a new updatedAt; after sync + interest the purchase is back (raw 18.23) |
| 15 | The ladder's count of qualified actions equals the count stored with the score (Kala 2a) | For every scored user, `read_path.count_qualified_actions` equals `qualified_actions` on its rows |
| 16 | Actions on your own post or on a seed post are not counted; seed posts don't score (Kala 2a; ENG-30 point 9) | `selfseed`: 3 own-post likes, 3 seed-post likes, 2 ordinary: qualified_actions 2; the seed likes add nothing; the own-post likes still score (Home & Living raw 14.66 = 5 likes) |

Check 7's unmappable label is now "Fishing": since the category map (16 Oct) "Cricket" maps to Sports & Outdoors. Check 13 reports "Fishing".

**Found by check 15 and fixed:** M1's read of the event copies didn't include `is_self`, so own-post likes were counted in `qualified_actions` (5 against the ladder's 2). `writers._M1_EVENT_FIELDS` now reads it.

Result, 16 Oct 2026: **16 of 16 passed** (`Tracing/checks/ENG-11_2026-10-16.md`). Checklist 11.2 expects 16 of 16.

## M1 complete (16 Oct 2026)

Kala's F7 ("ENG-30 is Passed only when the ENG-03, 04, 10, 11 and 29 checks re-run on the ENG-30 code and still pass"): the full checklist ran on the new code on 16 Oct. Every ENG-03 (3.1–3.5), ENG-04 (4.2–4.11), ENG-29 (8.1–8.9), ENG-10 and ENG-11 (11.2, 11.3) line passed. The other failures were test counts that the new tests raised (4.1, 10.2, 11.1, now updated), one test pinning the score's fields (now includes `qualified_actions`), the known laptop speed lines (6.3, 6.4) and the kill demo on a slow link (7.5). Record: `Tracing/checks/Checklist_2026-10-16_F7.md`.

M1 (ENG-09, ENG-10, ENG-11, with ENG-30 points 5, 6, 7, 9, 10 and Kala's answers) is complete on dev.

**16 Oct 2026:** checks 17 (own-post only: count 0, no score) and 18 (the qualifying set) added from Kala's follow-up. **18 of 18 passed.**

## Review of 26 Oct 2026, point 12

"return-request copy not current; M1 runs on the last good copy" in `check_m1.py` came from the **deliberate** freshness rule (ENG-30 point 7: current only after a sync within 24 hours **and** a passed reconciliation): the script synced its throwaway database but never ran a reconciliation there. It now runs `reconcile_sync` after each `sync`, so the line appears only when it is true.

## Update, 26 Oct 2026: check_m1's settings-diary error fixed (review point 3)

`scripts/check_m1.py` printed `could not record the settings change in ml_config_changes … cannot encode object: datetime.date(2026, 10, 26)` and carried on with the change in force. The cause: its settings copy lists the constructed test account with an `expiry` date (`lists.test_accounts`, ENG-29 item 3), and BSON has no date type. The diary now stores a date as its ISO text (`2026-11-02`), and `Tunables` reads it back as a date (ENG-02, *Update, 26 Oct 2026*). Under the new rule a change that cannot be written would not be applied at all, so the test account would no longer be on the list in force.

Re-run on 26 Oct 2026 on the dev laptop, after the fix: **18 of 18 passed**, and the error line is gone from the output (`Tracing/checks/ENG-11_2026-10-26.md`).
