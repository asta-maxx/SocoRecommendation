---
tags: [project, documents]
---
# The Pack: our rulebook

Five documents from Kala (Cristo Labs), dated **22 September 2026**. They're kept in `docs/updated/` in the repo.

> [!important] The pack is **final**. We never edit it. Everything we build follows it.

| Document | Plain meaning |
|---|---|
| **Build List** (spreadsheet) | The to-do list: every task, who does it, what it waits for, and how to prove it's done |
| **API Contract (DS-017)** | The "language" my engine and the app's backend use to talk to each other |
| **Service Design Agreement (SDA)** | How my engine is built on the inside |
| **Fraud and Abuse Policy** | What counts as cheating, and what happens about it |
| **Capture Register** | A dictionary of every piece of data the app records |

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
