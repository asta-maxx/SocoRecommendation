---
tags: [concept, database]
---
# Indexes

An **index** is like the **index at the back of a book**. Instead of reading every page to find "request_id 3f1c…", the database jumps straight to it.

Without indexes, lookups get slower as the data grows. With them, they stay fast.

## The ones added so far
Every document already has one built-in, unique index: its `_id`. The engine files each copy of a SOCO row under **SOCO's own `_id` for that row**, so the same row can never be saved twice, however often the sync reads it → [[Engine sync]].

On `ml_events`:

| Index | What it's for |
|---|---|
| user + time | "Show me everything this user did, newest first" |
| `request_id` | "Show me everything that happened to this one list I served" |
| event code + time | "Show me every like (E9) this week" |
| `retention` (**auto-delete**) | Deletes a copy 365 days after the event really happened |

On `ml_orders`: buyer + time, the basket (`checkout_id`), and the same 365-day `retention`.

On `ml_config_changes`: the settings version, **unique**, so each settings change is written down once.

> [!note] Changed in pack v1.3. The 22 Sep design had a unique `event_id` index and **no** auto-delete on `ml_events`. Now copies are keyed on SOCO's `_id`, so the `event_id` index was dropped. The auto-delete counts from the event's **original** time, so a copy is always kept at least a year, while SOCO deletes its own rows after 90 days.

## How this connects
- They sit on → [[Collections]].
- They were added in → [[ENG-01 - Engine home and databases]].
- Filing copies under SOCO's `_id` is what lets the → [[Engine sync]] read a row twice without duplicating it ([[ENG-04 - Engine sync]]).
