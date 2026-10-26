---
tags: [demo]
task: ENG-03
duration: about 6 minutes
---
# Demo: ENG-03, reading SOCO's data correctly

## What this demo proves
The Build List's check for ENG-03 (v1.3): *"Unit tests read one of each record type and return the expected values, including a follows record with text ids, a businessRegister actor, a product post on a platform feed list, and an order with a status log and a return request."* It also shows that the rules fit SOCO's **real** data. → [[ENG-03 - Reading SOCO's data correctly]]

This demo only **reads**. Nothing is changed anywhere, so there's no clean-up.

## Setup
One terminal, in the repo folder. Nothing needs to be running. Make sure the Atlas cluster is awake → [[How to demo a task]].

## Steps

### 1. The four cases the check names
- **Say:** "The pack names four tricky cases: a follow stored with text IDs, a business doing something, a post card on SOCO's feed that shows a product, and an order with a history and a return request. Each has its own test."
- **Run:**
  ```bash
  .venv/bin/python -m pytest tests/test_platform_records.py -v -p no:cacheprovider -k "follow_with_text_ids or businessregister_actor or product_post_on_a_platform_feed or history_and_a_return"
  ```
- **They should see:**
  ```
  test_follow_with_text_ids PASSED
  test_postevent_from_a_businessregister_actor PASSED
  test_a_product_post_on_a_platform_feed_list PASSED
  test_order_with_history_and_a_return_request PASSED
  ======================= 4 passed, 56 deselected in 0.03s =======================
  ```

### 2. The same rules, on every real document
- **Say:** "Tests use examples. This reads every document in SOCO's database through the same rules, without changing anything."
- **Run:**
  ```bash
  .venv/bin/python scripts/check_platform_records.py
  ```
- **They should see** (a warning about "LEGACY_LABEL_MAP" prints first; it comes from the older demo code and doesn't affect this check):
  ```
  kind                        read  failed  time from _id   notes
  user                          15       0              0   active 13/15
  business                      24       0              0
  post                           8       0              0   with a category of the 23 8/8
  postevent                    146       0              0   with an E code 127/146, business actor 6/146, with updated_at 0/146, page visits 0/146
  follow                        93       0              0   text ids 93/93
  order                          8       0              0   with checkout_id 2/8, with tracking_info 8/8, returned 0/8
  cart_line                      2       0              0
  product                     2011       0              0   category is one of the 23 0/2011
  variant                     6029       0              0   in stock 5169/6029
  category                     334       0              0   top level is one of the 23 92/334
  served_list                   12       0              0   fallback lists 12/12
  serve_log                      -       -              -   collection 'rec_serve_log' does not exist yet

  PASS: 0 document(s) could not be read
  ```
  (Re-run 1 Oct after the audit fixes. The `serve_log` line was added by ENG-29: SOCO hasn't created its serve log yet, so there's nothing to read.)
- **Point out:**
  - **0 failed** in every row: 8,682 real documents;
  - `follow … text ids 93/93`: IDs stored as text, read correctly;
  - `postevent … business actor 6/146`: businesses act too, and are recognised;
  - `order … with tracking_info 8/8`: every order's history is there;
  - `product … category is one of the 23 0/2011`: see step 5.

### 3. One place for each kind of data, and no switch
- **Say:** "Every kind of data is read from exactly one place, so nothing is counted twice. The old switch between SOCO's old and new logs is gone: everything comes from the engine's own copy."
- **Run:**
  ```bash
  .venv/bin/python -m pytest tests/test_platform_records.py -v -p no:cacheprovider -k "source"
  ```
- **They should see:**
  ```
  test_each_kind_has_exactly_one_source[event-ml_events] PASSED
  test_each_kind_has_exactly_one_source[served_list-ml_events] PASSED
  test_each_kind_has_exactly_one_source[order-ml_orders] PASSED
  test_each_kind_has_exactly_one_source[return-ml_orders] PASSED
  test_each_kind_has_exactly_one_source[follow_graph-follow] PASSED
  test_each_kind_has_exactly_one_source[block-follower] PASSED
  test_each_kind_has_exactly_one_source[eligibility_state-ml_item_state] PASSED
  test_there_is_no_event_source_switch PASSED
  ======================= 8 passed, 52 deselected in 0.03s =======================
  ```
  → [[Engine sync]] · [[Event source switch]]

### 4. SOCO's 26 kinds of activity, and its screens
- **Say:** "SOCO records 26 kinds of activity. Each one gets the pack's code and a flag saying whether a model uses it. SOCO's screens map to the engine's two, feed and product, and a visit to a post's own page is never counted as seeing a card."
- **Run:**
  ```bash
  .venv/bin/python -m pytest tests/test_platform_records.py -v -p no:cacheprovider -k "native or surface or page_visit or undo"
  ```
- **They should see** (abridged):
  ```
  test_sheet_4_lists_26_native_types PASSED
  test_native_types_map_to_e_codes[click-E3-True] PASSED
  test_native_types_map_to_e_codes[unlike-E9-True] PASSED
  test_native_types_map_to_e_codes[remove_from_cart-E4-False] PASSED
  test_native_types_map_to_e_codes[purchase-E5-True] PASSED
  test_native_surfaces_map_to_engine_surfaces[home_for_you-feed] PASSED
  test_native_surfaces_map_to_engine_surfaces[cart-product] PASSED
  test_native_surfaces_map_to_engine_surfaces[post_detail-None] PASSED
  test_a_post_page_impression_is_a_page_visit PASSED
  test_undo_fields_dwell_and_own_posts_are_kept PASSED
  ====================== 20 passed, 40 deselected in 0.03s =======================
  ```
- **Point out:** `remove_from_cart … False`: kept, but no model uses it yet. → [[Activity events]]

### 5. What the real data showed
- **Say:** "Reading everything also found a real gap, in SOCO's data rather than my code. None of the 2,011 products sits in one of the pack's 23 categories, because SOCO's category list is different. The pack's answer is a category map in the engine's own settings, which I fill in under ENG-29. Until then, products are dropped from category scoring, as the pack says."
- **Show:** the `product … 0/2011` row from step 2. → [[Settings file]]

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The check on the **test** server | It doesn't exist yet | Aravinth's hosting → [[People]] |
| Products counted in a category | The category map is empty | ENG-29 |
| Reading blocks and SOCO's serve log | `followers` is empty and `rec_serve_log` doesn't exist yet | Aravinth; ENG-08, ENG-29 |

## Clean up
Nothing: this demo only reads.

## How this connects
- Proves → [[ENG-03 - Reading SOCO's data correctly]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-02]]
- Next demo → [[Demo - ENG-04]]
