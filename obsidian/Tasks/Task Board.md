---
tags: [task, board]
---
# Task Board

My tasks (ENG-…) in the pack's order. A link turns solid once its note exists.

## Step 1: foundations
- [ ] [[ENG-01 - Engine home and databases]]: **waiting** (realigned to v1.3 on 1 Oct: 16 of 16 drawers on laptop; test server ready 14 Oct and being set up; production later) · [[Demo - ENG-01|demo]]
- [ ] [[ENG-02 - Service skeleton and settings]]: **built** (realigned to v1.3 on 1 Oct: sync replaces events, v1.3 settings; check passed on laptop; re-run on the test server later) · [[Demo - ENG-02|demo]]
- [x] [[ENG-03 - Reading SOCO's data correctly]]: **passed** (16 Oct, Kala: dev run counts) · was built (realigned to v1.3 on 1 Oct: no event source switch; check passed on laptop; re-run on the test server later) · [[Demo - ENG-03|demo]]
- [ ] [[ENG-04 - Engine sync]]: **built** (laptop/dev; real backfill done 1 Oct; waits on APP-12 updated_at and the test server) · [[Demo - ENG-04|demo]]
- [x] [[ENG-05 - Same method for each user]]: **passed** (16 Oct, Kala: dev run counts) · was built (1 Oct, laptop; re-run on the test server later) · [[Demo - ENG-05|demo]]
- [ ] [[ENG-20 - Speed test|ENG-20 (part 1)]]: Time today's feed: **in progress** (13 Oct: timer built and tested; the real run waits on the feed's address and a test login from Aravinth)

## Step 2: serving lists
- [ ] [[ENG-06 - Serve a recommendation list]]: **built** (16 Oct, Kala S2; passed once checked on the test server) (1 Oct: serving, record, modes, exploration and errors work; interim newest-first lists until ENG-08, ENG-09, ENG-17, ENG-19 and ENG-29) · [[Demo - ENG-06|demo]]
- [x] [[ENG-07 - Nightly jobs]]: **passed** (16 Oct, Kala: dev run counts) · was built (1 Oct, laptop: batches, run diary, 2 AM scheduler, M1; other jobs join with their tasks) · [[Demo - ENG-07|demo]]
- [x] [[ENG-29 - Adapting to the platform as built]]: **passed** (16 Oct, Kala: dev run counts) · was built (1 Oct, dev: tracking stages, spellings, account lists, daily category check, serve log in the sync, made-up test data; rework for v1.4 done 15 Oct; the category map is yours to fill) · [[Demo - ENG-29|demo]]
- [ ] [[ENG-30 - Adapting to the October platform facts]]: **in progress** (new in pack v1.4; 15 Oct: order history as events, returns only at Returned, E-12 check done; return requests, one person, reposts, commission settings to build)
- [x] [[ENG-08 - Filters]]: **passed** (16 Oct, Kala: dev run counts) · was built on dev (1 Oct: all twelve rules, logged, re-checked before each list goes out; two answers from Aravinth pending: block fields, accounts with no status) · [[Demo - ENG-08|demo]]
- [x] [[ENG-09 - Fallback ladder]]: **passed** (16 Oct, Kala: dev run counts) · was built (14 Oct, dev: all five rungs, "rung 3 empty", the rung on every feed list, nightly popularity; re-run on the test server later) · [[Demo - ENG-09|demo]]
- [x] [[ENG-10 - Interest score on real data]]: **passed** (16 Oct, Kala: dev run counts) · was built (14 Oct, dev: every v1.3 action and weight, from the engine's copies; 8 of 15 dev users scored; re-run on the test server later) · [[Demo - ENG-10|demo]]
- [x] [[ENG-11 - Interest score checks]]: **passed** (16 Oct, Kala: dev run counts) · was built (14 Oct: all 11 checks pass; output saved; re-run on the test server later) · [[Demo - ENG-11|demo]]

## Step 3: finding and scoring
- [ ] ENG-12 to ENG-15: Finding candidate posts
- [ ] ENG-16: Promoter score
- [ ] ENG-17: Product "you might also like"

## Step 4: ranking and fraud
- [ ] ENG-18: Opportunity scores (hidden)
- [ ] ENG-19: Ordering the feed
- [ ] [[ENG-20 - Speed test|ENG-20 (part 2)]]: Speed test (waits on ENG-06 and the test server)
- [ ] ENG-21: Fraud rules and review cases
- [ ] ENG-22: Retrieval and product checks

## Step 5: acceptance and monitoring
- [ ] ENG-23: Final acceptance queries
- [ ] ENG-24: Go-live rule, safety switch and weekly report
- [ ] ENG-25: Weekly measurements

## After launch
- [ ] ENG-26: Compare the two methods every two weeks

## How this connects
- The steps are explained in → [[Build Steps]].
- Who waits on whom → [[People]].
- Aravinth's side, tracked here because the pack is never edited → [[Aravinth's tasks]].
- What Kala and the app team answered on 16 Oct → [[Answers 16 Oct]].
