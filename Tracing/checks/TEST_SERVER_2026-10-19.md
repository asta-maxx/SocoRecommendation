# Test server run, 19 Oct 2026

`bash scripts/test_server_run.sh` on the test server (`revealer`, Windows Server 2019, Git Bash), environment **test**, engine database `soco_engine_test`, commit `6ddc3ce` (branch `wave1a/eng-09-11-m1`). Raw proofs received by WeTransfer (19 files, no `checklist_server.txt`); scanned for secrets (none); filed with PDFs in `Test Output (test server)/` (`python scripts/make_proofs.py "Test Output (test server)"`).

**Result: 85 passed, 8 not passed.**

| Task | Passed | Not passed | Why |
|---|---|---|---|
| ENG-01 | 6 / 6 | | Test environment; production still to come |
| ENG-02 | 11 / 11 | | → **Passed** |
| ENG-03 | 4 / 5 | 3.5 | The connection dropped during the long read of every real platform document (distance) |
| ENG-04 | 11 / 11 | | → **Passed** |
| ENG-05 | 5 / 5 | | (already Passed) |
| ENG-06 | 3 / 6 | 6.2, 6.3, 6.4 | A request may take 250 ms in all and one round trip to Atlas takes about 250 ms: the engine answers 503 at once (`ExecutionTimeout`, "network round trip time 0.25") |
| ENG-07 | 5 / 6 | 7.5 | Killing a job halfway: its timing assumes a normal machine; to confirm on a faster server |
| ENG-08 | 6 / 6 | | (already Passed) |
| ENG-09, 10, 11 | 4, 2, 1 | | All 18 M1 checks; (already Passed) |
| ENG-12 | 3 / 3 | | Rules pass; its check is the 20 ms timing "on test load", which this server cannot show: stays Built |
| ENG-13 | 2 / 2 | | → **Passed** |
| ENG-14 | 3 / 3 | | Its check is a 20 ms read: the database plan passes, the wall time cannot be shown here: stays Built |
| ENG-15 | 2 / 2 | | → **Passed** |
| ENG-16 | 3 / 3 | | → **Passed** |
| ENG-17 | 2 / 3 | 16.2 | Served through the request path, whose 250 ms limit the round trip uses up |
| ENG-19 | 2 / 2 | | → **Passed** |
| ENG-29 | 8 / 9 | 8.9 | **A checklist fault**: it seeded `soco_engine_test`, which on the test server is the engine's own database, and the seed rightly refused. Fixed: it seeds `soco_platform_test` |

## The server

- **Far from the database:** one round trip to Atlas about **250 ms** (pymongo's measured round trip in the 6.2 failure), against about 25 ms from the laptop. The MongoDB tests took 1 to 3 minutes each (the laptop: seconds).
- **Slow by itself:** the tests with no database took 9 to 19 s, against 0.6 to 1.1 s on the laptop (about 10 to 20 times slower): e.g. `test_similar.py` 35 tests 11.83 s (laptop 0.63 s), `test_quotas.py` 23 tests 13.34 s (0.95 s).
- So: everything that does not depend on speed is valid here; the speed checks (ENG-06 200 ms, ENG-12 and ENG-14 20 ms, ENG-20) need a server **in the same region as the Atlas clusters**, with at least 2 to 4 cores and 8 GB. Also worth trying on this one: a Windows Defender exclusion for the repo folder.

## Changes made from this run (19 Oct 2026)

- Checklist 8.9 seeds `soco_platform_test` (`scripts/seed_test_platform.py` examples too).
- Checklist 16.4 (new): both product methods serve, one request each through the request path (`scripts/try_product_methods.py`; on dev: both served 10 items, method two through step 1, labelled intent).
- Checklist section 18 (new): ENG-30 point 4 and the daily report of unmatched history texts.
- `scripts/make_proofs.py` takes a folder and writes environment-specific notes and index.
- ENG-02, ENG-04, ENG-13, ENG-15, ENG-16, ENG-19 marked **Passed** in both sets of docs.
