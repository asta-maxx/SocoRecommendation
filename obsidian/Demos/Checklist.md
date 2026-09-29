---
tags: [demo, checklist]
---
# Checklist: is everything still working?

One command runs every check for every finished task and prints **PASS** or **FAIL** for each line. Run it before a demo, after a change, or whenever you want to be sure.

```bash
bash scripts/run_checklist.sh
```

It takes about 3 minutes. It ends with `Result: N passed, 0 failed` when all is well. It only **reads** SOCO's data. Anything it writes goes into a throwaway database (`reco_demo`) that it deletes at the end. It uses its own ports (8190/8191), so a demo already running isn't disturbed.

## What each line checks, in plain words

### 0. Before you start
| Line | Checks | Why |
|---|---|---|
| 0.1 | Nothing is half-saved in git | So what you show is what's on GitHub |
| 0.2 | Your copy matches GitHub | Same reason |
| 0.3 | All the automatic tests pass (about 475) | The quick safety net |
| 0.4 | The database tests pass | Also proves the Atlas cluster is awake |

### 1. ENG-01: the engine's home → [[ENG-01 - Engine home and databases]]
| Line | Checks |
|---|---|
| 1.1 | The engine knows it's in dev, has its own database, and all 12 drawers exist |
| 1.2 | The login to SOCO's data can only read, never change |
| 1.3 | The engine refuses to start if its database is SOCO's |
| 1.4 | The password file is never uploaded to GitHub |
| 1.5 | No password is written anywhere in the code or notes |
| 1.6 | In production, the engine refuses a password file |

### 2. ENG-02: skeleton, health, logs, settings → [[ENG-02 - Service skeleton and settings]]
| Line | Checks |
|---|---|
| 2.1 | The 12 parts exist, and only the right parts can read SOCO's data or write |
| 2.2 | The "jobs" way of running works |
| 2.3 | The health page says OK (200) when both databases work |
| 2.4 | …and says NOT OK (503) when one is down |
| 2.5 | Every request is written to the log |
| 2.6 | A settings change takes effect within a minute, with no restart |
| 2.7 | The change diary records who changed what |
| 2.8 | A broken settings file is refused, and the engine keeps running |
| 2.9 | A change without a new version number is refused |

### 3. ENG-03: reading SOCO's data → [[ENG-03 - Reading SOCO's data correctly]]
| Line | Checks |
|---|---|
| 3.1 | Every kind of SOCO record is read correctly (the task's official check) |
| 3.2 | …including follows, whose IDs are stored as plain text |
| 3.3 | Each kind of data comes from one place, and the old-to-new log switch never double-counts → [[Event source switch]] |
| 3.4 | The fields the pack forbids are never read |
| 3.5 | Every real document in SOCO's database reads without a single failure |

### 5. ENG-04: receiving events → [[ENG-04 - Receiving activity events]]
| Line | Checks |
|---|---|
| 5.1 | Every rule for refusing a bad event, and duplicates, work (tests) |
| 5.2 | The daily comparison fixes the switch date only after 7 good days (tests) |
| 5.3 | A real batch sent to the running engine is stored |
| 5.4 | The same batch again comes back as all duplicates (the task's official check) |
| 5.5 | An event with position 0 is refused with a reason (the task's official check) |
| 5.6 | Without the token, the door says 401 |

### 4. Clean up
| Line | Checks |
|---|---|
| 4.1 | The throwaway database is gone and no test engine is left running |

## If a line fails
- **0.1 or 0.2:** save and push your work first (or ask Claude to commit and push).
- **0.4, or everything touching the database:** the Atlas cluster may be paused, or the network blinked. See [[How to demo a task]] → *If something goes wrong*.
- **The run is very slow** (more than 5 minutes) but nothing fails: your router's DNS is probably giving broken answers. Seen on 29 Sep 2026, when the router at `192.168.1.1` returned malformed replies and the run took over 10 minutes. Set DNS to `1.1.1.1` and `8.8.8.8` in System Settings → Network → Wi-Fi → Details → DNS.
- **Anything else:** it's a real problem. Note which line failed and look at the message under it.

## Last full run
29 Sep 2026: **25 passed, 0 failed.** Record: `Tracing/checks/Checklist_2026-09-29.md`.

## What the checklist can't check yet
- The test and production servers, production's own login, and the private network: all waiting on Aravinth → [[People]].
- **Data to fix on SOCO's side:**
  - product categories not in the 23 (DB-07);
  - the missing feedback log;
  - `request_id` on cart lines (DB-05).

## How this connects
- Every line comes from a task's check on the → [[Task Board]].
- The same steps, shown live to an audience → [[How to demo a task]].
- Each new task adds its own lines here as it's built.
