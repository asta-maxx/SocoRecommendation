---
tags: [demo]
task: ENG-29
duration: about 10 minutes
---
# Demo: ENG-29, the engine adapted to SOCO as it's really built

## What this demo proves
The Build List's check for ENG-29: *"Unit tests: an unmapped category is reported; a test account is left out of scoring; an order with tracking_info and a return request reads correctly; a product post on a feed list keeps post_id and product_id apart; rec_serve_log rows are copied. The test environment holds the constructed data."*

Each part of that sentence is one step below. Where there's real SOCO data to show it on, the step shows that too. → [[ENG-29 - Adapting to the platform as built]]

> [!important] Anything that writes goes to the **throwaway database** `reco_demo`, or (for the made-up SOCO data) to `soco_engine_test`. SOCO's own database is only ever read, with the read-only login. The real engine database `SoCo` is never touched.

> [!note] Rehearsed on 1 Oct 2026. Run IDs are random. Categories with the same count (Food, Sports, Fashion…) can come out in a different order each time.

## Setup (before the audience watches)
One terminal, in the repo folder. Make sure `reco_demo` starts empty:
```bash
.venv/bin/python -c "
import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
async def m():
    c=AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database('reco_demo'); await c.close(); print('reco_demo dropped')
asyncio.run(m())"
```
Do steps 1 and 2 **before** the automatic checks in step 3: the checks use `reco_demo` too and empty it as they finish.

## Steps

### 1. The daily category check, on SOCO's real data
- **Say:** "The engine scores 23 categories. SOCO uses its own names. Every night the engine lists every SOCO category it can't match to the 23, and tells me."
- **Run:**
  ```bash
  .venv/bin/python -c "from reco.jobs.scheduler import NIGHTLY; print('nightly jobs:', NIGHTLY)"
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs category_check 2>&1 | grep -o '"message": "[^"]*"[^}]*' | grep -v "client opened\|ensured\|vocabulary"
  ```
- **They should see** (trimmed):
  ```
  nightly jobs: ('interest', 'category_check', 'reconcile_sync')
  "message": "job started", "job": "category_check"
  "message": "platform categories outside the 23 and not in the category map", "alert": true, "reason": "unmapped_categories", "owner": "Allen", "count": 42, "labels": ["Menswear catimp1790216912437", "Menswear catimp1790217539835", "Food", "Sports", "Fashion", "Nature", "Business", "Automobiles", "Travel", "Cooking", …]
  "message": "category check", "job": "category_check", "unmapped": 42, …
  "message": "job finished", "job": "category_check", "outcome": "succeeded", "duration_ms": 575.8
  ```
- **Point out:**
  - It's in the 2 AM list now, between the interest score and the sync's audit.
  - **42 labels** don't match. That's the first half of the check: *an unmapped category is reported*, as an alert addressed to me.
  - "Fashion" isn't "Fashion & Apparel", so it doesn't match. The engine **never guesses**: things in those categories are left out of category scoring until I map them in the settings file. → [[Settings file]]

