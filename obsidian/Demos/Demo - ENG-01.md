---
tags: [demo]
task: ENG-01
duration: about 7 minutes
---
# Demo: ENG-01, the engine's home and databases

## What this demo proves
The Build List's check for ENG-01: *"The engine runs in all three environments. The production engine reaches the platform database read-only."*

On my laptop (dev) we can show everything **except** test, production, and the private network. See *What you can't show yet* below. → [[ENG-01 - Engine home and databases]]

> [!important] Steps 1, 2 and 4 create drawers and indexes, so they run against a **throwaway database** (`reco_demo`). The real engine database `SoCo` is never touched. Steps 3, 5 and 6 only read.

## Setup
One terminal, in the repo folder. Nothing needs to be running.

## Steps

### 1. The engine knows where it is, and builds its own 16 drawers
- **Say:** "The engine runs in three setups. Right now it's in dev, on my laptop, with its own database, separate from SOCO's. Watch it build all 16 drawers from nothing."
- **Run:**
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/setup_engine_db.py
  ```
- **They should see:**
  ```
  environment      dev
  engine database  reco_demo on soco.4b7z1ko.mongodb.net
  platform (read)  soco on nex-dev.cob9whd.mongodb.net
  created          ml_events, ml_orders, ml_sync_state, ml_item_state, ml_deletions, ml_user_interest_scores, … ml_config_changes, ml_measurements
  engine check     16 of 16 collections present
  platform ping    ok
  ```
  Point out the **two different clusters**: the engine's own, and SOCO's. No password appears anywhere. → [[Environments]], [[Engine Database]]

### 2. Running it again changes nothing, and the copies expire after a year
- **Say:** "Setup is safe to repeat: the second time it finds everything already there. And every copy of SOCO's activity is kept for exactly a year from when it really happened."
- **Run** the same command again:
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/setup_engine_db.py
  ```
