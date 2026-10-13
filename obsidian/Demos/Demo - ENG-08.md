---
tags: [demo]
task: ENG-08
duration: about 6 minutes
---
# Demo: ENG-08, the twelve rules no model can override

## What this demo proves
The Build List's check for ENG-08: *"A test case for each rule: one item excluded and one kept."*

It also shows the parts around the rules: what the engine reads about the viewer, the log line for every item left out, the last-moment check that swaps in a replacement, and the rules running on SOCO's real dev data. → [[ENG-08 - Filters]]

> [!note] Rehearsed on 1 Oct 2026 on my laptop against SOCO's dev data (8 posts, 2,011 products). Steps 1, 2 and 4 only read. Step 3 writes, so it runs in the throwaway database `reco_demo` (and `reco_demo_platform` for its made-up SOCO data); the tests drop both when they finish. The real engine database `SoCo` is never touched.

## Setup (before the audience watches)
One terminal, in the repo folder. Nothing needs to be running: every step starts and stops on its own.

## Steps

### 1. One test per rule: one item out, one kept (the Build List's check)
- **Say:** "Here are the twelve rules. For each one, a test builds two items from SOCO-shaped records: one the rule must leave out, and one it must keep."
- **Run:**
  ```bash
  .venv/bin/python -m pytest -p no:cacheprovider tests/test_eligibility.py -m 'not mongo' -v 2>&1 | grep -E "::|passed|failed"
  ```
- **They should see:**
  ```
  tests/test_eligibility.py::test_every_rule_is_named PASSED               [  7%]
  tests/test_eligibility.py::test_e01_blocked_either_way PASSED            [ 15%]
  tests/test_eligibility.py::test_e02_muted_author PASSED                  [ 23%]
  tests/test_eligibility.py::test_e03_not_interested_hide_or_report PASSED [ 30%]
  tests/test_eligibility.py::test_e04_hidden_or_not_public PASSED          [ 38%]
  tests/test_eligibility.py::test_e05_private_author_not_followed PASSED   [ 46%]
  tests/test_eligibility.py::test_e06_product_post_not_activated PASSED    [ 53%]
  tests/test_eligibility.py::test_e07_product_not_sellable PASSED          [ 61%]
  tests/test_eligibility.py::test_e08_author_or_seller_not_active PASSED   [ 69%]
  tests/test_eligibility.py::test_e09_suspended_or_removed_once_db08_exists PASSED [ 76%]
  tests/test_eligibility.py::test_e10_own_posts_and_products PASSED        [ 84%]
  tests/test_eligibility.py::test_e11_adult_only_content PASSED            [ 92%]
  tests/test_eligibility.py::test_e12_deranked_or_removed PASSED           [100%]
  ======================= 13 passed, 4 deselected in 0.48s =======================
  ```
  One line per rule, E-01 to E-12, plus one that checks all twelve are named in order. They need no database: the rules are pure checks on records, so they run in half a second.

### 2. Look inside one: E-04
- **Say:** "Here's what 'one out, one kept' looks like for E-04, hidden or not public."
- **Run:**
  ```bash
  sed -n '/def test_e04/,/^$/p' tests/test_eligibility.py
  ```
- **They should see:**
  ```
  def test_e04_hidden_or_not_public() -> None:
      assert post_rule(P("hidden_post"), AUTHOR, VIEWER) == "E-04"
      assert post_rule(P("private_post"), AUTHOR, VIEWER) == "E-04"
      assert post_rule(P("post"), AUTHOR, VIEWER) is None
  ```
- **Point out:** a hidden post and a non-public post both come back as **E-04** (left out, with the reason); an ordinary post comes back as **None** (kept). Every rule's test follows this pattern, some with extra cases (E-08 also checks an account with no status, and one not found).

> [!example] Like a bouncer's list
> Each test hands the bouncer one guest who should be turned away and one who should walk in, and checks the reason number he gives.

### 3. The parts around the rules, on a database
- **Say:** "Now the parts that need a database: reading who I've blocked, follow and muted; writing down every item left out; and the last-moment check before a list goes out."
- **Run:**
  ```bash
  TEST_MONGO_DB=reco_demo TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -p no:cacheprovider tests/test_eligibility.py -m mongo -v 2>&1 | grep -E "::|passed|failed"
  ```
- **They should see** (takes about 15 seconds):
  ```
  tests/test_eligibility.py::test_the_viewer_context_comes_from_the_platform_and_the_engine_copy PASSED [ 25%]
  tests/test_eligibility.py::test_each_exclusion_is_logged_with_request_id_item_and_rule PASSED [ 50%]
  tests/test_eligibility.py::test_an_item_failing_the_final_recheck_is_replaced PASSED [ 75%]
  tests/test_eligibility.py::test_e07_a_post_card_showing_an_unsellable_product_is_left_out PASSED [100%]
  ====================== 4 passed, 13 deselected in 15.04s =======================
  ```
