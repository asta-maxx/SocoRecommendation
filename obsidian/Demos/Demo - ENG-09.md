---
tags: [demo]
task: ENG-09
duration: about 5 minutes
---
# Demo: ENG-09, the fallback ladder

## What this demo proves
The Build List's check for ENG-09: *"Test users for each rung get the right rung reported."*

It also shows the ladder on SOCO's real dev users. → [[ENG-09 - Fallback ladder]]

> [!note] Rehearsed on 14 Oct 2026 on my laptop (Windows: use `.venv\Scripts\python.exe` where this says `.venv/bin/python`). Every step only reads. The real engine database `SoCo` is never written to.

## Setup (before the audience watches)
One terminal, in the repo folder. Nothing needs to be running.

## Steps

### 1. One test user per rung
- **Say:** "The ladder has five rungs. For each, a test builds a user who should land on it, and checks they do."
- **Run:**
  ```bash
  .venv/bin/python -m pytest -p no:cacheprovider tests/test_read_path.py -v 2>&1 | grep -E "::|passed"
  ```
- **They should see** (trimmed):
  ```
  test_rung_1_five_actions_and_a_fresh_score PASSED
  test_rung_2_fewer_than_five_with_declared_interests_uses_floor_plus_actions PASSED
  test_rung_2_comes_before_rung_4_for_a_new_user PASSED
  test_rung_3_fewer_than_five_and_nothing_declared_is_platform_popularity PASSED
  test_rung_3_empty_names_itself PASSED
  test_rung_4_a_stale_score_serves_the_old_delivered_score PASSED
  test_rung_4_without_a_delivered_score_falls_to_rung_3 PASSED
  test_rung_5_an_unreadable_store_serves_the_delivered_score_at_once PASSED
  test_rung_5_without_a_delivered_score_is_rung_3_empty PASSED
  ...
  ============================= 20 passed in 1.27s ==============================
  ```

### 2. The rung is reported on every list
- **Say:** "The pack says the rung goes on the answer and on the receipt. This test serves a feed list for each rung and reads both."
- **Run:**
  ```bash
  .venv/bin/python -m pytest -p no:cacheprovider tests/test_recommendations.py -k "each_rung or walk" -v 2>&1 | grep -E "::|passed"
  ```
- **They should see:**
  ```
  test_each_rung_is_reported_on_the_list[answer0-None-False] PASSED
  test_each_rung_is_reported_on_the_list[answer1-rung_2-True] PASSED
  test_each_rung_is_reported_on_the_list[answer2-rung_3-True] PASSED
  test_each_rung_is_reported_on_the_list[answer3-rung_3_empty-True] PASSED
  test_each_rung_is_reported_on_the_list[answer4-rung_4-False] PASSED
  test_each_rung_is_reported_on_the_list[answer5-rung_4_to_3-False] PASSED
  test_each_rung_is_reported_on_the_list[answer6-rung_5-False] PASSED
  test_each_rung_is_reported_on_the_list[answer7-rung_5_to_3_empty-False] PASSED
  test_the_product_surface_does_not_walk_the_interest_ladder PASSED
  ====================== 9 passed, 19 deselected in 1.30s =======================
  ```
- **Point out:** each line reads *rung, step name, newcomer?* Rung 1 has no step (no plan B was needed). Rungs 2 and 3 are newcomers (`True`); 4 and 5 are real fallbacks (`False`).

### 3. The ladder on SOCO's real users
- **Say:** "Now on SOCO's actual dev users. This only reads."
- **Run:**
  ```bash
  .venv/bin/python scripts/show_ladder.py 2>/dev/null | tail -1
  ```
- **They should see:**
  ```
  15 users by step: rung_2 6, rung_3_empty 7, rung_4 1, rung_4_to_3_empty 1
  ```
- **Point out:** most are newcomers (rung 2 picked interests; rung 3 picked none). Rung 3 is *empty* because no view on dev has an on-screen time yet, so the list is simply the newest posts.

### 4. One user in detail: SOCO's old score in use
- **Say:** "This user did plenty, but their score is from 1 October, so too old. The engine uses SOCO's old score instead."
- **Run:**
  ```bash
  .venv/bin/python scripts/show_ladder.py 6a3a6df8bac0b9eb430edc7c 2>/dev/null
  ```
- **They should see** (trimmed):
  ```
  6a3a6df8bac0b9eb430edc7c  RUNG 4  step rung_4
          stored score stale or failed its checks; the old delivered score
            Fashion & Apparel             1.000  raw    32.00
            Shoes & Footwear              0.000  raw     0.00
  ```

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| Rung 1 on real users | No fresh scores on dev: the interest score still reads SOCO's live log, and the nightly job hasn't run since 1 Oct | ENG-10 |
| Rung 3 with real numbers | No view on dev has an on-screen time | Aravinth's APP-02 data → [[Aravinth's tasks]] |
| The same on the test server | Being set up | → [[Environments]] |

## Clean up
Nothing to clean: every step only reads.

## How this connects
- Proves → [[ENG-09 - Fallback ladder]]
- How every demo is run → [[How to demo a task]]
- Previous demo → [[Demo - ENG-08]] · Next demo → [[Demo - ENG-10]]
