---
tags: [concept, database]
---
# Engine Database

**My engine's own database**: its private notebook. It holds everything the engine works out or copies: scores, its copies of SOCO's activity and orders, fraud cases, job logs and so on.

- Only my engine writes here.
- Everything in it starts with `ml_` → see [[Collections]].
- Each of the three [[Environments]] has **its own** engine database, so testing never touches real data.

## Why separate from SOCO's database?
In the old demo, the plan was to keep my data *inside* SOCO's database (→ [[Before Wave 1A - the M1 demo]]). The pack changed that: my engine gets its own database, so it can never accidentally change SOCO's data. The code now **refuses to start** if someone points both at the same database.

## Where it is (so far)
| Environment | Where |
|---|---|
| dev (laptop) | `SoCo` on my build cluster (`soco.4b7z1ko`) in [[MongoDB Atlas]] |
| test (server) | Its own cluster, created later |
| production (server) | Its own cluster, created later, close to the production server |

## How this connects
- Its opposite is → [[Platform Database]].
- Its 16 collections were created in → [[ENG-01 - Engine home and databases]].
- Its first real contents are SOCO's activity and orders, copied in by the → [[Engine sync]] ([[ENG-04 - Engine sync]]).