### 2. What it wrote down
- **Say:** "The result is kept, so I can see it grow or shrink day by day, and the run is in the job diary."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -c "
  import asyncio; from reco.config import get_settings; from reco.store import connection as c
  async def m():
      s=get_settings(); c.init_client(s)
      row=await c.ml_db(s)['ml_measurements'].find_one({'measure':'unmapped_categories'})
      print(row['measure'], row['day'], '| labels', row['count'], '| uses', row['items'])
      for r in row['unmapped'][:6]: print(f\"  {r['label'][:30]:30} {r['items']:5}  {r['used_by']}\")
      await c.close_client()
  asyncio.run(m())" 2>/dev/null
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_job_runs.py 2>/dev/null
  ```
- **They should see:**
  ```
  unmapped_categories 2026-10-01 | labels 42 | uses 2064
    Menswear catimp1790216912437    1005  {'products': 1005}
    Menswear catimp1790217539835    1000  {'products': 1000}
    Food                               4  {'user interests': 4}
    Sports                             4  {'user interests': 4}
    Fashion                            4  {'user interests': 3, 'products': 1}
    Nature                             3  {'user interests': 3}
  ml_job_runs in reco_demo (dev), newest first:
    cff9327f  category_check None            succeeded rows     0    0.55s
  ```
- **Point out:** almost all SOCO's products (2,005) sit under two top-level categories called "Menswear catimp…". Mapping those two labels alone would bring them into scoring. Which of the 23 they map to is my decision, not the engine's. → [[Nightly batches]]

### 3. The automatic checks, one per part of the sentence
- **Say:** "Now the five unit tests the Build List names, run one by one on made-up SOCO data."
- **Run:**
  ```bash
  T="TEST_MONGO_DB=reco_demo TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_platform_dataset.py"
  eval "$T -k unmapped" 2>/dev/null | tail -1                                         # an unmapped category is reported
  eval "$T -k 'test_account or account_lists or list_change'" 2>/dev/null | tail -1   # a test account is left out of scoring
  eval "$T -k 'tracking or first_delivery or cancellation'" 2>/dev/null | tail -1     # an order with tracking_info and a return request
  eval "$T -k apart" 2>/dev/null | tail -1                                            # post_id and product_id kept apart
  eval "$T -k serve_log" 2>/dev/null | tail -1                                        # rec_serve_log rows are copied
  ```
- **They should see:**
  ```
  2 passed, 12 deselected in 3.95s
  3 passed, 11 deselected in 3.79s
  4 passed, 10 deselected in 0.03s
  1 passed, 13 deselected in 0.03s
  2 passed, 12 deselected in 4.75s
  ```
- **Point out:**
  - **Unmapped:** "Cricket", "Fashion" and "(no category id)" are reported; once the map covers Fashion and Cricket they disappear. A map pointing at something that isn't one of the 23 is refused.
  - **Test account:** with one test account in the settings, the interest score skips exactly one user. Entries stop counting after their expiry day, and a change to the list is logged like any settings change.
  - **Post and product apart:** a click on a product post on the feed gives the post id and the product id separately, never mixed up.

### 4. An order's history, read from its tracking steps
- **Say:** "SOCO keeps each order's steps as short sentences, like 'Shipped by seller'. The engine reads which step each one is, and who did it."
- **Run** (a made-up order first, then SOCO's real orders, counts only):
  ```bash
  .venv/bin/python -c "
  from tests.platform_dataset import build_dataset; from reco.platform import records
  data, cases = build_dataset()
  doc = next(o for o in data['orders'] if o['_id'] == cases['order_return_requested'])
  o = records.parse_order(doc)
  print('order_status:', o.status)
  for e in o.tracking: print(f'  {e.status:38} -> {e.stage:17} actor {e.actor}')
  print('delivered_at set:', o.delivered_at is not None, '| return_requested_at set:', o.return_requested_at is not None, '| is_returned:', o.is_returned)
  " 2>/dev/null
  .venv/bin/python -c "
  import asyncio, collections; from reco.config import get_settings; from reco.platform import connection as p, fetch
  async def m():
      s=get_settings(); p.init_client(s)
      orders = await fetch.read_records(s, 'order')
      stages = collections.Counter(e.stage or 'NO STAGE' for o in orders for e in o.tracking)
      print(len(orders), 'orders,', sum(stages.values()), 'tracking entries')
      print('stages:', dict(stages))
      print('delivered:', sum(o.delivered_at is not None for o in orders), '| returned:', sum(o.is_returned for o in orders),
            '| cancelled by:', [o.cancelled_by for o in orders if o.cancelled_at])
      await p.close_client()
  asyncio.run(m())" 2>/dev/null
  ```
- **They should see:**
  ```
  order_status: Return Requested
    Order created by Buyer One             -> created           actor buyer
    Delivered (Test Seller Studio)         -> delivered         actor None
    Return Requested by buyer              -> return_requested  actor buyer
  delivered_at set: True | return_requested_at set: True | is_returned: True
  8 orders, 14 tracking entries
  stages: {'created': 8, 'accepted': 1, 'confirmed': 1, 'shipped': 1, 'paid': 1, 'delivered': 1, 'cancelled': 1}
  delivered: 1 | returned: 0 | cancelled by: ['seller']
  ```
- **Point out:**
  - The made-up order is the Build List's case: delivered, then a return request. The engine keeps **when** it was first delivered and **when** the return was asked for, and counts it as returned.
  - On SOCO's real orders, **every one of the 14 steps** was recognised. The list of sentence beginnings ("order created", "shipped", "delivered"…) lives in the settings file, so a new wording is a settings change, not a code change.

### 5. The serve log joins the sync
- **Say:** "SOCO will keep a small log of every list request it makes, `rec_serve_log`. The sync now copies it, alongside the other three."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs sync 2>&1 | grep -o '"message": "sync pass finished"[^}]*}'
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py 2>/dev/null | grep -A4 "sync state" | cut -c1-60
  ```
- **They should see:**
  ```
  "message": "sync pass finished", "env": "dev", "job": "sync", "copied": {"postevents": 146, "orders": 8, "recommendationrequests": 12, "rec_serve_log": 0}
  sync state:
    postevents                 backfill done (146 copied) | c
    orders                     backfill done (8 copied) | che
    recommendationrequests     backfill done (12 copied) | ch
    rec_serve_log              backfill done (0 copied) | che
  ```
- **Point out:** four sources now. The serve log copies **0** rows because SOCO hasn't created it yet (Aravinth's APP-15). The test in step 3 copied three made-up serve-log rows, so it's ready for when it arrives. → [[Engine sync]]

