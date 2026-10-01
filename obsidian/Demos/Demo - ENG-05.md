---
tags: [demo]
task: ENG-05
duration: about 5 minutes
---
# Demo: ENG-05, the same method for each user

## What this demo proves
The Build List's check for ENG-05: *"The same user gets the same method across two restarts. Changing a split changes assignment with no deploy. Over 10,000 test ids, the split is within 2 points."*

It also shows where the split lives, why Python's own `hash()` would have been wrong, and the label (`policy_id`) each list carries. → [[ENG-05 - Same method for each user]]

> [!tip] No database and no running engine needed. Choosing a method only needs a user's ID and the settings, so every step runs straight from the terminal, even offline.

> [!important] The split change in step 5 is made on a **throwaway copy** of the settings file (`/tmp/soco-demo-eng05.toml`). The real `settings/engine.toml` is never touched.

> [!note] Rehearsed on 1 Oct 2026. The real settings file was at **version 2**, so the copy in step 5 becomes version **3**. If the file has moved on, use the next number up. The outputs below are the real ones from that run, trimmed, re-run after the label switched to method names.

## Setup (before the audience watches)
One terminal, in the repo folder (`~/vultrx/SocoRecommendation`). Nothing else to start.

The two user IDs used throughout are made up but SOCO-shaped (24 characters):
- `64f1c0ffee0000000000abcd`
- `65a2b3c4d5e6f70812345678`

## Steps

### 1. Where the split lives
- **Say:** "Three parts of the engine each have two methods. Which one a user gets is set here, in the settings file, not in the code."
- **Run:**
  ```bash
  grep -A4 '^\[slots' settings/engine.toml
  ```
- **They should see:**
  ```
  [slots.interest]
  method_one = "recency_decay"
  method_two = "time_windows"
  split = 50
  default_method = "method_one"
  --
  [slots.product_ranking]
  method_one = "attribute_similarity"
  method_two = "bought_together"
  split = 50
  …
  [slots.promoter_score]
  method_one = "shrinkage"
  method_two = "cohort_percentile"
  split = 50
  …
  ```
  The split is the share of users on **method two**: 50 means half. → [[Two methods per slot]], [[Settings file]]

### 2. Why not Python's own hash
- **Say:** "Each user is turned into a number from 0 to 99. Python has a built-in way to do that, but watch what happens when I run it twice."
- **Run:**
  ```bash
  for i in 1 2; do .venv/bin/python -c 'print(hash("interest:64f1c0ffee0000000000abcd") % 100)'; done
  ```
- **They should see:** two **different** numbers (69 and 37 in rehearsal; yours will differ too). Python re-seeds `hash()` every time it starts, so a user would change method on every restart.
- **Then run** the pack's recipe, SHA-256:
  ```bash
  for i in 1 2; do .venv/bin/python -c 'import hashlib; print(int(hashlib.sha256(b"interest:64f1c0ffee0000000000abcd").hexdigest()[:8], 16) % 100)'; done
  ```
- **They should see:** `90` and `90`. The same on every run and every computer.

> [!example] Like a coin that always lands the same way for the same name. Python's `hash()` is a normal coin: toss it again and you might get the other side.

### 3. Same user, same method, across two restarts
- **Say:** "Here are two users' methods in all three slots. Each run of this script is a fresh start of the program: a restart."
- **Run** it twice:
  ```bash
  .venv/bin/python scripts/show_assignment.py 64f1c0ffee0000000000abcd 65a2b3c4d5e6f70812345678
  .venv/bin/python scripts/show_assignment.py 64f1c0ffee0000000000abcd 65a2b3c4d5e6f70812345678
  ```
- **They should see** the same six lines both times:
  ```
  settings settings/engine.toml: config_version 2
    64f1c0ffee0000000000abcd  interest         bucket 90  method_one recency_decay          cfg2.interest-recency_decay
    64f1c0ffee0000000000abcd  product_ranking  bucket 28  method_two bought_together        cfg2.product_ranking-bought_together
    64f1c0ffee0000000000abcd  promoter_score   bucket 19  method_two cohort_percentile      cfg2.promoter_score-cohort_percentile
    65a2b3c4d5e6f70812345678  interest         bucket 23  method_two time_windows           cfg2.interest-time_windows
    65a2b3c4d5e6f70812345678  product_ranking  bucket 95  method_one attribute_similarity   cfg2.product_ranking-attribute_similarity
    65a2b3c4d5e6f70812345678  promoter_score   bucket 45  method_two cohort_percentile      cfg2.promoter_score-cohort_percentile
  ```
