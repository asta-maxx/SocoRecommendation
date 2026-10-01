---
name: wave1a-pack-supersedes-earlier-docs
description: "docs/updated/ holds the current Wave 1A pack (v1.3 of 29 Sep 2026, received 1 Oct); precedence order; owner split; never edit it"
metadata:
  node_type: memory
  type: project
  originSessionId: 6c588693-28bf-4e69-8879-22dc21052fb3
  modified: 2026-10-01T07:33:34.582Z
---

`docs/updated/` holds the Wave 1A pack issued by Kala (Cristo Labs). The current versions, received on 1 Oct 2026 and committed as 357c18a:

- Build List **v1.3** (29 Sep), with a "Change register" sheet
- API Contract DS-017 **v2.5**
- Service Design Agreement **v1.6**
- Fraud Policy **v1.3**
- Capture Register **29 Sep**, which arrived twice; both copies are identical

These replaced the 22 Sep pack. Older material is superseded: SERVICE_CONTRACT.md, EVENT_CONTRACT.md, OPEN_QUESTIONS.md, `reference/`, and the 22 Sep pack, which is still in git history.

Precedence when documents disagree: Build List, then DS-017, then SDA, then Fraud Policy, then Capture Register.

Owner split: Allen owns the ENG-* items (the engine). Aravinth owns APP-* and DB-* (Flutter, SOCO_BE, the admin panel, the platform DB). Questions go to Kala in writing, quoting the item ID.

The user said the pack is final: never edit, move or rewrite files in `docs/updated/`. Use them as read-only reference. Leave the older docs in place too.

Everything must follow `docs/updated/`: plans, code, sequencing and module layout. Don't propose re-sequencing, deferring items, or adding things the pack doesn't state. Where the pack is silent, say so and keep the choice within the cited rule.

**Why:** v1.2/v1.3 changed decisions already built. POST /v1/events is retired in favour of the engine sync; there is no event source switch; 16 engine collections; module `sync` replaces `events`; incognito is purchase privacy only. Realignment notes are in `Tracing/REALIGNMENT_v1.3.md`.
**How to apply:** build to the pack's current versions. When the code and the pack disagree, the pack wins. When the user says the pack changed, diff the old (git) against the new and realign before continuing. See [[user-is-allen-engine-owner]].
