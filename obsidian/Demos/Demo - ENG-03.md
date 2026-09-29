---
tags: [demo]
task: ENG-03
duration: about 5 minutes
---
# Demo: ENG-03, reading SOCO's data correctly

## What this demo proves
The Build List's check for ENG-03: *"Unit tests read one of each record type and return the expected values, including a follows record with text ids."* It also shows that the rules fit SOCO's **real** data. → [[ENG-03 - Reading SOCO's data correctly]]

This demo only **reads**. Nothing is changed anywhere, so there's no clean-up.

## Setup
One terminal, in the repo folder. Nothing needs to be running. Make sure the Atlas cluster is awake → [[How to demo a task]].

## Steps

### 1. One of each record type, as the check asks
- **Say:** "SOCO stores 14 kinds of data, each a bit differently. For each one there's a test that reads a real-shaped example and checks every value."
- **Run:**
  ```bash
  .venv/bin/python -m pytest tests/test_platform_records.py -v -k "test_user or test_business or follow or test_post or postevent or test_order or cart or category_and_product or variant or legacy"
  ```
- **They should see** one PASSED line per record type, including **`test_follow_with_text_ids`**, the exact case the pack names.

### 2. The same rules, on every real document
- **Say:** "Tests use examples. This reads every document in SOCO's database through the same rules, without changing anything."
- **Run:**
  ```bash
  .venv/bin/python scripts/check_platform_records.py
  ```
- **They should see** a table of 14 kinds with **0 failed** in every row, ending **`PASS: 0 document(s) could not be read`**. (A warning about "LEGACY_LABEL_MAP" may print first. It comes from the older demo code and doesn't affect this check.)
- **Point out:**
  - `follow … text ids 93/93`: IDs stored as text, read correctly;
  - `post … with a category of the 23 8/8`;
  - `product … category is one of the 23 0/2011`: see step 4.

### 3. Nothing is counted twice
- **Say:** "Clicks, views and feedback are moving from SOCO's old logs to the engine's new one. Each day is read from exactly one of them."
- **Run:**
  ```bash
  .venv/bin/python -m pytest tests/test_platform_records.py -v -k "source or switch or window"
  ```
- **They should see** all PASSED, including **`test_a_window_across_the_switch_reads_each_part_from_one_source`**. → [[Event source switch]]

### 4. What the real data showed
- **Say:** "Reading everything also found a real problem, in SOCO's data rather than my code. None of the 2,011 products sits in one of the pack's 23 categories, because SOCO's category list is different. Aravinth's DB-07 fixes that; until then, products are dropped as the pack says."
- **Show:** the `product … 0/2011` row from step 2.

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The check on the **test** server | It doesn't exist yet | Aravinth's hosting → [[People]] |
| The switch actually happening | The switch date is set by ENG-04 after 7 matching days | ENG-04, then APP-12 |

## Clean up
Nothing: this demo only reads.

## How this connects
- Proves → [[ENG-03 - Reading SOCO's data correctly]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-02]]
- Next demo → [[Demo - ENG-04]]
