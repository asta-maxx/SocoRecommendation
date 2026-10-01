---
tags: [demo, checklist]
---
# Checklist: is everything still working?

One command runs every check for every finished task and prints **PASS** or **FAIL** for each line. Run it before a demo, after a change, or whenever you want to be sure.

```bash
bash scripts/run_checklist.sh
```

It takes about 4 minutes. It ends with `Result: N passed, 0 failed` when all is well. It only **reads** SOCO's data. Anything it writes goes into a throwaway database (`reco_demo`) that it deletes at the end. It uses its own ports (8190/8191), so a demo already running isn't disturbed.

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
| 1.1 | The engine knows it's in dev, has its own database, and all 16 drawers exist (16 of 16) |
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
| 3.1 | One of each kind of SOCO record is read correctly (the task's official check) |
| 3.2 | …including the four cases the check names: follows with IDs stored as plain text, a business account as the actor, a product post on SOCO's own feed list, and an order with a status history and a return request |
| 3.3 | Each kind of data comes from one place, and there is no event source switch → [[Event source switch]] |
| 3.4 | The fields the pack says to ignore are never read |
| 3.5 | Every real document in SOCO's database reads without a single failure |

### 4. ENG-04: the engine sync → [[ENG-04 - Engine sync]]
Lines 4.3 to 4.9 act out the task's official check, (a) to (g) → [[Engine sync]].

| Line | Checks |
|---|---|
| 4.1 | Each copy keeps where it came from, its IDs, its undo details and its E code; orders keep their status history (tests) |
| 4.2 | The first full copy (backfill) is filed under SOCO's own IDs and can restart halfway without duplicates (tests) |
| 4.3 | (a) The daily audit compares IDs **and** field values, and re-reads any mismatch (tests) |
| 4.4 | (b) A like undone after it was copied updates the existing copy (tests) |
| 4.5 | (c) Stopping the sync for an hour and restarting loses nothing and doubles nothing (tests) |
| 4.6 | (d) Two rows with the same change time across a page break are both copied (tests) |
| 4.7 | (e) A failure before the bookmark is saved reads that batch again (tests) |
| 4.8 | (f) The alert fires when the sync is behind, and when a run fails (tests) |
| 4.9 | (g) Copies are kept 365 days from when the event really happened (tests) |
| 4.10 | A real backfill from SOCO's data into the throwaway database finishes for all three collections |
| 4.11 | A real audit of yesterday passes |

### 5. ENG-05: the same method for each user → [[ENG-05 - Same method for each user]]
| Line | Checks |
|---|---|
| 5.1 | The same user gets the same method across two restarts (tests) |
| 5.2 | Changing a split moves users at once, with no new release (tests) |
| 5.3 | Over 10,000 made-up IDs, each split lands within 2 points, at 50, 25, 10 and 0 (tests) |
| 5.4 | With the settings missing, everyone gets the default and the fault is logged (tests) |
| 5.5 | The real settings file splits 10,000 IDs within 2 points in all three slots |

### 6. ENG-06: serve a list and record it → [[ENG-06 - Serve a recommendation list]]
| Line | Checks |
|---|---|
| 6.1 | The rules of the door: wrong token 401, bad input 400, surface off or internal 503, a database fault 503 with no retry, the answer's shape (tests) |
| 6.2 | On made-up SOCO data: only eligible items, newest first, and the record matches the answer (tests) |
| 6.3 | Over the network, 19 feed requests: p95 within 200 ms, every record matches the answer |
| 6.4 | The same for the product surface |
| 6.5 | A wrong token is refused (401) |
| 6.6 | Setting the feed to off in the settings (no restart) gives 503 |

### 7. ENG-07: nightly jobs → [[ENG-07 - Nightly jobs]]
| Line | Checks |
|---|---|
| 7.1 | The scheduler runs at the time in the settings (2 AM India time), with the sync's daily audit last; one failed job doesn't stop the others (tests) |
| 7.2 | A batch is read only once it's complete and current; every row carries its history (tests) |
| 7.3 | A job that fails halfway leaves the previous batch in use (tests) |
| 7.4 | A killed run is recorded as failed and never read (tests) |
| 7.5 | A real kill (SIGKILL) halfway: requests still read the previous batch, and the run diary shows the failure |
| 7.6 | A real nightly run: both interest methods end up current |

### Last line: clean up
| Line | Checks |
|---|---|
| Z.1 | The throwaway database is gone and no test engine is left running |

## If a line fails
- **0.1 or 0.2:** save and push your work first (or ask Claude to commit and push).
- **0.4, or everything touching the database:** the Atlas cluster may be paused, or the network blinked. See [[How to demo a task]] → *If something goes wrong*.
- **The run is very slow** (more than 5 minutes) but nothing fails: your router's DNS is probably giving broken answers. Seen on 29 Sep 2026, when the router at `192.168.1.1` returned malformed replies and the run took over 10 minutes. Set DNS to `1.1.1.1` and `8.8.8.8` in System Settings → Network → Wi-Fi → Details → DNS.
- **Anything else:** it's a real problem. Note which line failed and look at the message under it.

## Last full run
1 Oct 2026, pack v1.3, ENG-01 to ENG-07: **53 passed, 0 failed.** The first run that day failed two lines (4.1 and 4.3) only because the script expected too few tests after new ones were added; every test passed. The counts were corrected and the whole list was run again. Record: `Tracing/checks/Checklist_2026-10-01.md`.

Earlier: 29 Sep 2026, on the 22 Sep design: 31 passed, 0 failed (`Tracing/checks/Checklist_2026-09-29.md`).

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
