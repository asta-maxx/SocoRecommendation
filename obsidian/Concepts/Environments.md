---
tags: [concept]
---
# Environments

The same engine runs in **three separate setups**, so mistakes never reach real users:

| Environment | What it's for | Runs on | Who sees it |
|---|---|---|---|
| **dev** | Where I build and try things | **My laptop** | Only me |
| **test** | Where every check is run, on made-up data | **A server** | Me and Aravinth |
| **production** | The real thing | **A server** next to [[SOCO_BE]] | Real SOCO users |

Each one has **its own** [[Engine Database]], so testing can never overwrite real data.

> [!note] Decided 24 Sep 2026. The pack says there must be three setups, but not where they run. That part was our choice.

## Four rules that come with this
1. **Test and production are kept apart:** separate servers, or at least separate boxes on one machine. The speed test runs on test and must never slow down real users.
2. **Test never uses real SOCO data.** It uses a copy or made-up data, because the checks create their own users and orders.
3. **Production's database lives close to its server.** Every request has to finish in 0.2 seconds, so the database can't be far away.
4. **Test keeps its passwords in the server's settings, like production does.** Then whatever works on test also works for real. See [[Secrets and passwords]].

## How the engine knows which one it's in
A setting called `ENGINE_ENV`, set to `dev`, `test` or `production`. On my laptop it isn't set, so it defaults to **dev**.

The engine's health page (`/health`) now says which environment it's in.

## Where things stand
- **dev (laptop):** ready.
- **test (server):** its database cluster will be created later. It also needs a server, and Aravinth's test setup (task DB-13).
- **production (server):** its database cluster will be created later. It also needs Aravinth's hosting and the new login (DB-02).

## How this connects
- Required by → [[ENG-01 - Engine home and databases]].
- Production has strict rules about passwords → [[Secrets and passwords]].
- The demo only had one setup → [[Before Wave 1A - the M1 demo]].
