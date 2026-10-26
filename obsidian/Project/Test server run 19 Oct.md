---
tags: [project, checks]
---
# Test server run, 19 Oct 2026

**In one line:** the first run of all the checks on the test server: everything that doesn't depend on speed passed; the server is too slow and too far from the database to prove the speed targets.

## What passed
- All the interest-score checks (M1), finding posts (M2), the promoter score (M8), the feed ranking, and the foundation (settings, copying SOCO's data, method choice, filters).
- So these became **Passed**: [[ENG-02 - Service skeleton and settings]], [[ENG-04 - Engine sync]], [[ENG-13 - Quotas]], [[ENG-15 - Merge the shortlist]], [[ENG-16 - Promoter score]], [[ENG-19 - Ordering the feed]]. (ENG-05, 08, 09, 10 and 11 were already Passed.)

## What didn't, and why
- **Speed.** One trip from the server to the database takes about a quarter of a second (from my laptop: a fortieth), and the machine itself is 10 to 20 times slower than my laptop. A list must come back within a fifth of a second, so the engine gives up and SOCO's own ordering would show instead, exactly as designed. Five checks failed for this reason, and probably a sixth (stopping a job halfway).
- **One mistake of mine in the checklist:** it put test data into the wrong database name on the test server; the safety check refused it. Fixed.

## What's needed
- A test server **close to the database** and a bit bigger (2 to 4 cores, 8 GB), to prove the speed. → [[Environments]]
- Until then, the speed-related tasks stay **Built**: ENG-03, 06, 07, 12, 14, 17 and 29.

## How this connects
- The proofs (with PDFs) are in `Test Output (test server)/` in the repo, one folder per model.
- **Technical version:** `Tracing/checks/TEST_SERVER_2026-10-19.md`.
- → [[Task Board]], [[Jira updates]]
