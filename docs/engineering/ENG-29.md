# ENG-29: Adapt the platform reader and sync to the platform as built

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days, proposed estimate) |
| **Waits on** | ENG-03 (built: the platform reader), ENG-04 (built: the engine sync) |
| **Needed by** | ENG-06, ENG-08, ENG-10, ENG-16, ENG-21, ENG-27 (and ENG-23, which runs on the item 8 data) |
| **Status** | **Built** (1 Oct 2026, on dev). All eight parts are built and the row's unit tests pass. Item 1 waits on Allen filling `lists.category_map` (42 labels unmapped on dev); item 7 waits on APP-15 creating `rec_serve_log`; item 8's data lives on the dev engine cluster until the test cluster exists (ENG-01). Becomes Passed when re-run on **test**. Audit fixes the same day (`6c3ef46`, `2b585af`): item 6's `item_type` settled (question 4); `rec_serve_log` read append-only by `_id` with an overlap re-read, time field `at` first (F80); unknown tracking stages logged (DS-017 §6.4). Questions 3, 4, 5 and 12 are answered |
| **Spec** | Build List v1.3 ENG-29 (and Changes sheet v1.3: APP-09, DB-04, DB-07, DB-09, DB-11, DB-13, APP-11, APP-20 "Not needed"); DS-017 v2.5 §4.3 (serve log), §6.4 (who cancelled), §7 (sync sources); SDA v1.6 (engine sync reads `rec_serve_log`); Capture Register (29 Sep) X-16, X-17, X-18, X-20, X-21, F75, F80 |

> **Why a separate item.** Build List v1.3, Changes sheet: ENG-29 is *"New. Holds every 29 September adaptation that would otherwise change ENG-01 to ENG-04, which are built and left unchanged."* So this item adds on top of ENG-03 and ENG-04; their own rows stay as they were.

---

## 1. What the item requires

The Build List v1.3 row, *What to build*, verbatim:

> ENG-01 to ENG-04 are built and stay as they are. This item adds, on top of them, what the 29 September review changed. Where ENG-03 or ENG-04 mention orders.statusLog, return_info, the delivered-list record or engine_position, this item replaces them: the platform does not have those.
>
> 1. Category map: a mapping in the engine's settings from the platform's categories (the global master tree and older seller categories) to the 23. It must cover every category in use. A daily check reports any unmapped category to the service owner, and an item in an unmapped category is left out of category scoring until it is mapped, never guessed.
> 2. Spelling and order-status maps in the settings: status fields compared ignoring case (for example Activate and Activated), and the exact stored value of a return request (Return Requested).
> 3. Exemption and test-account lists in the settings: each entry with the account id, the reason, an expiry and who changed it; every change is logged in ml_config_changes. Exempt accounts are flagged but never actioned (ENG-21). Test accounts are left out of learning, measurement and fraud.
> 4. Order history: tracking_info (APP-08) is the history of each order: the first time it reached Delivered, a return request, a cancellation, and who acted (read from the entry, with order_status and buyer_approval_status). Cancel reasons are stored when present and not used for scoring. Status changes the sync observes itself (ENG-04 point 9, if built) are kept as a cross-check only. The daily reconciliation compares tracking_info in place of statusLog and return_info.
> 5. Returns: an order that has reached Return Requested or Returned is returned. Partial refunds are not modelled in Wave 1A.
> 6. Item adapter: the engine returns items in the shape the app already uses. On the feed, a post card showing a product keeps its post id as item_id, with item_type as the app expects, and every item also carries post_id and product_id as separate fields, so a post id is never read as a product id. Product rails carry product ids. The capture register (X-16) holds the same mapping, and the sync reads platform lists with it.
> 7. Lists shown unchanged: SOCO_BE never drops or renumbers engine lists (APP-15), so there is no delivered-list record and no engine_position; the position on an event is the engine's position. Add rec_serve_log (APP-15) to the sync, read the same way as recommendationrequests.
> 8. Engine test environment: fill the engine's test environment with constructed platform-shaped data (the platform collections the engine reads, with test records), for the engine tests in ENG-23.

**How to check it is done:**

