---
tags: [concept]
---
# Activity events

An **event** is one small record of something a shopper did: saw a post, tapped it, liked it, added a product to the cart, bought it, said "not interested". Together they're how the engine learns what each person is into.

## Where events live now (pack v1.3)
Nobody **sends** events to the engine any more. The engine's old front door for them (`POST /v1/events`) is retired (API Contract v2.5, section 7).

```
Shopper's phone → SOCO_BE → postevents (SOCO's activity log)
                                 │
                 engine sync, every 5 minutes (read-only)
                                 ↓
                       ml_events (the engine's copy)
```

1. The app writes each event to SOCO's own activity log, `postevents`, in the [[Platform Database]]. → [[SOCO_BE]]
2. The **engine sync** reads that log every 5 minutes and copies what's new or changed into the engine's `ml_events` drawer → [[Engine sync]], [[Collections]].
3. Every model reads events only from that copy, never from SOCO's log directly → [[ENG-03 - Reading SOCO's data correctly]].

> [!example] Like a newspaper archive. The newsagent (SOCO) throws papers out after 90 days. The library (the engine) photocopies each new paper as it arrives, files it under the paper's own number, and keeps its copy for a year.

## What a copy keeps
- **SOCO's own ID for the row** (its `_id`). The copy is filed under it, so reading the same row twice just updates the copy; it never makes a second one.
- **Where it came from:** which SOCO collection, and the row's ID.
- **When it really happened** (`created_at`), and when it last changed (`updated_at`).
- **Undo details:** if a like was later undone, the copy says so.
- **Its E code:** SOCO's 26 native event types are translated into the pack's event codes, following the Capture Register's sheet 4. For example, `click` becomes E3, `like` E9, `add_to_cart` E4, `purchase` E5, `feedback` E13. A few types (such as `video_play`) have no code: they're copied and kept, but no model scores them.

The engine also writes one kind of event itself: **E1**, the record of each list it served.

## How long they're kept
| Who | Keeps events for |
|---|---|
| SOCO's `postevents` | 90 days, then deleted |
| The engine's `ml_events` | **at least 365 days**, counted from when the event really happened |

Updating a copy never restarts its clock. SOCO deleting its row never deletes the engine's copy.

> [!warning] Because SOCO deletes after 90 days, the engine's first full copy has to happen before the oldest rows reach that age. It was done on dev on 1 Oct 2026.

## How this connects
- How the copying works → [[Engine sync]], built in [[ENG-04 - Engine sync]]
- Rules for reading them (one source, E codes, page visits) → [[ENG-03 - Reading SOCO's data correctly]]
- They're stored in the `ml_events` drawer → [[Collections]]
- The old plan of switching between logs is gone → [[Event source switch]]
