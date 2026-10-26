---
tags: [demo]
task: ENG-11
duration: about 3 minutes
---
# Demo: ENG-11, the interest score's 11 checks

## What this demo proves
The Build List's check for ENG-11: *"All 11 checks pass, and the output is saved."* It is also ENG-10's check. → [[ENG-11 - Interest score checks]]

> [!note] Rehearsed on 14 Oct 2026 on my laptop. Everything it writes goes into two throwaway databases (`reco_m1_check` and `reco_m1_check_platform`), deleted at the end. SOCO's data and the engine's real databases are never touched.

## Setup (before the audience watches)
One terminal, in the repo folder.

## Steps

### 1. Run the check script
- **Say:** "Fourteen made-up users, each built to test one rule. The script loads them, runs the engine's real nightly jobs on them, and checks the answers."
- **Run:**
  ```bash
  .venv/bin/python scripts/check_m1.py 2>/dev/null | grep -E "succeeded|PASS|FAIL|Result"
  ```
- **They should see:**
  ```
    python -m reco.jobs sync        succeeded
    python -m reco.jobs interest    succeeded
    python -m reco.jobs popularity  succeeded
    PASS   1. Scores exist for every user with a mappable category
    PASS   2. Share sums to 1 per user
    PASS   3. Raw is never below 0
    PASS   4. Decay on: Home & Living above Electronics; decay off: the order flips
    PASS   5. The declared floor is present and not decayed
    PASS   6. A bought-then-cancelled order nets to exactly zero
    PASS   7. Unmappable and malformed categories are dropped
    PASS   8. event_count excludes views under 3 seconds
    PASS   9. Both methods are written with method name and model_version
    PASS  10. Each fallback rung is reported for its test user
    PASS  11. Method assignment is stable across restarts; split within 2 points
  Result: 11 of 11 passed
  ```

### 2. The saved output
- **Say:** "The pack asks for the output to be saved. Here it is, with what each check saw."
- **Run:**
  ```bash
  grep -A1 " 4\. \| 5\. " Tracing/checks/ENG-11_2026-10-14.md
  ```
- **They should see:**
  ```
    PASS   4. Decay on: Home & Living above Electronics; decay off: the order flips
             on: Home & Living 5.86 vs Electronics 2.25; off: Home & Living 6.00 vs Electronics 9.00
    PASS   5. The declared floor is present and not decayed
             Pets raw (decay, windows): [10.0, 10.0]; declared, no Pets action; one Electronics click 200 days ago
  ```

## What you can't show yet
| Part | Why not | Waiting on |
|---|---|---|
| The same on the test server | Being set up | → [[Environments]] |
| The output in the shared "Wave1A checks" folder | The folder doesn't exist yet | Sanjai |

## Clean up
Nothing: the script deletes its two throwaway databases.

## How this connects
- Proves → [[ENG-11 - Interest score checks]]
- How every demo is run → [[How to demo a task]]
- Previous demo → [[Demo - ENG-10]]