> Unit tests: an unmapped category is reported; a test account is left out of scoring; an order with tracking_info and a return request reads correctly; a product post on a feed list keeps post_id and product_id apart; rec_serve_log rows are copied. The test environment holds the constructed data.

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–8 are the Build List's parts, A–C are extras. Commit `f7c82f3` (1 Oct 2026) unless noted. Several parts were already built inside ENG-03 and ENG-04 on 1 Oct (their docs say so); this item adds the rest.

### 1. Category map, and the daily unmapped-category check: built; ⏳ the map itself is Allen's to fill

**The map (from ENG-03):** `lists.category_map` in `settings/engine.toml` (platform category name, any case → one of the 23). `reco.platform.categories.canonical_name(vocabulary, label, category_map)` matches **by name first** (case and spacing ignored), then through the map; the map's target must itself be one of the 23, else the label is dropped. Nothing is guessed and the legacy label map is never consulted. An item whose category matches neither is left out of category scoring (ENG-03 §3).

**New: the daily check.**

- `reco.platform.fetch.categories_in_use(settings)`: every category label the platform uses, counted by where it's used:
  - `posts.categories` → "posts";
  - `users.interest` → "user interests";
  - `businessregisters.category` → "businesses";
  - products: the top of the product's category path, `categoryPathIds[0]`, else `basicInfo.categoryId`, looked up in the `categories` tree (`path[0]`, else `name`) → "products". A product with neither id is counted under the label `"(no category id)"`; an id missing from the tree under `"(category id … not in the tree)"`.
- `fetch.unmapped_categories(settings)`: the labels for which `canonical_name(…, category_map)` is `None`, as `{label, used_by, items}`, most-used first.
- `reco/jobs/category_check.py`, `check_categories(settings)`, job `python -m reco.jobs category_check`:
  - records one document per IST day in `ml_measurements`: `{measure: "unmapped_categories", day, checked_at, count, items, unmapped: [first 200]}` (replaced on a re-run the same day; `writers.record_measurement`);
  - if any label is unmapped, raises the alert `reason: unmapped_categories` to the service owner (`reco.monitoring.alerts`, ENG-04 part 7) with the count and the first 20 labels;
  - runs inside `recorded_run(settings, "category_check")`, so every run is in `ml_job_runs` (SD-21; detail `{unmapped: n}`).
- **Daily:** added to the nightly list. `reco.jobs.scheduler.NIGHTLY = ("interest", "category_check", "reconcile_sync")`, so it runs at 2 AM IST every day (ENG-07). It runs before the reconciliation, which stays last (SD-22).

