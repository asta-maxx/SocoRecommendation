---
tags: [concept, database]
---
# Indexes

An **index** is like the **index at the back of a book**. Instead of reading every page to find "request_id 3f1c…", the database jumps straight to it.

Without indexes, lookups get slower as the data grows. With them, they stay fast.

## The ones added so far (on `ml_events`)
| Index | What it's for |
|---|---|
| `event_id` (**unique**) | Each event has an ID. "Unique" means the same event can never be saved twice, even if the app sends it again after a network hiccup |
| user + time | "Show me everything this user did, newest first" |
| `request_id` | "Show me everything that happened to this one list I served" |

> [!note] There's deliberately **no auto-delete** on `ml_events`. Events must be kept for at least a year.

## How this connects
- They sit on → [[Collections]].
- These three were added in → [[ENG-01 - Engine home and databases]].
- The "unique" one matters most for task ENG-04 (receiving events).
