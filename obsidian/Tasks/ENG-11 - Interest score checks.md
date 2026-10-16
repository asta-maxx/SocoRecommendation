---
tags: [task, step-2]
task: ENG-11
status: Passed
owner: Allen
---
# ENG-11: Interest score checks

> [!note] Status: **Built** (14 Oct 2026, on my laptop)
> One script checks the whole interest score on made-up users and prints PASS or FAIL for each of the pack's 11 checks. **All 11 pass.** It becomes **Passed** once it passes on the test server and the output is saved in the shared "Wave1A checks" folder.

> [!success] Passed (16 Oct 2026)
> Kala: this task's check names no environment, so the run on my laptop is the evidence. 13 of 13 (15 Oct). It covers this task's own check, not the later ENG-30 changes. → [[Answers 16 Oct]]

> [!tip] Pack v1.4 (15 Oct 2026)
> Two more checks, from the rework list: **12, a test account is left out** (a made-up user with six likes, on the test-account list, gets no score) and **13, an unmapped category is reported** ("Cricket"). **13 of 13 pass.**

**In one line:** a single command that proves the interest score (M1) does what the pack says, end to end.

## Why this task
The go-live rule (ENG-24) only switches the feed on if this check passes. It's also M1's official "done" check (ENG-10's check is "all of ENG-11's checks pass"). → [[Build Steps]]

> [!example] The idea in one picture
> A driving test with a fixed route. Each made-up user is one manoeuvre: a hill start, a reverse park, an emergency stop. The examiner ticks each one PASS or FAIL.

## What came before
- [[ENG-10 - Interest score on real data]] built the score itself.
- [[ENG-09 - Fallback ladder]] built the rungs that check 10 tests.
- [[ENG-05 - Same method for each user]] built the method choice that check 11 tests.

## Subtasks, one by one

### 1. The made-up users ✅
- **What it asks:** load "the constructed test users".
- **What we did:** 14 made-up users, each built for one check: one who liked Home & Living yesterday but more Electronics two months ago; one who picked Pets at sign-up and did nothing with Pets; one who bought and cancelled; one who hid something; one per ladder rung; and so on.
- **Why it matters:** each check has a user whose right answer is known in advance.

### 2. Run the real engine on them ✅
- **What we did:** the script puts the users in a **throwaway** pretend-SOCO database, then runs the engine's real jobs on them: copying (sync), the interest score, and the popularity count. SOCO's data and the engine's real databases are never touched; both throwaway databases are deleted at the end.
- **Why it matters:** it tests the same path the servers run, not a shortcut.

### 3. The 11 checks ✅
| # | Check | Result |
|---|---|---|
| 1 | Every user with a category in the 23 has a score | ✅ 10 scored, 4 rightly not |
| 2 | Shares add up to 1 for each user | ✅ |
| 3 | No category below 0 | ✅ "hide" user's category set to 0 |
| 4 | Fading on: Home & Living first; fading off: Electronics first | ✅ 5.86 vs 2.25; off 6 vs 9 |
| 5 | The sign-up floor is there and doesn't fade | ✅ exactly 10 |
| 6 | Bought then cancelled nets to exactly zero | ✅ 0 |
| 7 | Made-up and broken categories are dropped | ✅ |
| 8 | Views under 3 seconds don't count | ✅ count 1 of 4 views |
| 9 | Both methods written, each named, with the version | ✅ |
| 10 | Each ladder rung reported for its user | ✅ all five |
| 11 | Same method after a restart; split within 2 points | ✅ within 0.8 points |

### 4. Save the output ✅
- **What it asks:** save the full output (the pack's Home sheet: `<task>_<date>`).
- **What we did:** each run saves `Tracing/checks/ENG-11_<date>.md`.
- **Status:** done locally. Copying it to the shared "Wave1A checks" folder waits on Sanjai creating it.

## Result (14 Oct 2026)
**11 of 11 passed**, first run. Record: `Tracing/checks/ENG-11_2026-10-14.md`.

## Still to do
| What | Waiting on |
|---|---|
| Run it on the **test** server, save the output, mark Passed | The test server → [[Environments]] |
| Put the output in the shared "Wave1A checks" folder | Sanjai |

## How this connects
- **Before it:** [[ENG-10 - Interest score on real data]]
- **Built on:** [[ENG-09 - Fallback ladder]], [[ENG-05 - Same method for each user]], [[Two methods per slot]], [[Nightly batches]], [[Engine sync]]
- **Next:** [[ENG-12 - Candidate sources]]. The first step of finding posts for the feed (M2).
- **Demo:** [[Demo - ENG-11]]. Run the script and watch the 11 checks.
- **Technical version:** `docs/engineering/ENG-11.md` in the repo.