- **They should see:** `created          nothing (all present)` and `16 of 16 collections present`.
- **Then run** (lists the indexes on the two copy drawers; reads only):
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -c "
  import asyncio
  from pymongo import AsyncMongoClient
  from reco.config import get_settings
  async def main():
      s = get_settings(); db = AsyncMongoClient(s.ml_mongo_uri)[s.ml_mongo_db]
      for c in ('ml_events', 'ml_orders'):
          async for i in await db[c].list_indexes():
              print(c, i['name'], dict(i['key']), i.get('expireAfterSeconds', ''))
  asyncio.run(main())"
  ```
- **They should see:**
  ```
  ml_events _id_ {'_id': 1}
  ml_events user_time {'user_id': 1, 'created_at': -1}
  ml_events request_id {'request_id': 1}
  ml_events code_time {'event_code': 1, 'created_at': -1}
  ml_events retention {'created_at': 1} 31536000
  ml_orders _id_ {'_id': 1}
  ml_orders buyer_time {'buyer_id': 1, 'created_at': -1}
  ml_orders checkout_id {'checkout_id': 1}
  ml_orders retention {'created_at': 1} 31536000
  ```
  Point out:
  - `_id_`: each copy is filed under SOCO's own label for that row, so it can never be saved twice;
  - `retention`: 31,536,000 seconds is 365 days, counted from `created_at`, the moment the event really happened.

  → [[Indexes]], [[Collections]]

### 3. It can only *read* SOCO's data
- **Say:** "The engine must never change SOCO's data. Rather than try a write, which would be risky, I ask the database what the engine's login is allowed to do."
- **Run:**
  ```bash
  .venv/bin/python scripts/check_platform_access.py
  ```
- **They should see:**
  ```
  platform database  soco on nex-dev.cob9whd.mongodb.net
  logged in          yes
  roles              SocoReadonly@admin
  write actions      NONE (read-only)
  reads              users ok, posts ok, postevents ok, orders ok, follows ok, products ok
  ```
  → [[Platform Database]]

### 4. (Optional) An older database is upgraded in place
- **Say:** "My laptop's database was built to the 22 September design, with a lock on `event_id` and an index on the wrong time field. Setup replaces them by itself."
- **Run** (puts the two old indexes back on the throwaway database, then runs setup again):
  ```bash
  ML_MONGO_DB=reco_demo .venv/bin/python -c "
  import asyncio
  from pymongo import AsyncMongoClient
  from reco.config import get_settings
  async def main():
      s = get_settings(); ev = AsyncMongoClient(s.ml_mongo_uri)[s.ml_mongo_db]['ml_events']
      await ev.drop_index('user_time')
      await ev.create_index([('event_id', 1)], unique=True, name='uniq_event_id')
      await ev.create_index([('user_id', 1), ('server_ts', -1)], name='user_time')
      print([i['name'] + ' ' + str(dict(i['key'])) async for i in await ev.list_indexes()])
  asyncio.run(main())"
  ML_MONGO_DB=reco_demo .venv/bin/python scripts/setup_engine_db.py
  ```
- **They should see:** first the old ones, `uniq_event_id {'event_id': 1}` and `user_time {'user_id': 1, 'server_ts': -1}`; then `16 of 16 collections present`. Re-run the index listing from step 2: `uniq_event_id` is gone and `user_time` is on `created_at` again.

### 5. The safety lock between the two databases
- **Say:** "If someone ever points the engine's database at SOCO's, the engine refuses to start."
- **Run** (made-up addresses, with no passwords at all):
  ```bash
  .venv/bin/python -c "
  from reco.config import Settings
  Settings(app_mongo_uri='mongodb+srv://reader@cluster0.example.net/', app_mongo_db='soco',
           ml_mongo_uri='mongodb+srv://writer@cluster0.example.net/', ml_mongo_db='soco')"
  ```
- **They should see** an error ending: *"the engine database ('soco') is the platform database. The engine has its own database in every environment (AS-09, SD-06): set ML_MONGO_DB to a different name."*

### 6. Passwords never live in files
- **Say:** "Passwords only live in the server's own settings. The repository has none, and production refuses a settings file."
- **Run:**
  ```bash
  git check-ignore -v .env
  git grep -nE "mongodb(\+srv)?://[^@ \"']+:[^@ \"']+@" -- . ':!tests' || echo "none found"
  .venv/bin/python -c "
  from reco.config import _require_production_env_from_server as check
  check('production', server_engine_env='')"
  ```
- **They should see:**
  - `.gitignore:1:.env	.env`: `.env` is ignored by git;
  - `none found`: no connection string with a password anywhere in the code or docs;
  - an error: *"ENGINE_ENV=production was read from a .env file. In production, passwords and tokens live only in server environment settings, never in a file (SD-08, ENG-01) …"*.

  → [[Secrets and passwords]]

## What you can't show yet
| Part of the check | Why not | Waiting on |
|---|---|---|
| Engine running in **test** and **production** | Those servers and their database clusters don't exist yet | Aravinth's hosting → [[People]] |
| **Production** reading SOCO's data read-only | Needs production's own login, on the production server | DB-02 and the production server |
| **Private network**, and the address handed to Aravinth (DB-12) | The laptop isn't in SOCO_BE's network | The production server |
| A copy actually **expiring** after 365 days | Nothing in the drawers is a year old; the demo shows the rule, not a deletion | Time (and ENG-04 filling the drawers) |

Say it plainly: "Everything that can run on my laptop is done and shown. The rest needs the servers."

## Clean up
Drop the throwaway database:
```bash
ML_MONGO_DB=reco_demo .venv/bin/python -c "
import asyncio
from pymongo import AsyncMongoClient
from reco.config import get_settings
asyncio.run(AsyncMongoClient(get_settings().ml_mongo_uri).drop_database('reco_demo'))"
```
Nothing else to clean: steps 3, 5 and 6 only read.

## How this connects
- Proves → [[ENG-01 - Engine home and databases]]
- Laid out as described in → [[How to demo a task]]
- Next demo → [[Demo - ENG-02]]
