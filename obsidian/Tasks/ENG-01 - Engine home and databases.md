---
tags: [task, step-1]
task: ENG-01
status: Waiting
owner: Allen
---
# ENG-01: Engine home and databases

> [!note] Status: **Waiting** (24 Sep 2026)
> Everything I can do on my laptop is **done and checked**. The task counts as finished only when the engine also runs on the **test** and **production** servers. Those don't exist yet; Aravinth sets them up. → [[People]]

**In one line:** give my engine a proper home. That means three separate setups, its own database with all its drawers, and safe handling of passwords.

## Why this task comes first
Every other task needs somewhere to run and somewhere to save things. This task builds that. → [[Build Steps]]

## What came before
- The demo had **one** setup, and planned to keep its data **inside SOCO's database**. → [[Before Wave 1A - the M1 demo]]
- The pack changed that: my engine gets its **own** database, and there are **three** setups. → [[The Pack]]

## Subtasks, one by one
The Build List splits ENG-01 into four numbered parts (1–4). We added three small extras (A–C) that make them safe and easy to check.

### 1. Three setups, each with its own database ✅ laptop / ⏳ servers
- **What it asks:** the engine must run in three separate places (dev, test, production), and each place gets its own private database.
- **What we did:** added one setting, `ENGINE_ENV`, that tells the engine which place it's in. If no database name is given, each place automatically gets its own name (`soco_engine_dev`, `soco_engine_test`, `soco_engine_production`). Two places can't share a database by accident.
- **Why it matters:** testing can never overwrite real data.
- **Status:** dev (my laptop) works. Test and production wait for the servers.
- → [[Environments]]

### 2. The 12 drawers in the engine's database ✅
- **What it asks:** the engine's database must hold all 12 `ml_` collections.
- **What we did:** when the engine starts, it checks which of the 12 [[Collections]] exist and creates only the missing ones. It never touches the ones already there, so running it twice is harmless. On `ml_events` it also added three [[Indexes]]:
  - one so the same event can never be saved twice;
  - one to find a person's events quickly;
  - one to find everything about one list shown to a user.
- **Why it matters:** every later task saves into one of these drawers.
- **Status:** done on dev. 11 drawers were created; `ml_user_interest_scores` already existed from the demo.

### 3. Live next to SOCO_BE, and tell Aravinth the address ⏳
- **What it asks:** put the engine on a server in the same private network as [[SOCO_BE]], so only SOCO_BE and the admin panel can reach it. Then give Aravinth the engine's address.
- **What we did:** nothing yet. There's no server.
- **Why it matters:** the app's backend has to be able to call the engine, and nobody on the internet should be able to.
- **Status:** waiting for Aravinth's servers. → [[People]]

### 4. Passwords only in the server's own settings ✅
- **What it asks:** logins and keys must never sit in code or in files.
- **What we did:**
  - In production, the engine completely ignores the `.env` file.
  - If it notices that "production" was switched on from a `.env` file, it refuses to start.
  - Nothing it prints ever shows a password.
- **Why it matters:** a password was leaked once before.
- **Status:** done. → [[Secrets and passwords]]

### A. Extra: a safety lock between the two databases ✅
- **What we did:** the engine refuses to start if its own database is the same as SOCO's database. That means the same cluster and the same name, even if the capital letters differ.
- **Why it matters:** the engine can never accidentally write into SOCO's data. → [[Engine Database]], [[Platform Database]]

### B. Extra: a one-command setup helper ✅
- **What we did:** a small script (`scripts/setup_engine_db.py`) sets up any environment in one go:
  - creates the drawers;
  - checks all 12 are there;
  - checks SOCO's database answers.

  It reports each database's name, never the password.
- **Why it matters:** when the servers arrive, finishing ENG-01 is one command per server.

### C. Extra: proving the SOCO login is read-only ✅
- **What we did:** asked the database what my login is *allowed* to do, instead of trying to write something. Trying a write would have been risky: if it worked, it would have changed SOCO's real data. The answer: it can read, and it can't change anything.
- **Why it matters:** "the engine only reads SOCO's data" is now checked, not just promised. → [[Platform Database]]

## Result (24 Sep 2026)
- **dev is ready:** all 12 collections exist in `SoCo` on my Atlas build cluster. → [[MongoDB Atlas]]
- SOCO's database answers when the engine reads it.
- **The login to SOCO's database is confirmed read-only.** I checked without trying to write anything: I asked the database what the login is allowed to do. It can read, but it can't add, change or delete anything. → [[Platform Database]]
- All automatic checks pass (400 tests).

## Decided: where each setup runs (24 Sep 2026)
- **dev** runs on **my laptop**. It's ready now.
- **test** runs on **a server**. Its database cluster will be created later.
- **production** runs on **a server** next to [[SOCO_BE]]. Its database cluster will be created later.

More detail → [[Environments]]

## Re-checked (28 Sep 2026)
The whole checklist was run again on my laptop, and everything passed. The record is in `Tracing/checks/Checklist_2026-09-28.md`.

## Still to do
| What                                                             | Waiting on                          |
| ---------------------------------------------------------------- | ----------------------------------- |
| Create the test and production database clusters                | Later, when the servers are ready   |
| Test and production servers                                      | Aravinth's hosting → [[People]]     |
| Change the read-only login's password (only the password changes) | Aravinth, DB-02                     |
| Put the engine next to [[SOCO_BE]] and give Aravinth its address | Aravinth's hosting                  |

## How this connects
- **Before it:** [[Before Wave 1A - the M1 demo]]
- **Built on:** [[Environments]], [[Engine Database]], [[Collections]], [[Indexes]], [[Secrets and passwords]]
- **Next:** [[ENG-02 - Service skeleton and settings]]. It organises the engine into 12 tidy parts and adds a settings file that can change without a restart.
- **Demo:** [[Demo - ENG-01]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-01.md` in the repo.