- **Point out:**
  - **Viewer context:** a block is read from SOCO's `followers`; a mute made on a post mutes its author; a year-old mute still applies; a 91-day-old Hide doesn't; an undone mute doesn't.
  - **Logged:** every post is either kept or written in the log with its rule. None disappears silently.
  - **Recheck:** a post hidden **after** the list was built is dropped at the last moment, and the next eligible post takes its place.
  - **E-07 on the feed:** a post showing a product is left out once that product's stock runs out.

### 4. The rules on SOCO's real data
- **Say:** "Now the real thing: the first feed page and the first product page, built from SOCO's dev data the way the engine does, as a made-up viewer who follows nobody. Nothing is served or recorded; it counts what each rule left out."
- **Run:**
  ```bash
  .venv/bin/python scripts/show_exclusions.py 2>&1 | grep -v '^{"ts"'
  ```
- **They should see:**
  ```
  LEGACY_LABEL_MAP is NOT loaded (…). Legacy category names will be dropped …
  feed: 3 eligible of 8 read
  product: 0 eligible of 1000 read
  left out, by rule:
    E-05  post         5  private author the viewer does not follow
    E-07  product    143  product not sellable
    E-08  product    857  author or seller not active
  ```
  (The first line is an old start-up warning about category names; ignore it.)
- **Point out:**
  - **Feed:** dev holds only 8 posts; 5 are by private accounts this viewer doesn't follow, so 3 can be shown.
  - **Product:** all 1,000 newest products are out. 143 are marked out of stock (E-07). The other 857 are sold by SOCO's import sellers, who have **no status written** at all, so the engine won't treat them as active (E-08). That's question 17 to Aravinth; until he answers, the product rail stays empty on dev.
  - It stops at 1,000 on purpose: a list never reads more than that.

### 5. The log line for each item left out
- **Say:** "Each of those exclusions is a line in the log, with the list's ID, the item and the rule number. Here's a feed list built with the ID `req-demo-eng08`."
- **Run:**
  ```bash
  .venv/bin/python -c "
  import asyncio; from reco.config import get_settings; from reco.monitoring.logs import configure_logging
  from reco.platform import connection as p; from reco.store import connection as s; from reco.ranking import serving
  async def m():
      st=get_settings(); configure_logging(st); s.init_client(st); p.init_client(st)
      await serving.interim_candidates(st, 'feed', 1, 5, None, '64f1c0ffee0000000000abcd', 'req-demo-eng08')
      await p.close_client(); await s.close_client()
  asyncio.run(m())" 2>&1 | grep '"excluded"'
  ```
- **They should see** (five lines like these; post IDs abridged):
  ```
  {"ts": "2026-10-01T12:37:43.355Z", "level": "INFO", "logger": "reco.eligibility", "message": "excluded", "env": "dev", "request_id": "req-demo-eng08", "item_id": "6a5a7b81…a2d1", "item_type": "post", "rule": "E-05"}
  {"ts": "2026-10-01T12:37:43.355Z", "level": "INFO", "logger": "reco.eligibility", "message": "excluded", "env": "dev", "request_id": "req-demo-eng08", "item_id": "6a5a7b4a…a2ad", "item_type": "post", "rule": "E-05"}
  …
  ```
  Only reads: nothing is served or recorded. "Why didn't this post show up for her?" is one search for the list's ID. → [[Logs]]

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| A real block on SOCO (E-01) | `followers` is empty on dev, and its field names are assumed | Aravinth, question 16 |
| Products on the product rail | SOCO's import sellers have no status, so E-08 leaves them all out | Aravinth, question 17 |
| A suspended author hidden (E-09) | The field doesn't exist yet | DB-08 |
| An adult-only post hidden from a minor on real data (E-11) | Every SOCO post is "All" today | Real content (AS-15) |
| The 15-minute snapshot in use | Not built | ENG-27 |
| Filtering before scoring in the overnight jobs | Those jobs aren't built | ENG-10, ENG-13, ENG-17 |
| Blocking end to end in the app, both ways | Aravinth's acceptance test | APP-21 test 3 |
| The check on the **test** server | It doesn't exist yet | The test server ([[ENG-01 - Engine home and databases]]) |

## Clean up
The tests in step 3 drop `reco_demo` and `reco_demo_platform` themselves when they finish. If a run was interrupted, drop them by hand:
```bash
.venv/bin/python -c "
import asyncio; from pymongo import AsyncMongoClient; from reco.config import get_settings
async def m():
    c=AsyncMongoClient(get_settings().ml_mongo_uri)
    for d in ('reco_demo','reco_demo_platform'): await c.drop_database(d)
    await c.close(); print('reco_demo dropped')
asyncio.run(m())"
```

## How this connects
- Proves → [[ENG-08 - Filters]]
- Laid out as described in → [[How to demo a task]]
- Previous demo → [[Demo - ENG-29]]
- Next demo → [[Demo - ENG-09]]
