---
tags: [task, step-4]
task: ENG-20
status: In progress
owner: Allen
---
# ENG-20: Speed test

> [!note] Status: **In progress** (13 Oct 2026)
> Part 1's timer is built and works. It can't time SOCO's real feed yet, because I don't have the feed's address or a test login. Those come from Aravinth. Part 2 waits until serving is finished.

**In one line:** find out how fast SOCO's feed is today, and later prove the engine's lists come back fast enough (under 0.2 seconds for 95 out of 100 requests).

## Why this task
The engine gets **250 ms** per request. After that, SOCO's backend gives up and shows its own feed. So speed decides whether shoppers see the engine's lists at all. → [[Recommendation Engine]]

It sits in Step 4, but part 1 is meant to be done **right away**: the pack says it "needs nothing and should be done this week". Knowing today's speed sets how big the engine's shortlist can be. The go-live rule (ENG-24) needs both parts. → [[Build Steps]]

> [!example] The idea in one picture
> Before opening a new kitchen, time how long the old one takes to plate a dish. If the old one is already slow, the new menu must be smaller.

## What came before
- [[ENG-06 - Serve a recommendation list]] built the engine's serving door. Its own quick timing on my laptop was about 0.13 seconds (1 Oct). That doesn't count: the official test is on the test server.
- The **pool** is how many candidate posts the engine looks at for each list. The pack starts it at 300. It lives in the [[Settings file]].

## Subtasks, one by one

### 1. Time today's feed 🔨 timer built / ⏳ waiting on access
- **What it asks:** call SOCO's current feed (`/dashboard-feed`) at least 1,000 times, and write down how long the typical call takes (p50), the slow ones (p95: 95 in 100 are faster), and the very slow ones (p99).
- **What we did:** wrote a timing script. It calls the feed 10 times to warm up, then 1,000 times one by one, and saves the three numbers to a file named `ENG-20_<date>`. It never saves the address or the password. It also says which computer it ran on, because a laptop's internet adds time.
- **Why it matters:** this is the "before" number. Without it, we can't tell whether a slow list is the engine's fault.
- **Status:** tested against a pretend feed on my laptop (works, 0 errors). **The real run needs the feed's address and a test user's login from Aravinth.**

### 2. Cut the pool if today's feed is slow ⏳
- **What it asks:** if p95 is over **120 ms**, shrink the pool from 300 to 200.
- **What we did:** the script says which way it went. The change itself is made by hand in the settings file, so it's recorded with my name, like every other change.
- **Why it matters:** a smaller pool means less to sort through, so a faster answer.
- **Status:** waiting on part 1's number.

→ [[Settings file]]

### 3. Load-test the engine ⏳
- **What it asks:** once serving works, send the engine lots of requests at realistic volume and check that 95 in 100 come back within **200 ms**, measured from SOCO's backend. Each stage has its own limit: finding candidates 80 ms, ordering them 80 ms, sending the answer 40 ms.
- **What we did:** nothing yet.
- **Why it matters:** this is the "after" number, and the go-live rule needs it.
- **Status:** waits on serving being finished (ENG-06) and on the test server.

→ [[Environments]]

## Result (13 Oct 2026)
- The timer works: against a pretend feed, 1,000 calls gave p50 22 ms, p95 35 ms, p99 38 ms, with no errors. That result was thrown away, since it isn't SOCO's feed.
- It refuses to run with fewer than 1,000 calls, and never writes the password into the file.
- **No real number yet.**

## Decided
- **13 Oct 2026:** calls go one at a time, so each time is a single call, not one waiting behind another. Only successful calls are timed; failures are counted separately.
- **13 Oct 2026:** the script never changes the pool itself. A person does, so the change has a name on it.

## Still to do
| What | Waiting on |
|---|---|
| The feed's address and a test user's login | Aravinth → [[People]] |
| Run part 1 and save the numbers | The above |
| Put the file in the shared "Wave1A checks" folder | Sanjai creating the folder |
| Part 2: load test | [[ENG-06 - Serve a recommendation list]] finished, and the test server |

## How this connects
- **Before it:** [[ENG-08 - Filters]] (the last task built)
- **Built on:** [[Settings file]], [[Recommendation Engine]], [[SOCO_BE]]
- **Next:** [[ENG-09 - Fallback ladder]]. It decides what a new or quiet user is shown.
- **Technical version:** `docs/engineering/ENG-20.md` in the repo.
