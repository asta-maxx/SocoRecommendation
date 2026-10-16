---
tags: [task, step-1]
task: ENG-01
status: Waiting
owner: Allen
---
# ENG-01: Engine home and databases

> [!note] Status: **Waiting** (24 Sep 2026; brought up to date with pack v1.3 on 1 Oct 2026)
> Everything I can do on my laptop is **done and checked**, now with **16** drawers instead of 12. The task counts as finished only when the engine also runs on the **test** and **production** servers.
>
> **14 Oct 2026:** the **test server is ready**, so the engine goes there now. **Production comes later.** Until it's up, this task stays Waiting, because its check says the engine runs in all three places.

> [!tip] 16 Oct 2026 (Kala)
> Production moves to a new task in the next Build List, as a go-live condition. ENG-01's check then covers dev and test only: it becomes Passed once it runs on the test server. On test, the engine must read SOCO's data with its own read-only login, not the engine's login. → [[Answers 16 Oct]]

**In one line:** give my engine a proper home. That means three separate setups, its own database with all its drawers, and safe handling of passwords.

## Why this task comes first
Every other task needs somewhere to run and somewhere to save things. This task builds that. → [[Build Steps]]

## What came before
- The demo had **one** setup, and planned to keep its data **inside SOCO's database**. → [[Before Wave 1A - the M1 demo]]
- The pack changed that: my engine gets its **own** database, and there are **three** setups. → [[The Pack]]
- I first built this on 24 Sep to the 22 Sep pack, which listed **12** drawers. Pack v1.3 (29 Sep, received 1 Oct) changed how the engine gets SOCO's activity: instead of SOCO **sending** it events, the engine now **copies** them itself, every 5 minutes. That copying needs four more drawers, and a rule for how long copies are kept. → [[Engine sync]]

> [!example] What v1.3 changed for this task, in one table
> | | Before (22 Sep) | Now (v1.3) |
> |---|---|---|
> | Drawers | 12 | 16 |
> | How a copy is labelled | by its `event_id` | by SOCO's own label for that row (its `_id`) |
> | How long copies are kept | no auto-delete | auto-deleted **365 days after the event really happened** |

## Subtasks, one by one
The Build List splits ENG-01 into four numbered parts (1–4). We added three small extras (A–C) that make them safe and easy to check.

### 1. Three setups, each with its own database ✅ laptop / ⏳ servers
- **What it asks:** the engine must run in three separate places (dev, test, production), and each place gets its own private database.
- **What we did:** added one setting, `ENGINE_ENV`, that tells the engine which place it's in. If no database name is given, each place automatically gets its own name (`soco_engine_dev`, `soco_engine_test`, `soco_engine_production`). Two places can't share a database by accident.
- **Why it matters:** testing can never overwrite real data.
- **Status:** dev (my laptop) works. Test and production wait for the servers. Unchanged by v1.3.
- → [[Environments]]

### 2. The 16 drawers in the engine's database ✅ laptop
- **What it asks:** the engine's database must hold all 16 `ml_` collections. A collection is one drawer of a filing cabinet, holding one kind of record. → [[Collections]]
- **What we did:** when the engine starts, it checks which of the 16 drawers exist and creates only the missing ones. It never touches the ones already there, so running it twice is harmless.

  The four drawers v1.3 added, all for the copying job:

  | Drawer | What goes in it |
  |---|---|
  | `ml_orders` | Copies of SOCO's orders, with their status and delivery history |
  | `ml_sync_state` | A bookmark per SOCO collection: how far the copying has got |
  | `ml_item_state` | Whether each post, account and product can be shown right now (ENG-27) |
  | `ml_deletions` | Accounts SOCO has really deleted, and when we wiped our copies (ENG-28) |

  It also puts [[Indexes]] on the two copy drawers, `ml_events` and `ml_orders`. An index is like the index at the back of a book: it lets the database jump straight to what it needs.
  - Each copy is filed under **SOCO's own label** for that row (its `_id`), so the same row can never be saved twice, however often it's copied.
  - Quick lookups: a person's events (or a buyer's orders) newest first; everything about one list shown to a user; one kind of event over a week; one basket.
  - An **auto-delete** index called `retention`: each copy is deleted **365 days after the event really happened**. It counts from the original time, so copying a row again later never gives it a longer life.
- **Why it matters:** every later task saves into one of these drawers. SOCO deletes its own short-lived activity after 90 days; our copies keep a full year, which the models need to learn seasons and habits.
- **Status:** done on dev. 16 of 16 drawers present (1 Oct). The old `event_id` lock from 22 Sep was removed, and the old "person + time" index was rebuilt on the right time field.
- → [[Collections]], [[Indexes]]

> [!tip] Why "auto-delete" is safe here
> It only ever deletes rows **over a year old**, and only in my engine's copies. SOCO's own data is never touched: the engine can't write there at all. → [[Platform Database]]

