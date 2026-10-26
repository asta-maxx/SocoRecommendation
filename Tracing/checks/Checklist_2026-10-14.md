# Checklist run, 14 Oct 2026 (after ENG-09, before commit)

Laptop (Windows, Git Bash), Atlas build cluster; throwaway reco_demo. **69 passed, 3 failed.**

- 0.1: run before committing the ENG-09 work (uncommitted changes).
- 6.3: feed p95 309 ms (median 278), every record matched (19 of 19). 3 Oct, before ENG-09: 257 ms. The ladder adds reads on the feed (run alongside candidate building); the link was also slow this day (6.4 product, which walks no ladder, went from ~350 ms to 681 ms). The pack's 200 ms check is on test, next to the database (ENG-20).
- 6.4: product rail empty on dev (question 17), as before.
- Section 10 (ENG-09): 10.1 to 10.4 all pass.

```
== 0. Before you start
  FAIL  0.1 working tree clean
        uncommitted changes: commit or stash before a demo
  PASS  0.2 branch in step with GitHub
  PASS  0.3 unit tests pass
  PASS  0.4 database tests pass (Atlas awake)
== 1. ENG-01: the engine's home and databases
  PASS  1.1 environment, own database, 16 collections
  PASS  1.2 platform login is read-only
  PASS  1.3 safety lock refuses engine = platform
  PASS  1.4 .env is ignored by git
  PASS  1.5 no connection string with a password in tracked files
  PASS  1.6 production refuses a .env file
== 2. ENG-02: skeleton, health, logs, live settings (throwaway reco_demo)
  PASS  2.1 twelve modules; gatekeepers hold
  PASS  2.2 jobs mode
  PASS  2.3 health 200 with both databases up
  PASS  2.4 health 503 with the engine database down
  PASS  2.4b health 503 with the platform database down
  PASS  2.5 every request is logged
  PASS  2.6 setting change in force within a minute, logged
  PASS  2.7 change diary shows who changed what
  PASS  2.8 broken file rejected; still serving
  PASS  2.9 change without a new version refused
== 3. ENG-03: reading SOCO's data correctly
  PASS  3.1 one of each record type (the ENG-03 check)
  PASS  3.2 the four cases the ENG-03 check names
  PASS  3.3 one source per kind; no event source switch
  PASS  3.4 ignored platform data is never read
  PASS  3.5 every real platform document reads cleanly
== 4. ENG-04: the engine sync
  PASS  4.1 copies keep source, ids, undo fields, E code; order history
  PASS  4.2 backfill keyed on the platform _id, restartable
  PASS  4.3 (a) reconciliation: ids and field values, mismatches re-read
  PASS  4.4 (b) a like undone after copying updates the copy
  PASS  4.5 (c) an hour stopped: nothing lost, nothing doubled
  PASS  4.6 (d) same updated_at across a page boundary
  PASS  4.7 (e) a failure before the checkpoint re-reads the batch
  PASS  4.8 (f) the alert fires: behind, and a failed run
  PASS  4.9 (g) retention: 365 days on the original time
  PASS  4.10 real backfill from SOCO into reco_demo
  PASS  4.11 real reconciliation of yesterday passes
== 5. ENG-05: the same method for each user
  PASS  5.1 same method across two restarts
  PASS  5.2 changing a split moves users with no deploy
  PASS  5.3 10,000 ids: each split within 2 points
  PASS  5.4 missing settings or user_id: everyone gets the default, logged
  PASS  5.5 the real settings file splits within 2 points
== 6. ENG-06: serve a list and record it (throwaway reco_demo, port 8192)
  PASS  6.1 contract: 401, 400s, 503 off/internal, database fault, response shape
  PASS  6.2 constructed data: eligible newest first; record matches the response
  FAIL  6.3 feed over HTTP: p95 within 200 ms; every record matches
          p95 309 ms (median 278 ms) -> OVER 200 ms   records with served_items matching the response: 19 of 19 
  FAIL  6.4 product over HTTP: p95 within 200 ms; every record matches
          p95 681 ms (median 607 ms) -> OVER 200 ms   records with served_items matching the response: 19 of 19 
  PASS  6.5 a wrong token is 401
  PASS  6.6 feed set to off (no restart): 503
== 7. ENG-07: daily refresh jobs (throwaway reco_demo)
  PASS  7.1 the scheduler runs at the set time (2 AM IST), reconciliation last; one failed job doesn't stop the rest
  PASS  7.2 a batch is read only once complete; rows carry provenance
  PASS  7.3 a failure halfway keeps the previous batch
  PASS  7.4 a killed run is recorded as failed and never read
  PASS  7.5 a real kill halfway: previous batch still read
  PASS  7.6 the real nightly run: both methods and the popularity batch current
== 8. ENG-29: adapting to the platform as built
  PASS  8.1 the constructed test data covers every platform collection and reads
  PASS  8.2 an unmapped category is reported, and left out until mapped
  PASS  8.3 test-account and exemption lists (expiry, logged); a test account is left out of scoring
  PASS  8.4 an order's history from tracking_info: delivery, return request, who cancelled
  PASS  8.5 a product post on a feed list keeps post_id and product_id apart
  PASS  8.6 rec_serve_log rows are read and copied
  PASS  8.7 status spellings from the settings
  PASS  8.8 the real daily category check runs on SOCO's data
  PASS  8.9 the engine test environment holds the constructed data
== 9. ENG-08: eligibility filters E-01 to E-12
  PASS  9.1 each rule E-01 to E-12: one item excluded, one kept (the ENG-08 check)
  PASS  9.2 the viewer's follows, blocks and feedback are read when the list is built
  PASS  9.3 every exclusion is logged with request_id, item_id and rule
  PASS  9.4 an item failing the final recheck is replaced by the next eligible one
  PASS  9.5 the rules run on SOCO's real data
== 10. ENG-09: the fallback ladder
  PASS  10.1 each rung is reported on the response and the record (the ENG-09 check)
  PASS  10.2 one test user per rung; first match wins; 4 and 5 fall to 3; rung 3 empty
  PASS  10.3 on a database: the 5 qualified actions, the nightly popularity, one user per rung
  PASS  10.4 the ladder walks SOCO's real users (reads only)
  PASS  Z.1 clean up: reco_demo dropped, no engine left running
== Result: 69 passed, 3 failed
```