- **Point out:**
  - Each user has a **different bucket in each slot**: the slot's name is mixed in, so the three choices are independent.
  - Bucket below 50 → method two; 50 or above → method one.
  - The last column is the label each list carries: `cfg2.interest-recency_decay` means "settings version 2, interest slot, recency decay". It names the method rather than saying "1" or "2", so it stays true even after the methods are swapped round to promote a winner. A real feed list joins its two slots: `cfg2.interest-recency_decay.promoter_score-cohort_percentile`. → [[Served list record]]
- **Then run** the automatic check, which starts Python twice more with 50 random users:
  ```bash
  .venv/bin/python -m pytest tests/test_assignment.py -p no:cacheprovider -k restarts -v
  ```
- **They should see:** `test_same_method_across_restarts PASSED`, `1 passed`.

### 4. Over 10,000 users, the split is within 2 points
- **Say:** "A split of 50 should put about half the users on each method. Let's count 10,000."
- **Run:**
  ```bash
  .venv/bin/python scripts/show_assignment.py
  ```
- **They should see:**
  ```
  settings settings/engine.toml: config_version 2
    interest         split 50  method two 50.21%  (within 2 points)
    product_ranking  split 50  method two 49.72%  (within 2 points)
    promoter_score   split 50  method two 50.59%  (within 2 points)
  ```
  The 10,000 test IDs are fixed, so these numbers are the same every run.
- **Optional, other splits** (10,000 random IDs each time, at 50, 25, 10 and 0):
  ```bash
  .venv/bin/python -m pytest tests/test_assignment.py -p no:cacheprovider -k ten_thousand -v
  ```
  **They should see:** four `PASSED` lines (`[50]`, `[25]`, `[10]`, `[0]`), `4 passed`.

### 5. Change the split: users move, with no new code
- **Say:** "Now I turn the dial from 50 to 20 in every slot, on a copy of the settings. No code changes, nothing is redeployed."
- **Run:**
  ```bash
  cp settings/engine.toml /tmp/soco-demo-eng05.toml
  sed -i '' 's/^split = 50/split = 20/; s/^config_version = "2"/config_version = "3"/; s/^changed_by = "Allen"/changed_by = "Demo"/' /tmp/soco-demo-eng05.toml
  grep -n '^config_version\|^changed_by\|^split' /tmp/soco-demo-eng05.toml
  ```
- **They should see:**
  ```
  16:config_version = "3"
  17:changed_by = "Demo"
  40:split = 20
  46:split = 20
  52:split = 20
  ```
  Every change needs a new version number and a name; the engine refuses a change without one. → [[Settings file]]
- **Run** the same two users on the copy:
  ```bash
  SETTINGS_FILE=/tmp/soco-demo-eng05.toml .venv/bin/python scripts/show_assignment.py 64f1c0ffee0000000000abcd 65a2b3c4d5e6f70812345678
  ```
- **They should see:**
  ```
  settings /tmp/soco-demo-eng05.toml: config_version 3
    64f1c0ffee0000000000abcd  interest         bucket 90  method_one recency_decay          cfg3.interest-recency_decay
    64f1c0ffee0000000000abcd  product_ranking  bucket 28  method_one attribute_similarity   cfg3.product_ranking-attribute_similarity
    64f1c0ffee0000000000abcd  promoter_score   bucket 19  method_two cohort_percentile      cfg3.promoter_score-cohort_percentile
    65a2b3c4d5e6f70812345678  interest         bucket 23  method_one recency_decay          cfg3.interest-recency_decay
    65a2b3c4d5e6f70812345678  product_ranking  bucket 95  method_one attribute_similarity   cfg3.product_ranking-attribute_similarity
    65a2b3c4d5e6f70812345678  promoter_score   bucket 45  method_one shrinkage              cfg3.promoter_score-shrinkage
  ```
