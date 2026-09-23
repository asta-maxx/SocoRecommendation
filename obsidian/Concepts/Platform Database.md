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

## A gotcha
Some things are stored inconsistently. For example, some IDs are saved as text and others in MongoDB's own ID format. My engine has to treat them the same, or it silently finds nothing.

## How this connects
- Its opposite is → [[Engine Database]].
- Keeping the two apart was part of → [[ENG-01 - Engine home and databases]].
- The login to it is a secret → [[Secrets and passwords]].