### 3. Live next to SOCO_BE, and tell Aravinth the address ⏳
- **What it asks:** put the engine on a server in the same private network as [[SOCO_BE]], so only SOCO_BE and the admin panel can reach it. Then give Aravinth the engine's address.
- **What we did:** nothing yet. There's no server.
- **Why it matters:** the app's backend has to be able to call the engine, and nobody on the internet should be able to.
- **Status:** waiting for Aravinth's servers. → [[People]]

### 4. Passwords only in the server's own settings ✅
- **What it asks:** logins and keys must never sit in code or in files.
- **What we did:**
  - In production, the engine completely ignores the `.env` file (the private settings file I use on my laptop).
  - If it notices that "production" was switched on from a `.env` file, it refuses to start.
  - Nothing it prints ever shows a password.
- **Why it matters:** a password was leaked once before.
- **Status:** done. → [[Secrets and passwords]]

### A. Extra: a safety lock between the two databases ✅
- **What we did:** the engine refuses to start if its own database is the same as SOCO's database. That means the same cluster and the same name, even if the capital letters differ.
- **Why it matters:** the engine can never accidentally write into SOCO's data. → [[Engine Database]], [[Platform Database]]

### B. Extra: a one-command setup helper ✅
- **What we did:** a small script (`scripts/setup_engine_db.py`) sets up any environment in one go:
  - creates the drawers and their indexes;
  - replaces any index left over from an older design;
  - checks all 16 are there;
  - checks SOCO's database answers.

  It reports each database's name, never the password.
- **Why it matters:** when the servers arrive, finishing ENG-01 is one command per server. It also upgraded my laptop's database to v1.3 in one go.

### C. Extra: proving the SOCO login is read-only ✅
- **What we did:** asked the database what my login is *allowed* to do, instead of trying to write something. Trying a write would have been risky: if it worked, it would have changed SOCO's real data. The answer: it can read, and it can't change anything. Re-checked on 1 Oct.
- **Why it matters:** "the engine only reads SOCO's data" is now checked, not just promised. → [[Platform Database]]

## Result (1 Oct 2026)
- **dev is ready for v1.3:** all 16 collections exist in `SoCo` on my Atlas build cluster, with the new indexes and the 365-day auto-delete. → [[MongoDB Atlas]]
- SOCO's database answers when the engine reads it.
- **The login to SOCO's database is still read-only.** It can read, but it can't add, change or delete anything. → [[Platform Database]]
- Automatic checks: the 23 checks for this task pass (19 without a database, 4 on Atlas). The whole set without a database: 509 pass, 1 skipped.

## Decided
- **Where each setup runs (24 Sep 2026):**
  - **dev** runs on **my laptop**. It's ready now.
  - **test** runs on **a server**. Its database cluster will be created later. It reads made-up, SOCO-shaped data, never real data.
  - **production** runs on **a server** next to [[SOCO_BE]]. Its database cluster will be created later.

  More detail → [[Environments]]
- **Test now, production later (14 Oct 2026):** the test server is available, so the engine is set up there first. Every other task can then run its official check on test and become Passed. Production is set up later; it must be up before anything goes live for shoppers. → [[Environments]]
- **How long copies are kept (1 Oct 2026, from the pack):** 365 days from when the event really happened. This is fixed for Wave 1A; it's in the settings file but can't be changed. → [[Settings file]]

## Re-checked
- **28 Sep 2026:** the whole checklist was run again on my laptop, and everything passed. The record is in `Tracing/checks/Checklist_2026-09-28.md`.
- **1 Oct 2026:** after the v1.3 update: 16 of 16 drawers, read-only login, safety lock, and the password rules all checked on my laptop.

## Still to do
| What                                                             | Waiting on                          |
| ---------------------------------------------------------------- | ----------------------------------- |
| Set up the engine on the test server, with its own database cluster | The server's access details |
| Production: server and database cluster                          | Later (decided 14 Oct) → [[People]] |
| Change the read-only login's password (only the password changes) | Aravinth, DB-02                     |
| DB-02 is missing from the v1.3 Build List sheet; ask Kala to restore it | Kala, in writing                    |
| Put the engine next to [[SOCO_BE]] and give Aravinth its address | Aravinth's hosting                  |

## How this connects
- **Before it:** [[Before Wave 1A - the M1 demo]]
- **Built on:** [[Environments]], [[Engine Database]], [[Collections]], [[Indexes]], [[Secrets and passwords]]
- **Next:** [[ENG-02 - Service skeleton and settings]]. It organises the engine into 12 tidy parts and adds a settings file that can change without a restart.
- **Used by:** [[ENG-04 - Engine sync]] fills `ml_events`, `ml_orders` and `ml_sync_state`, the drawers v1.3 added here. → [[Engine sync]]
- **Demo:** [[Demo - ENG-01]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-01.md` in the repo.
