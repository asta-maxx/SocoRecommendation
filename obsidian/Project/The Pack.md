---
tags: [project, documents]
---
# The Pack: our rulebook

Five documents from Kala (Cristo Labs). The current set is **version 1.4, dated 14 October 2026**, received 15 Oct. It replaced v1.3 (29 Sep) and the earlier sets of 22 and 28 September. They're kept in `docs/updated/` in the repo, and **that folder is the only reference**: whatever is in it is the current pack.

> [!note] What changed in v1.4 (14 Oct)
> SOCO's app team sent a reference and answers, and Kala checked the real database. Nothing asks the app to change; the engine adapts, in a new task of mine: [[ENG-30 - Adapting to the October platform facts]]. The main facts: there is **no "Return Requested" status** (a request is its own record, and "Returned" is the only return); an order's history is read as events from its text; a person and their stores count as one person; reposts lead back to the original; commission settings come from a new collection. ENG-01 to ENG-04 are now marked Built in the pack. **DB-02 is removed**: the engine keeps the read-only login it has.

> [!note] The biggest change in v1.3: the engine no longer **receives** events from the app. It **copies** SOCO's own activity log, orders and served lists → [[Engine sync]]. ENG-01 to ENG-04 were realigned to it on 1 Oct 2026.

> [!important] The pack is **final**. We never edit it. Everything we build follows it.

| Document | Plain meaning |
|---|---|
| **Build List v1.4** (spreadsheet) | The to-do list: every task, who does it, what it waits for, and how to prove it's done |
| **API Contract (DS-017) v2.6** | The "language" my engine and the app's backend use to talk to each other |
| **Service Design Agreement (SDA) v1.7** | How my engine is built on the inside |
| **Fraud and Abuse Policy v1.4** | What counts as cheating, and what happens about it |
| **Capture Register** (14 Oct) | A dictionary of every piece of data the app records |

**If two documents disagree**, the one higher in the table wins: the Build List first, the Capture Register last.

**It replaced everything older.** The earlier contracts in the repo (`SERVICE_CONTRACT.md`, `EVENT_CONTRACT.md` and the rest) are kept, but we no longer build to them.

## Codes you'll see
- **ENG-01, ENG-02…:** my tasks (**ENG**ine).
- **APP-… / DB-…:** Aravinth's tasks (the app and the database).
- **SD-…:** decisions in the Service Design Agreement.
- **AS-…:** assumptions. Things taken as true until someone says otherwise.

## How this connects
- It describes → [[Wave 1A]].
- It was written by Kala for Allen and Aravinth → [[People]].
- Its Build List sets the order of work → [[Build Steps]].
- It overrides the older demo documents → [[Before Wave 1A - the M1 demo]].
