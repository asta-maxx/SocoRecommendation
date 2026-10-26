---
tags: [concept]
---
# Engine sync

The **engine sync** is how the engine gets SOCO's activity. It copies three of SOCO's collections into the engine's own database, using the read-only login:

| SOCO's collection | Holds | Copied into |
|---|---|---|
| `postevents` | What shoppers did (views, taps, likes…) | `ml_events` |
| `recommendationrequests` | Lists that were served | `ml_events` |
| `orders` | Orders and their status | `ml_orders` |

It runs in the engine's **jobs** mode, on its own 5-minute timer rather than the 2 AM nightly run (→ [[Recommendation Engine]]). SOCO doesn't knock on a door; the engine goes and reads. It replaced the retired `POST /v1/events` → [[Activity events]].

> [!example] Like a clerk photocopying a busy office's in-tray into the archive. First the clerk copies the whole filing cabinet once. After that, every 5 minutes, they copy only what's new or changed.

## The pieces, one by one

### Backfill: the first full copy
Before anything else, the sync copies **everything** SOCO holds in the three collections. It goes in ID order and writes down how far it got after every page, so if it stops halfway it carries on from there, with no duplicates.

On dev, 1 Oct 2026: 146 events, 8 orders and 12 served lists copied.

### Checkpoint: the bookmark
After that, every **5 minutes** (a setting, 1 to 15), it asks SOCO for rows whose *last changed* time (`updated_at`) is later than its **checkpoint**. The checkpoint is a bookmark: the latest change time it has already copied. It's kept in `ml_sync_state`.

> [!important] The bookmark only moves **after** the page it covers is written. If the sync crashes in between, the next run reads that page again. Nothing is skipped.

### The 2-minute overlap
Each read starts **2 minutes before** the bookmark, not exactly at it. Rows stamped at nearly the same moment, or written a little late, are caught on the next pass.

> [!example] Like rewinding a recording a few seconds before where you stopped, so you don't miss the start of a sentence.

Rows are read in order of change time, then ID. Two rows with exactly the same time on either side of a page break are both copied.

### Upsert: update, never skip
Each copy is filed under SOCO's own ID for the row. If the engine already holds it, the copy is **updated**, not skipped and not duplicated. That's called an **upsert** (update, or insert if new).

Why it matters: rows change after they're written. A like gets undone. An order moves from Placed to Delivered, then a return is requested. Skipping rows the engine already holds would miss all of that.

For orders, every new status is also written into the copy's **status history** with its time. Then the engine still knows an order reached Delivered, even if it later becomes Returned.

### Lag alert
If the copy is more than **15 minutes** behind on any collection, or a run fails, the engine **alerts** the service owner (Allen), who restarts it from the last bookmark. For now the alert is a special line in the [[Logs]].

### Daily reconciliation: the audit
Once a day, for the previous day, the sync checks its copies against SOCO, collection by collection:
- **IDs:** the same set of rows on both sides;
- **Field values:** for rows that changed, the important fields match exactly (undo time, order status, status log, return details, seen items).

**Equal counts alone don't pass.** 100 rows on each side could still be the wrong 100, or hold stale values. Every mismatch is logged and read again from SOCO. The result is saved in `ml_measurements`.

> [!example] Like a bank reconciliation. You don't just check that both statements have 40 lines; you tick off each line and check each amount.

This check matters beyond the engine. SOCO's migration (DB-16) drops its old event logs only after the reconciliation has passed **7 days in a row** → [[Event source switch]].

## Keeping copies for a year
SOCO deletes its events after 90 days. The engine's copies are kept **at least 365 days** from when the event really happened, under the engine's own expiry. An update never restarts that clock → [[Collections]], [[Indexes]].

## Where it stands (1 Oct 2026)
- **Built on dev (laptop).** The backfill works on today's data.
- **Waiting on SOCO's side:** the 5-minute read needs `updated_at` on every row (APP-12). On 1 Oct, none of the 146 events and none of the 12 served lists had it yet.
- **Waiting on the test server** to run the official check there.

## How this connects
- Built in → [[ENG-04 - Engine sync]]
- Reads SOCO's data with the read-only login → [[Platform Database]]
- Writes its copies into → [[Engine Database]] (`ml_events`, `ml_orders`, `ml_sync_state`)
- Its timings (5 minutes, 2-minute overlap, 15-minute alert) are in the → [[Settings file]]
- What's in the copies → [[Activity events]]
- What it replaced → [[Event source switch]]