*"Older seller categories" (the row's wording):* **answered 1 Oct 2026** (question 12, `Tracing/REALIGNMENT_v1.3.md`, "Questions (reviewed 1 Oct 2026)"): they are `businessregisters.category` (free text) and the category tree (`categories`), both read here. The daily check already covers both, so nothing changed in the code.

**Real run, 1 Oct 2026, dev platform (read-only), into `reco_demo`:** **42 unmapped labels** covering 2,064 uses. The two largest are product categories whose top level is `Menswear catimp…` (1,005 and 1,000 products); then `Fashion` (3 user interests, 1 product), `Sports`, `Food`, `Business`, `Nature`, `Automobiles`, …, `Cricket`, `(no category id)`. The map is empty, so every label not spelled exactly as one of the 23 is unmapped. **Filling the map is Allen's decision**; re-run the job to see the current list (it prints labels and counts only, never user ids).

### 2. Spelling and order-status maps in the settings: built

- **Status spellings (new use):** `lists.status_spellings` (stored spelling → the value compared with). Keys and values are lower-cased and trimmed by a validator (`Lists._lower_keys`). `reco.platform.records.status_is(value, expected)` now maps both sides through it before comparing ignoring case, so `{"activated": "activate"}` makes `Activated` read as `Activate`. `records.spellings_of("activate")` returns every stored spelling that reads as `activate`. (It also built the case-insensitive regex of the product "servable" filter `fetch._servable` in `read_newest`; that database pre-filter was **removed on 1 Oct 2026**, `d1e5427`, so that ENG-08 logs every exclusion; the eligibility rules apply `status_is` instead.) The map is empty today (dev uses `Activate` only).
- **Order-status values (from ENG-03):** `lists.order_status` holds the exact stored values: `Delivered`, `Cancelled`, `Rejected`, `Return Requested`, `Returned` (AS-23).
- **New: tracking stages.** `lists.tracking_stages` (settings **version 3**): the beginning of a `tracking_info` entry's text → a stage, one of `created, accepted, confirmed, shipped, paid, delivered, return_requested, returned, cancelled, rejected`. Matched ignoring case; **the longest matching beginning wins** (`records.tracking_stage`).

  *Why:* on dev, `tracking_info` entries are free text with keys `status`, `timestamp`, `_id`: "Order created by Rahul", "Order Accepted By Seller", "Confirmed by buyer", "Shipped by seller", "Payment Completed", "Delivered (Urban Vogue Fashion Studio)", "Cancelled by seller". *Choice (the pack is silent on the text of an entry); rule it satisfies: item 2, "spelling and order-status maps in the settings", and item 4, which reads Delivered, a return request and a cancellation from the entry.* Being a setting, a new wording is a settings change (logged), not a code change.

  **Real dev orders, 1 Oct 2026:** 8 orders, 14 entries; every entry matched a stage (created 8, accepted 1, confirmed 1, shipped 1, paid 1, delivered 1, cancelled 1).

  **Fix, 1 Oct 2026 (audit, `2b585af`): an entry with no stage is logged.** DS-017 §6.4 says any other value is *stored and logged, never rejected*. An entry whose text matches no beginning was already stored with `stage: None`; now the sync (`copies.make_copy`, orders) also logs a WARNING `tracking_info entries with no stage` on `reco.sync`, with `order_id` and up to 5 of the texts, so a new wording is noticed and can be added to `[lists.tracking_stages]`. Test: `tests/test_sync.py::test_an_order_history_entry_with_no_stage_is_logged`.

  Also fixed the same day: the sync's own `status_history` (ENG-04 part 9, kept as the cross-check) now compares statuses with `records.status_is`, ignoring case and spellings, so `Delivered` then `delivered` is not two steps.

### 3. Exemption and test-account lists: built

- **The lists (from ENG-02/ENG-03 settings):** `lists.exemptions` and `lists.test_accounts`, each entry an `AccountEntry {account_id (24-character id, lower-cased), reason, expiry (date), changed_by}`.
- **New helper:** `reco/config/accounts.py`:

  | Function | Meaning |
  |---|---|
  | `active(entries, today)` | ids whose `expiry >= today`: an entry counts **through** its expiry day |
  | `test_account_ids(today)` | the active test accounts in the settings in force |
  | `is_test_account(id)` | left out of learning, measurement and fraud; the only accounts internal mode serves |
  | `is_exempt(id)` | flagged by fraud rules, never actioned |

- **Logged:** a list change is a settings change, so `live.differences` records it in `ml_config_changes` with old and new value and who made it (ENG-02 item 4). Test: `test_a_list_change_is_a_settings_change_with_who_changed_it`.
- **Left out of learning (M1, now):** `reco.jobs.refresh.refresh` drops test accounts from the users it scores and counts them as `RefreshRun.test_accounts_skipped` (in the run summary: "Test accounts left out: n").
- **Internal mode (ENG-06):** `reco/api/recommendations.py` now calls `accounts.is_test_account` (its private copy was removed).
- **Later users:** measurement (ENG-25) and fraud (ENG-21) will use the same helper; exemptions are flagged, not actioned, in ENG-21 (X-21). Both lists are empty today. Popularity used by the fallback ladder's rung 3 must also leave test accounts out ("left out of learning"); that waits on ENG-09.
- **Test accounts and fraud: answered 1 Oct 2026** (question 5, `Tracing/REALIGNMENT_v1.3.md`, "Questions (reviewed 1 Oct 2026)"): test accounts are **left out of fraud entirely**; exempt accounts are flagged, never actioned. The Build List (this row, item 3, and X-21) outranks the Fraud Policy's §11 wording. ENG-21 applies it.

### 4. Order history from `tracking_info`: built

`records.parse_order(doc, statuses, stages)`:

- `tracking`: the entries, **sorted by time**, each a `TrackingEntry {status (text as stored), at, stage, actor}`. `actor` is `"buyer"` / `"seller"` when the text contains "by buyer" / "by seller" (`records.tracking_actor`), else `None`.
- New fields on `OrderRecord`: `delivered_at` (the **first** entry at stage `delivered`), `return_requested_at`, `returned_at`, `cancelled_at` (first `cancelled` or `rejected`).
- `cancelled_by`: from `order_status` + `buyer_approval_status` first (DS-017 §6.4: "Cancelled is by the buyer; Rejected with buyer_approval_status Rejected By Seller is by the seller; Rejected with buyer_approval_status Rejected is by the buyer"), else the cancelling entry's actor.
- `cancel_reasons`: whatever reason fields exist, stored, never scored (DB-04 and APP-11 are *Not needed*).
- The stage map comes from the settings in force (`live.current().lists.tracking_stages`) unless a caller passes its own; the sync's copies (`copies.make_copy`) and `fetch.read_records` use the settings'.
- **ENG-04 part 9** (the sync's own `status_history`) stays, as the cross-check the row asks for. **The reconciliation** already compares `tracking_info` in place of `statusLog` and `return_info` (ENG-04 §2.8).

### 5. Returns: built

`is_returned` = `order_status` is `Return Requested` or `Returned` (the exact stored values, item 2), **or** the history has a `return_requested` or `returned` stage. So an order returned and later moved on still counts as returned (X-18). Partial refunds are not modelled (as the row says).

### 6. Item adapter: built in ENG-03 and ENG-06

Nothing new in commit `f7c82f3`:

- **Reading** (ENG-03, `records.card_identity`): a platform event or list row for a post card showing a product gives `item_id` = the post id, `post_id` = the post id and `product_id` = the product id, kept apart (X-16, F75).
- **Serving** (ENG-06): every response item carries `item_id`, `item_type`, `post_id`, `product_id`; a feed post card keeps the post id as `item_id`; product rails carry product ids.

**Answered 1 Oct 2026 (question 4; commit `6c3ef46`):** the `item_type` of a post
card that shows a product ("as the app expects") is **`product`**, with `item_id`
= `post_id` = the post id and `product_id` = the product. Source: the Capture
Register's F10 note (28 Sep), *"On platform feed lists, item_type product with a
post id is a post card showing a product: read post_id = item_id (X-16)"*, and
the real feed clicks on dev. ENG-06's `_post_card` now returns it that way (it
returned `post` before); a plain post card stays `post`. See ENG-06 §2.11.

Test: `test_a_product_post_on_a_feed_list_keeps_post_id_and_product_id_apart` (the row's check).

### 7. `rec_serve_log` in the sync: built; ⏳ the collection doesn't exist yet

- **Record:** `records.ServeLogRecord` / `parse_serve_log(doc)`: `request_id` (opaque), `user_id`, `native_surface`, `surface`, `page`, `origin` (engine | fallback | cache), `outcome` (ok | timeout | error | off | skipped), `elapsed_ms`, `created_at` (its **`at`** field first, since 1 Oct, F80; else `time`, `timestamp`, `created_at`, else the `_id` time), `updated_at`. Fields from DS-017 §4.3 and F80 (*"request_id, user_id, surface, page, origin, outcome, elapsed_ms, at"*). `serve_log` added to `RECORD_KINDS`.
- **Sync:** a fourth `SyncSource` in `reco/sync/copies.py`: `rec_serve_log` → `ml_events`, copied as `event_type: "serve_log"`, `event_code: None`, `scored: False`, marked **`append_only=True`**:
  - **backfill** by `_id`, as for every source;
  - **incremental: by `_id`**, carrying on from the backfill's position (`backfill.after_id` in the sync state), and first stepping back `events.sync_overlap_minutes` (2) by `_id` time, because several SOCO_BE servers write it and `_id`s can arrive slightly out of order. Copies are upserts keyed on `_id`, so a re-read never duplicates (the pass's "copied" count includes re-read rows);
  - **daily reconciliation** by its time fields (`at`, `time`, `timestamp`, `created_at`), comparing **`origin`, `outcome`, `elapsed_ms`** (no `updated_at`).

**Fix, 1 Oct 2026 (`6c3ef46`, `2b585af`): `rec_serve_log` is append-only.** This
doc said before that it was read *"incremental by `updated_at`"*, so new rows were
copied only by the backfill and the daily reconciliation, about a day late
(question 3). Question 3 is **answered** (`Tracing/REALIGNMENT_v1.3.md`,
"Questions (reviewed 1 Oct 2026)"): DS-017 §4.3 says SOCO_BE *"writes one row to
rec_serve_log"* per list request, so a row is written once and needs no
`updated_at`; the sync reads new rows by `_id`. Reading by `_id` is still "the same
way as recommendationrequests" for its backfill; the row's wording does not require
an `updated_at`. The overlap re-read and the `at` field came with the audit
(`2b585af`). Test: `tests/test_sync.py::test_a_serve_log_row_written_slightly_out_of_order_is_still_copied`
(a row stamped 30 s earlier, landing after the first was copied, is still copied).
- **On dev, 1 Oct:** the collection doesn't exist yet (APP-15). The sync's pass reports `rec_serve_log: 0` and its backfill as done; ENG-04's checklist line 4.10 now expects **4** sources with `backfill done`.
- **No delivered-list record, no `engine_position`:** none was ever built (ENG-03 part 7 reads the event's position as the engine's).

### 8. Engine test environment with constructed data: built (on the dev engine cluster for now)

- `tests/platform_dataset.py`, `build_dataset(now)` → `(collections, CASES)`: **56 documents** in all **13** platform collections the engine reads (users 10, businessregisters 2, follows 3, followers 1, categories 3, products 4, productvariants 2, posts 11, postevents 10, orders 5, carts 1, recommendationrequests 1, rec_serve_log 3), in the platform's own field names. **41 named cases**, so a test finds "the hidden post" by key, not position, among them: hidden, private, deranked, under-review, adult and unmapped-category posts; private and inactive authors; a blocker; test and exempt accounts; a minor; out-of-stock, inactive, no-category and `Activated` products; orders delivered, return requested, cancelled by seller, incognito and with no incognito value; a like and its unlike; a feed product click with no `item_id`; a post-detail impression; a fallback list; three serve-log rows (engine, fallback, cache). Ids are fixed (stamped 1 Sep 2026 + a counter), so a seeded database is the same every time.
- `scripts/seed_test_platform.py <name>` writes it into a database **on the engine cluster** (the platform login is read-only), emptying each collection first, then parses every document back through the ENG-03 parsers. It refuses any name without "test" and the configured platform and engine databases.
- **Seeded, 1 Oct 2026:** `soco_engine_test` on the dev engine cluster: "56 documents in soco_engine_test; 41 named cases; all parse". It moves to the test cluster when that exists (ENG-01's remainder). To point the engine at it: `APP_MONGO_URI=<engine cluster URI> APP_MONGO_DB=soco_engine_test`.
- **Assumed:** the shape of `followers` (empty on dev, fields undocumented). The data assumes `userId` (blocker), `followerId` (blocked), `status: "blocked"`. Question 16, still open (Aravinth, or the backend code).

### A. Extra: settings version 3

`config_version` raised from "2" to "3" for the new `[lists.tracking_stages]` table (the file's rule: every change raises the version and is logged in `ml_config_changes`). Scores and served lists written since carry `config_version 3` / `cfg3…` policy ids.

### B. Extra: the category check is a recorded nightly job

Beyond "a daily check", it is recorded in `ml_job_runs` and its result in `ml_measurements`, so a day without a check, or a rising count, is visible (SD-21). See part 1.

### C. Extra: the seeder checks its own data

`scripts/seed_test_platform.py` parses every document it wrote through the ENG-03 parsers and exits non-zero if any fails, so the test environment can't silently hold data the reader rejects. Checklist line 8.9.

---

## 3. Configuration reference

`settings/engine.toml`, `config_version = "3"` (was "2"), validated in `reco/config/tunables.py` (`Lists`):

| Setting | Value (1 Oct 2026) | Rule |
|---|---|---|
| `lists.category_map` | `{}` | platform label → one of the 23; target must be one of the 23 (item 1) |
| `lists.status_spellings` | `{}` | stored spelling → compared value; keys lower-cased (item 2) |
| `lists.tracking_stages` | 10 entries (below) | text beginning → stage; ignoring case, longest wins (items 2, 4). **New** |
| `lists.order_status` | `Delivered`, `Cancelled`, `Rejected`, `Return Requested`, `Returned` | exact stored values (item 2) |
| `lists.exemptions` | `[]` | `{account_id, reason, expiry, changed_by}` (item 3) |
| `lists.test_accounts` | `[]` | same shape (item 3) |

`lists.tracking_stages`: `"order created" = "created"`, `"order accepted" = "accepted"`, `"confirmed" = "confirmed"`, `"shipped" = "shipped"`, `"payment completed" = "paid"`, `"delivered" = "delivered"`, `"return requested" = "return_requested"`, `"returned" = "returned"`, `"cancelled" = "cancelled"`, `"rejected" = "rejected"`.

No new environment variables. Code constants: `scheduler.NIGHTLY` gains `category_check`; `category_check` keeps 200 labels in the measurement and lists 20 in the alert.

---

## 4. Environments

| Environment | State (1 Oct 2026) |
|---|---|
| dev (laptop; engine DB `SoCo`) | Everything built. Category check run (42 unmapped). `soco_engine_test` seeded on the dev engine cluster |
| test | Doesn't exist yet (ENG-01's remainder). `soco_engine_test` is seeded there when it does, and the row's check is re-run there |
| production | Not yet. Test accounts and exemptions go in its settings file as the accounts are named (DB-11) |

---

## 5. Tests

`tests/test_platform_dataset.py`: **14 tests** (11 without a database, 3 marked `mongo`), on the constructed data. The `mongo` ones seed it into the throwaway `<TEST_MONGO_DB>_platform` database.

| The row's check | Test |
|---|---|
| an unmapped category is reported | `test_an_unmapped_category_is_reported` (Cricket, Fashion and "(no category id)" reported; gone once mapped); `test_an_unmapped_category_is_left_out_until_the_map_covers_it` (and a map to a non-category is refused) |
| a test account is left out of scoring | `test_a_test_account_is_left_out_of_scoring` (`test_accounts_skipped == 1`); `test_the_account_lists_respect_expiry`; `test_a_list_change_is_a_settings_change_with_who_changed_it` |
| an order with `tracking_info` and a return request reads correctly | `test_an_order_with_tracking_info_and_a_return_request_reads_correctly` (stages created → delivered → return_requested, both times, `is_returned`, actor buyer); `test_the_first_delivery_is_kept_from_free_text_entries`; `test_a_cancellation_reads_who_acted_and_keeps_the_reason_unscored`; `test_a_tracking_entry_by_buyer_decides_when_the_status_fields_do_not` |
| a product post on a feed list keeps `post_id` and `product_id` apart | `test_a_product_post_on_a_feed_list_keeps_post_id_and_product_id_apart` |
| `rec_serve_log` rows are copied | `test_a_serve_log_row_reads`; `test_rec_serve_log_rows_are_copied` (3 copied, origins engine/fallback/cache, and the returned order's copy has `is_returned` and `return_requested_at`) |
| the test environment holds the constructed data | `test_every_constructed_document_reads` (all 13 collections, every document parses); and the seeder (checklist 8.9) |
| item 2 | `test_status_spellings_map_a_stored_spelling` |

`tests/test_sync.py` was updated for the fourth source (`test_the_sync_reads_the_four_sources`; the reconciliation test expects 4 sources).

```bash
TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q tests/test_platform_dataset.py
```

**Results, 1 Oct 2026:**
- `tests/test_platform_dataset.py`: **14 passed** (re-run with `TEST_MONGO_DB=reco_demo`: 14 passed).
- Full suite (`TEST_MONGO_DB=reco_test_eng29doc`): **598 passed, 1 skipped**.

**After the audit fixes, 1 Oct 2026** (`6c3ef46`, `2b585af`, `964f4ec`):
- `test_rec_serve_log_rows_are_copied` now counts the copies in `ml_events` (3) instead of the pass's "copied" figure, because the append-only overlap re-reads recent rows on purpose (`964f4ec`).
- New in `tests/test_sync.py`: `test_a_serve_log_row_written_slightly_out_of_order_is_still_copied`, `test_an_order_history_entry_with_no_stage_is_logged`.
- Full suite: **634 passed, 1 skipped**.

`scripts/run_checklist.sh` section 8 (8.1–8.9): the row's checks by test (8.1–8.7), the real category check on SOCO's dev data into `reco_demo` (8.8, expects `"outcome": "succeeded"`), and the seeder (8.9, expects `all parse`). Section 4's line 4.10 now expects 4 sources.

---

## 6. Runbook

```bash
# Today's unmapped categories (alert if any; result in ml_measurements, run in ml_job_runs).
.venv/bin/python -m reco.jobs category_check

# Re-seed the engine test environment with the constructed data.
.venv/bin/python scripts/seed_test_platform.py soco_engine_test
```

**Mapping a category:** add `"<platform label>" = "<one of the 23>"` under `[lists] category_map`, raise `config_version`, set `changed_by`. The engine picks it up on the next settings reload and logs the change in `ml_config_changes`; the next `category_check` drops the label from the report. A target that isn't one of the 23 is ignored, so the label stays reported.

**Adding a test account or exemption:** add `{ account_id = "<24-char id>", reason = "…", expiry = YYYY-MM-DD, changed_by = "…" }` to `test_accounts` or `exemptions`, raise `config_version`. It counts through its expiry day.

**A new `tracking_info` wording** (an entry with `stage` `None` in a copy): add its beginning to `[lists.tracking_stages]`, raise `config_version`.

---

## 7. Open

| Open item | Waits on |
|---|---|
| Fill `lists.category_map` so every category in use maps (42 unmapped on 1 Oct, incl. 2,005 products under `Menswear catimp…`) | **Allen** (a decision per label) |
| `rec_serve_log` on the platform | **APP-15** (Aravinth) |
| The `followers` shape assumed in the constructed data | Question 16 (Aravinth, or the backend code; and ENG-08) |
| Test accounts left out of popularity (the fallback ladder's rung 3) | ENG-09 |
| Test accounts left out of measurement | ENG-25 (calls `accounts.is_test_account`) |
| Test accounts left out of fraud; exemptions flagged, never actioned | ENG-21 (same helper) |
| Seed `soco_engine_test` on the test cluster and re-run the checks there; then Passed | ENG-01's remainder (the test cluster) |

Answered on 1 Oct 2026 and removed from this list (`Tracing/REALIGNMENT_v1.3.md`,
"Questions (reviewed 1 Oct 2026)"): **3** (`rec_serve_log` needs no `updated_at`;
read by `_id`, item 7), **4** (`item_type` `product` for a post card showing a
product, item 6), **5** (test accounts left out of fraud entirely, item 3), **12**
(older seller categories are `businessregisters.category` and the category tree,
item 1).

---

## 8. Files changed

Commit `f7c82f3` (1 Oct 2026):

| File | Change |
|---|---|
| `reco/config/accounts.py` | New: `active`, `test_account_ids`, `is_test_account`, `is_exempt` |
| `reco/config/tunables.py` | `TrackingStage`, `TRACKING_STAGES`, `Lists.tracking_stages`, key validator for `status_spellings` / `tracking_stages` |
| `settings/engine.toml` | `config_version` 3; `[lists.tracking_stages]` |
| `reco/platform/records.py` | `status_is` via spellings, `spellings_of`; `ServeLogRecord`, `parse_serve_log`; `TrackingEntry.stage/actor`, `tracking_stage`, `tracking_actor`; `OrderRecord.delivered_at/return_requested_at/returned_at/cancelled_at`; `parse_order` rewritten; `serve_log` kind |
| `reco/platform/fetch.py` | `_servable` from spellings; `categories_in_use`, `unmapped_categories`; orders parsed with the tracking stages |
| `reco/jobs/category_check.py` | New: `check_categories` |
| `reco/jobs/__main__.py` | Job `category_check` |
| `reco/jobs/scheduler.py` | `NIGHTLY` gains `category_check` |
| `reco/jobs/refresh.py` | Test accounts left out; `test_accounts_skipped` |
| `reco/api/recommendations.py` | Internal mode uses `accounts.is_test_account` |
| `reco/store/writers.py` | `record_measurement` |
| `reco/sync/copies.py` | Fourth source `rec_serve_log` |
| `tests/platform_dataset.py` | New: the constructed data (56 documents, 41 cases) |
| `tests/test_platform_dataset.py` | New: 14 tests |
| `tests/test_sync.py` | Four sources |
| `scripts/seed_test_platform.py` | New: the seeder |
| `scripts/run_checklist.sh` | Section 8; 4.1 and 4.10 for four sources |
| `Tracing/REALIGNMENT_v1.3.md` | Question 16; ENG-29 in "Built after the realignment" |

Since then, on 1 Oct 2026:

| Commit | File | Change |
|---|---|---|
| `6c3ef46` | `reco/sync/copies.py`, `reco/sync/run.py` | `SyncSource.append_only`; `rec_serve_log` read by `_id` from the backfill position; `updated_at` no longer compared |
| `6c3ef46` | `reco/ranking/serving.py` | `item_type` `product` for a post card showing a product (item 6) |
| `6c3ef46` | `Tracing/REALIGNMENT_v1.3.md` | Questions reviewed: 15 answered, 2 open |
| `2b585af` | `reco/platform/records.py` | `parse_serve_log` reads `at` first (F80) |
| `2b585af` | `reco/sync/copies.py` | `at` in the serve log's time fields; a WARNING for tracking entries with no stage; `status_history` compares with `status_is` |
| `2b585af` | `reco/sync/run.py` | Overlap re-read before the `_id` position |
| `2b585af` | `tests/test_sync.py` | Two new tests |
| `964f4ec` | `tests/test_platform_dataset.py` | Serve-log copies counted in `ml_events` |

## 9. Demo

The live demo script, in plain language, is `obsidian/Demos/Demo - ENG-29.md`.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks (section 8) with those of every other finished item, prints PASS/FAIL per line and drops `reco_demo` at the end.

## Pack v1.4 update (15 Oct 2026)

ENG-29's text is unchanged in v1.4; ENG-30 voids point 2's "exact stored value of a return request (Return Requested)", point 4's "a return request" and "who acted", point 5, and ENG-29's order check. The rework list for the built items, and its state:

| Item | Rework | State |
|---|---|---|
| ENG-03 | Category map; history mapped as ENG-30 point 5; no delivered-list record; update the order test | Done (15 Oct); map entries still to fill |
| ENG-04 | Reconciliation on tracking_info; rec_serve_log in the sync | Done (1 Oct) |
| ENG-06 | Items in the app's shape | Done (1 Oct) |
| ENG-08 | Spelling map; E-12 tests | Done (15 Oct): `activated → activate`; E-12 tests added |
| ENG-10 | Category map; test accounts left out; reversal on Cancelled, Rejected or Returned | Done (15 Oct): reversal from order_status only |
| ENG-11 | Re-run; add "unmapped category reported" and "test account left out" | Done (15 Oct): 13 of 13 |
| ENG-01, 02, 05, 07, 09 | Settings entries: category map, spelling map, test accounts, exemptions | Spelling map done; **category map (42 names), test accounts and exemptions wait on decisions / account ids** |

Point 4 (order history) is now ENG-30 point 5's history-text map (`[lists.tracking_stages]`, config_version 4).

**Where the 23 come from (checked 15 Oct 2026).** The v1.4 pack refers to "the 23" (ENG-03, ENG-29 item 1, the Settings sheet's Lists row, Capture Register X-20, DB-07 "the 23 platform categories") but never lists their names. The engine's list, `reco/platform/categories.json`, comes from the app's post-category picker (`reference/post_picker_categories.txt`, saved during the M1 demo); the older Sprint 1 Activity Pack (DS-003, superseded) also lists them. Asked in writing to confirm they are still the app's current 23.
