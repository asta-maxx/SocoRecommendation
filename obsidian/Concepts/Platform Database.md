---
tags: [concept, database]
---
# Platform Database

**SOCO's own database.** It holds users, posts, products, orders, likes, follows and more.

- It belongs to SOCO, and Aravinth looks after it (→ [[People]]).
- My engine may **only read** it, never change it.
- For that, my engine uses a special **read-only login**. Checked on 24 Sep: it can read but can't change anything. Aravinth will change its password later (task **DB-02**).

> [!example] Like a library book: I can read it and take notes, but never write in it. My notes go in my own notebook → [[Engine Database]].

## Where it is
On SOCO's cluster in [[MongoDB Atlas]] (`nex-dev.cob9whd`), in a database called `soco`.

## How the engine reads it
Never directly. Everything goes through clean "records" that apply the pack's rules: every ID the same way, the right field for each fact, categories matched to the 23, and each kind of data from one place only. → [[ENG-03 - Reading SOCO's data correctly]]

> [!warning] Checked on 29 Sep 2026: none of SOCO's 2,011 products sits in one of the pack's 23 categories yet. Aravinth's DB-07 fixes that.

## A gotcha
Some things are stored inconsistently. For example, some IDs are saved as text and others in MongoDB's own ID format. My engine has to treat them the same, or it silently finds nothing.

## How this connects
- Its opposite is → [[Engine Database]].
- Keeping the two apart was part of → [[ENG-01 - Engine home and databases]].
- The login to it is a secret → [[Secrets and passwords]].
- Its activity log (`postevents`), orders and served lists are copied into the engine every 5 minutes → [[Engine sync]]. The old plan to switch between event logs is retired → [[Event source switch]].
