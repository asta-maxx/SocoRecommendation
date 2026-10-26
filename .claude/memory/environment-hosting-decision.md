---
name: environment-hosting-decision
description: "Where the three engine environments run — dev on Allen's laptop, test and production on servers, their Atlas clusters created later"
metadata:
  node_type: memory
  type: project
  originSessionId: 6c588693-28bf-4e69-8879-22dc21052fb3
  modified: 2026-09-23T19:31:11.790Z
---

Decided 24 Sep 2026:

- **dev** runs on Allen's laptop. Engine DB is `SoCo` on the Atlas build cluster `soco.4b7z1ko`. Platform DB is `soco` on `nex-dev.cob9whd`, set in `.env`.
- **test** runs on a server.
- **production** runs on a server in SOCO_BE's private network.

The test and production Atlas clusters will be created later.

**Why:** the pack requires three environments, each with its own engine DB (SD-04), and production next to SOCO_BE (SD-03). It doesn't say where each one physically runs.

**How to apply:**
- Keep test and production separate (the ENG-20 load test runs on test).
- Test reads only copied or constructed platform data (DB-13).
- Put production's cluster in the same region as its server.
- Test and production take settings from the server env, not `.env`.

Recorded in `docs/engineering/ENG-01.md` §4. See [[wave1a-pack-supersedes-earlier-docs]].
