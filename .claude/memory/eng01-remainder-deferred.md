---
name: eng01-remainder-deferred
description: ENG-01's server parts (test/prod servers, Atlas clusters, deploy, DB-12 address) are deferred; the user will get them later
metadata:
  type: project
---

On 24 Sep 2026 the user (Allen) said they will get ENG-01's remaining parts later. Aravinth has been asked for them:

- test and production servers (SD-03);
- the test and production Atlas clusters;
- the deploy, then the DB-12 private address;
- rotation of the DB-02 password.

ENG-01 stays **Waiting** in `docs/engineering/ENG-01.md` and the Obsidian task note until then. Work moved on to ENG-02 on dev (the laptop).

**Why:** the laptop part of ENG-01 is done and verified. The rest is blocked on Aravinth.
**How to apply:** don't chase these items. When the user says they've arrived, run `scripts/setup_engine_db.py` per environment, save `ENG-01_<date>`, and mark ENG-01 Passed. See [[environment-hosting-decision]].
