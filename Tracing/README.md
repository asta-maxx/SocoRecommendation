# Tracing

The record of what has actually been done, kept against the demo task list.

## The files

**`TASK_LOG.md`** — the one that matters. A status board for all 22 tasks in
SOCO-REC-DS-015 v3, the open contradictions, and a dated log of every change.

**`RUNS.md`** — what each engine run produced. Numbers, not prose: how many
scores, what was dropped and why, how long it took, and what the data checks said
afterwards.

## The rule

Every time something is built, decided, corrected or discovered, it goes in
`TASK_LOG.md` before moving on. A change that is not recorded is
indistinguishable from a change that never happened — and on a four-day build
with two people, the thing nobody wrote down is the thing that gets rebuilt.

Three kinds of entry earn their place:

- **A task moved.** Which one, what "done" means for it, and the evidence.
- **A decision was taken.** Who ruled, on what, and what it changed.
- **A contradiction was found.** Both sides of it, which document each came from,
  and what is blocked until it is settled.

Contradictions stay in the table at the top until they are ruled on. They are not
worked around in code: a workaround built in is invisible, and the point of
writing it down is that somebody rules on it instead.

## What this is not

Not a substitute for the specification documents in `reference/`, which are the
authority. This records what was done about them.
