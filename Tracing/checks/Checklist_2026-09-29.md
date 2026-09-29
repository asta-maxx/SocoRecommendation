# Full checklist run: 29 Sep 2026, dev (laptop)

`bash scripts/run_checklist.sh`, from a clean, pushed working tree (commit e7b9ef1).

**Result: 25 passed, 0 failed.**

| Section | Lines | Result |
|---|---|---|
| 0. Before you start | tree clean, in step with GitHub, unit tests, database tests | 4/4 |
| 1. ENG-01 | environment and 12 collections, read-only login, safety lock, .env ignored, no passwords in files, production refuses .env | 6/6 |
| 2. ENG-02 | 12 modules, jobs mode, health 200 and 503, request log, live setting change, change diary, broken file refused, unversioned change refused | 9/9 |
| 3. ENG-03 | one of each record type, follows with text ids, sources and switch, ignored data, every real platform document | 5/5 |
| 4. Clean up | reco_demo dropped, no engine left running | 1/1 |

## Note on the run time
The run took much longer than usual (over 10 minutes), with no failures. The
router's DNS (192.168.1.1) was intermittently returning **malformed** answers to
the Atlas SRV lookup ("Message parser reports malformed message packet"). Every
test connection waited for those lookups. Cloudflare (1.1.1.1) and Google
(8.8.8.8) answered the same lookup cleanly. The fix is to set DNS to those
servers in System Settings → Network → Wi-Fi → Details → DNS.

## Not checkable yet
Test and production servers and clusters, production's read-only login (DB-02),
the private network (DB-12). Data to fix on SOCO's side: product categories not
in the 23 (DB-07), contentfeedbacks missing, cart request_id (DB-05).
