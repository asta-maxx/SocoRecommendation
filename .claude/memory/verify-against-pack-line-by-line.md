---
name: verify-against-pack-line-by-line
description: "Allen expects claims of \"follows the pack\" to be proven by a line-by-line check of each Build List row against code and tests"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 6c588693-28bf-4e69-8879-22dc21052fb3
  modified: 2026-10-01T12:35:50.287Z
---

Before saying a task is done or "follows docs/updated", split its Build List v1.3 row (and the DS-017 / SDA / Settings sheet / Capture Register entries it cites) into single requirements and check each against code and a test. Answer open questions from the pack first (by precedence) and from SOCO's data before asking anyone; only truly unanswerable ones go to Aravinth/Kala.

**Why:** on 1 Oct 2026 Allen asked "are you 100% sure we followed /docs/updated?" — an independent audit then found ~30 small gaps (driver retries vs SD-26, Fixed-for-Wave-1A settings editable, F71/F72 field names, E-02 mute window…). He also pushed back on a long question list: 15 of 17 were answerable from the pack or the data.

**How to apply:** run a per-row audit (read-only reviewers work well) when finishing each task; record silent-pack choices explicitly; keep the question list to what truly needs a person. See [[wave1a-pack-supersedes-earlier-docs]].