- **Point out:**
  - The **buckets didn't change** (90, 28, 19, 23, 95, 45). Only the line moved.
  - Buckets 20 to 49 moved to method one: three of the six lines changed. Bucket 19 is still below 20, so it stayed on method two.
  - The labels now start `cfg3`: every list says which settings version made it.
- **Run** the 10,000 count on the copy:
  ```bash
  SETTINGS_FILE=/tmp/soco-demo-eng05.toml .venv/bin/python scripts/show_assignment.py
  ```
- **They should see:**
  ```
  settings /tmp/soco-demo-eng05.toml: config_version 3
    interest         split 20  method two 19.55%  (within 2 points)
    product_ranking  split 20  method two 20.19%  (within 2 points)
    promoter_score   split 20  method two 20.01%  (within 2 points)
  ```
- **If asked "and in the running engine?":** the engine re-reads the settings file every 30 seconds, and looks up the split each time it's asked, so the next list after that uses the new split. The automatic check proves it inside one running program:
  ```bash
  .venv/bin/python -m pytest tests/test_assignment.py -p no:cacheprovider -k no_deploy -v
  ```
  **They should see:** `test_a_split_change_moves_users_with_no_deploy PASSED`, `1 passed`. The engine picking up a file change live is shown in [[Demo - ENG-02]], step 5.

### 6. The dial has limits
- **Say:** "The pack says the split stays between 0 and 50. Try 60."
- **Run:**
  ```bash
  sed -i '' '40s/split = 20/split = 60/' /tmp/soco-demo-eng05.toml
  SETTINGS_FILE=/tmp/soco-demo-eng05.toml .venv/bin/python scripts/show_assignment.py
  ```
- **They should see:**
  ```
  settings file rejected: outside the Settings sheet's rules: slots.interest.split: Input should be less than or equal to 50
  ```
  The running engine would do the same: refuse the file, log why, and keep the settings it had.

### 7. A slot left out of the settings: everyone gets the default
- **Say:** "What if someone deletes a whole slot from the settings by mistake? The pack says: everyone gets the default, say so, and keep serving."
- **Run** (a second throwaway copy, without the interest section):
  ```bash
  awk '/^\[slots.interest\]/{skip=1;next} /^\[/{skip=0} !skip' settings/engine.toml > /tmp/soco-demo-eng05-noslot.toml
  SETTINGS_FILE=/tmp/soco-demo-eng05-noslot.toml .venv/bin/python scripts/show_assignment.py
  ```
- **They should see:**
  ```
  settings file has no [slots.interest]: everyone gets the default method there
  settings /tmp/soco-demo-eng05-noslot.toml: config_version 2
    interest         split  0  method two  0.00%  (within 2 points)
    product_ranking  split 50  method two 49.72%  (within 2 points)
    promoter_score   split 50  method two 50.59%  (within 2 points)
  ```
  The first line is the error the engine logs. Nobody is on method two for interest; the other two slots are untouched. → [[Logs]]

### 8. Missing settings or a missing user: the safe default
- **Say:** "The automatic checks cover the rest: settings that can't be found at all, a slot left out, and a request with no user ID. In every case, method one, and the list is still served."
- **Run:**
  ```bash
  .venv/bin/python -m pytest tests/test_assignment.py -p no:cacheprovider -k 'missing or left_out' -v
  ```
- **They should see:**
  ```
  test_missing_settings_give_everyone_the_default_and_log_it PASSED
  test_a_slot_left_out_of_the_file_gives_everyone_the_default PASSED
  test_a_missing_user_id_gets_the_default_in_every_slot PASSED
  3 passed, 12 deselected
  ```
  The first two also check that an ERROR line is written to the [[Logs]].

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The checks on the **test** server | Every check is meant to run on test. It doesn't exist yet, so this runs on my laptop. The steps work unchanged there | The test server ([[ENG-01 - Engine home and databases]]) |
| The label on a real served list | Shown with serving, which needs the database and a surface switched on | [[Demo - ENG-06]] |
| Users per method, counted on real traffic | Needs live lists and the weekly report | ENG-24 |

## Clean up
```bash
rm /tmp/soco-demo-eng05.toml /tmp/soco-demo-eng05-noslot.toml
```
Nothing else: no database was written and no engine was started.

## How this connects
- Proves → [[ENG-05 - Same method for each user]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-04]]
- Next demo → [[Demo - ENG-06]]
