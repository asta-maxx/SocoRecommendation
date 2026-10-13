---
tags: [home]
---
# SOCO Recommendation Engine: start here

This vault explains, in plain words, what I'm building and why. Every note ends with **How this connects**, so you can follow the thread from one idea to the next.

> [!tip] Open the **Graph view** (left sidebar) to see how everything links together.

## The story so far
1. **SOCO** is a shopping-and-social app → [[SOCO App]]
2. Before this project I built a small demo of one piece → [[Before Wave 1A - the M1 demo]]
3. Now we're building the full thing, called **Wave 1A** → [[Wave 1A]]
4. The rules for it are in a set of five documents → [[The Pack]]
5. Three people are involved → [[People]]; what Aravinth has built and still owes → [[Aravinth's tasks]]
6. The work is split into steps → [[Build Steps]]

## The main pieces
- [[Recommendation Engine]]: what I'm building
- [[SOCO_BE]]: the app's backend, which talks to my engine
- [[Platform Database]]: SOCO's data, which I only read
- [[Engine Database]]: my own data, which I write
- [[MongoDB Atlas]]: where both databases live
- [[Environments]]: dev, test and production
- [[Collections]] and [[Indexes]]: how data is organised inside a database
- [[Secrets and passwords]]: keeping logins safe
- [[Settings file]]: every tunable number, in one place
- [[Logs]]: the engine's diary
- [[Activity events]]: what shoppers did, as the engine copies it from SOCO's activity log
- [[Engine sync]]: how the engine copies SOCO's activity, orders and served lists every 5 minutes
- [[Event source switch]]: retired in pack v1.3; kept to explain what the engine sync replaced
- [[Two methods per slot]]: how each user is given one of two methods, the same way every time
- [[Served list record]]: the receipt the engine keeps for every list it returns
- [[Nightly batches]]: the 2 AM recompute, and why a half-written batch is never read

## Tasks
- [[Audit 1 Oct]]: every task so far checked line by line against the pack, and what was fixed
- [[Task Board]]: every task and where it stands
- [[ENG-01 - Engine home and databases]]: laptop part done (16 drawers); test server being set up (14 Oct), production later
- [[ENG-02 - Service skeleton and settings]]: built; realigned to v1.3 on 1 Oct
- [[ENG-03 - Reading SOCO's data correctly]]: built; realigned to v1.3 on 1 Oct
- [[ENG-04 - Engine sync]]: built on laptop; real backfill done 1 Oct; waits on APP-12 and the test server
- [[ENG-05 - Same method for each user]]: built on laptop, 1 Oct
- [[ENG-06 - Serve a recommendation list]]: in progress; serving and recording work, real ranking waits on later tasks
- [[ENG-07 - Nightly jobs]]: built on laptop, 1 Oct; more jobs join as their tasks are built
- [[ENG-29 - Adapting to the platform as built]]: built on dev, 1 Oct; the category map still to fill
- [[ENG-08 - Filters]]: built on dev, 1 Oct; two answers from Aravinth pending
- [[ENG-09 - Fallback ladder]]: built on dev, 14 Oct; every feed list says which rung it used
- [[ENG-10 - Interest score on real data]]: built on dev, 14 Oct; M1 learns from the engine's own copy
- [[ENG-11 - Interest score checks]]: built, 14 Oct; all 11 checks pass
- [[ENG-20 - Speed test]]: part 1 timer built, 13 Oct; waits on the feed address and a test login

## Demos
- [[Checklist]]: one command that checks everything still works
- [[How to demo a task]]: how every demo is run
- [[Demo - ENG-01]]: the engine's home and databases
- [[Demo - ENG-02]]: skeleton, health check, logs, live settings
- [[Demo - ENG-03]]: reading SOCO's data correctly
- [[Demo - ENG-04]]: the engine sync
- [[Demo - ENG-05]]: the same method for each user
- [[Demo - ENG-06]]: serving a list and its record
- [[Demo - ENG-07]]: nightly jobs, and a job killed halfway
- [[Demo - ENG-29]]: adapting to the platform as built
- [[Demo - ENG-08]]: the twelve filters, one left out and one kept each
- [[Demo - ENG-09]]: each rung of the fallback ladder, and the ladder on real users
- [[Demo - ENG-10]]: the interest score on SOCO's real data
- [[Demo - ENG-11]]: the interest score's 11 checks
