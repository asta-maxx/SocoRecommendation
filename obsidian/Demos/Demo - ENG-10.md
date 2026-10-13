---
tags: [demo]
task: ENG-10
duration: about 4 minutes
---
# Demo: ENG-10, the interest score on SOCO's real data

## What this demo proves
The Build List's check for ENG-10 is *"All M1 checks in ENG-11 pass"*. That's [[Demo - ENG-11]]. This demo shows the other half: the score running on SOCO's **real** dev data, from the engine's own copy. → [[ENG-10 - Interest score on real data]]

> [!note] Rehearsed on 14 Oct 2026 on my laptop (Windows: use `.venv\Scripts\python.exe` where this says `.venv/bin/python`). Steps 1 and 2 write only to the engine's **own** dev database, as the nightly jobs do; SOCO's data is only read. Step 3 only reads.

## Setup (before the audience watches)
One terminal, in the repo folder.

## Steps

### 1. Bring the engine's copy up to date
- **Say:** "First the engine copies anything new from SOCO."
- **Run:**
  ```bash
  .venv/bin/python -m reco.jobs sync 2>&1 | grep -c '"job finished"'
  ```
- **They should see:** `1`

### 2. Work out everyone's interests, both methods
- **Say:** "Now the nightly interest job, run by hand. Watch what it reads and what it leaves out."
- **Run:**
  ```bash
  .venv/bin/python -m reco.jobs interest 2>&1 | grep -o 'recency_decay v[^"]*' | head -1
  ```
- **They should see** (trimmed):
  ```
  recency_decay v1.0.0: 8 of 15 users scored, 17 scores written ...
  views without a duration 10 ... Source: copies; left out before scoring:
  {'not_a_user': 8, 'repeat_views': 0, 'order_reversed': 1, 'business_follow_no_category': 2} ...
  ```
- **Point out:** *Source: copies*: it reads the engine's own copy, not SOCO's live log. 10 views had no on-screen time, so they don't count (Aravinth's APP-02). One cancelled or returned order added nothing.

### 3. Who now gets their own score
- **Say:** "The fallback ladder now finds real scores for some people."
- **Run:**
  ```bash
  .venv/bin/python scripts/show_ladder.py 2>/dev/null | tail -1
  ```
- **They should see:**
  ```
  15 users by step: rung_1 2, rung_2 6, rung_3_empty 7
  ```
- **Point out:** before ENG-10, nobody on dev reached rung 1.

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| Views counting | No view on dev has an on-screen time | Aravinth, APP-02 → [[Aravinth's tasks]] |
| Products' categories | The category map is empty | Me (ENG-29) |
| The same on the test server | Being set up | → [[Environments]] |

## Clean up
Nothing: the scores are the engine's normal nightly output on dev.

## How this connects
- Proves → [[ENG-10 - Interest score on real data]]
- How every demo is run → [[How to demo a task]]
- Previous demo → [[Demo - ENG-09]] · Next demo → [[Demo - ENG-11]]
