---
tags: [demo]
task: ENG-01
duration: about 5 minutes
---
# Demo: ENG-01, the engine's home and databases

## What this demo proves
The Build List's check for ENG-01: *"The engine runs in all three environments. The production engine reaches the platform database read-only."*

On my laptop (dev) we can show everything **except** test, production, and the private network. See *What you can't show yet* below. → [[ENG-01 - Engine home and databases]]

## Setup
One terminal, in the repo folder. Nothing needs to be running.

## Steps

### 1. The engine knows where it is, and has its own database
- **Say:** "The engine runs in three setups. Right now it's in dev, on my laptop, with its own database, separate from SOCO's."
- **Run:**
  ```bash
  .venv/bin/python scripts/setup_engine_db.py
  ```
- **They should see:**
  ```
  environment      dev
  engine database  SoCo on soco.4b7z1ko.mongodb.net
  platform (read)  soco on nex-dev.cob9whd.mongodb.net
  created          nothing (all present)
  engine check     12 of 12 collections present
  platform ping    ok
  ```
  Point out the **two different clusters**: the engine's own, and SOCO's. No password appears anywhere. → [[Environments]], [[Engine Database]]

### 2. All 12 drawers are there
- **Say:** "Every later task saves into one of these 12 drawers. They exist now, mostly empty, which is right at this stage."
- **Show:** line 5 above ("12 of 12"). For a visual, open **Atlas → Browse Collections → SoCo** and point out the `ml_…` collections. → [[Collections]]
- Optionally open `ml_events` → **Indexes**. Point out `uniq_event_id`, the lock that stops the same event being saved twice. → [[Indexes]]

### 3. It can only *read* SOCO's data
- **Say:** "The engine must never change SOCO's data. Rather than try a write, which would be risky, I ask the database what the engine's login is allowed to do."
- **Run:**
  ```bash
  .venv/bin/python scripts/check_platform_access.py
  ```
- **They should see:**
  ```
  roles              SocoReadonly@admin
  write actions      NONE (read-only)
  reads              users ok, posts ok, postevents ok, orders ok, follows ok, products ok
  ```
  → [[Platform Database]]

### 4. The safety lock between the two databases
- **Say:** "If someone ever points the engine's database at SOCO's, the engine refuses to start."
- **Run** (made-up addresses, with no passwords at all):
  ```bash
  .venv/bin/python -c "
  from reco.config import Settings
  Settings(app_mongo_uri='mongodb+srv://reader@cluster0.example.net/', app_mongo_db='soco',
           ml_mongo_uri='mongodb+srv://writer@cluster0.example.net/', ml_mongo_db='soco')"
  ```
- **They should see** an error ending: *"the engine database ('soco') is the platform database … (AS-09, SD-06): set ML_MONGO_DB to a different name."*

### 5. Passwords never live in files
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
  - `.env` is ignored by git;
  - `none found`: no connection string with a password anywhere in the code or docs;
  - an error: *"ENGINE_ENV=production was read from a .env file … (SD-08, ENG-01)"*.

  → [[Secrets and passwords]]

## What you can't show yet
| Part of the check | Why not | Waiting on |
|---|---|---|
| Engine running in **test** and **production** | Those servers and their database clusters don't exist yet | Aravinth's hosting → [[People]] |
| **Production** reading SOCO's data read-only | Needs production's own login, on the production server | DB-02 and the production server |
| **Private network**, and the address handed to Aravinth (DB-12) | The laptop isn't in SOCO_BE's network | The production server |

Say it plainly: "Everything that can run on my laptop is done and shown. The rest needs the servers."

## Clean up
Nothing to clean: this demo only reads, and the setup script only creates what's missing.

## How this connects
- Proves → [[ENG-01 - Engine home and databases]]
- Laid out as described in → [[How to demo a task]]
- Next demo → [[Demo - ENG-02]]