### 6. The engine's test environment holds the made-up data
- **Say:** "Last part: a separate test database filled with made-up SOCO data, one record for every awkward case the engine has to handle."
- **Run:**
  ```bash
  .venv/bin/python scripts/seed_test_platform.py soco_engine_test 2>/dev/null
  .venv/bin/python scripts/seed_test_platform.py SoCo 2>/dev/null
  ```
- **They should see:**
  ```
    users                     10 documents
    businessregisters          2 documents
    follows                    3 documents
    followers                  1 documents
    categories                 3 documents
    products                   4 documents
    productvariants            2 documents
    posts                     11 documents
    postevents                10 documents
    orders                     5 documents
    carts                      1 documents
    recommendationrequests     1 documents
    rec_serve_log              3 documents
  56 documents in soco_engine_test; 41 named cases; all parse
  refusing 'SoCo': the name must contain 'test' and be neither the platform nor the engine database
  ```
- **Point out:** all 13 SOCO collections the engine reads, 41 named cases (a hidden post, a blocked viewer, an out-of-stock product, an order cancelled by the seller…), and every record reads cleanly. The second command shows it **refuses** to write into a real database. Running it again leaves exactly the same data.

### 7. (Optional) All of this task's checks at once
- **Run:**
  ```bash
  TEST_MONGO_DB=reco_demo TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_platform_dataset.py 2>/dev/null | tail -1
  ```
- **They should see:** `14 passed`.

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| A category map that covers everything (0 unmapped) | The map is empty; choosing where each SOCO category goes is a decision | Me (Allen) |
| Real serve-log rows being copied | SOCO hasn't created `rec_serve_log` yet | Aravinth, APP-15 |
| A real test account skipped | No test accounts are named yet; the list is empty | Naming them (DB-11) |
| The made-up data on the **test** server | It doesn't exist yet; the data sits on the dev engine cluster for now | [[ENG-01 - Engine home and databases]] |

## Clean up
Drop the throwaway database (leave `soco_engine_test`: it *is* the engine's test environment):
```bash
.venv/bin/python -c "
import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
async def m():
    c=AsyncMongoClient(get_settings().ml_mongo_uri); await c.drop_database('reco_demo'); await c.close(); print('reco_demo dropped')
asyncio.run(m())"
```

## How this connects
- Proves → [[ENG-29 - Adapting to the platform as built]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-07]]
