---
tags: [concept]
---
# Served list record

Every time the engine returns a list to SOCO, it first writes down exactly what it returned. That note is the **served list record**. The pack calls it **E1** (`recommendation_request`). It goes into `ml_events`, next to the copies of SOCO's activity (→ [[Engine sync]]).

> [!example] Like a till receipt. The shop keeps a copy of every receipt, so later it can match "what was sold" against "what was paid".

## What it holds
| Part | What it is |
|---|---|
| `request_id` | A fresh random ID (a UUID) for this one list. SOCO copies it onto every view and tap of the list's items. |
| Who and where | `user_id`, `session_id`, `surface` (feed or product), the page and how many items |
| `policy_id` | The settings version and the method each slot used → [[Two methods per slot]] |
| `served_items` | The items, **exactly as returned**, with their positions from 1 |
| `candidate_ids` | Everything that was considered. Never sent to SOCO. |
| `slots` | For each slot, the method intended and the fallback step used |
| `scored_sample` | Every returned item, plus a random 10% of the ones not returned (all of them on an exploration list) |
| `server_ts` | When, in UTC, to the millisecond |

## Why it matters
- **Measurement.** Weekly measurements and the method comparison (ENG-25, ENG-26) join what users did back to the list it came from, through `request_id`.
- **No record, no list.** If the record can't be written, the engine returns an error and SOCO shows its own list instead. A list nobody can measure would be worse than none.
- **Kept a year,** like the event copies → [[Collections]].

SOCO's own lists (its fallback lists) are recorded by SOCO in `recommendationrequests`. Their `policy_id` doesn't start with `cfg`, so the two are never confused.

## How this connects
- Written by → [[ENG-06 - Serve a recommendation list]].
- Lives in `ml_events`, made in → [[ENG-01 - Engine home and databases]].
- Its `policy_id` comes from → [[ENG-05 - Same method for each user]].
