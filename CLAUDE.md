# SOCO recommendation engine

## Source of truth

`docs/updated/` holds the Wave 1A pack. It is final: never edit, move or rewrite
it. All code, plans and docs follow it. If its documents disagree, apply them in
this order: Build List, then DS-017 API Contract, then Service Design Agreement,
then Fraud Policy, then Capture Register.

## Always update both docs

After finishing or changing any build-list item, recording a decision, or
learning a fact that changes what the docs say, update **both** of these in the
same turn:

1. **Technical:** `docs/engineering/<ITEM>.md`
2. **Plain language:** the Obsidian vault in `obsidian/` (the task note, any
   affected concept notes, and `Tasks/Task Board.md`)

Follow the `update-docs` skill (`.claude/skills/update-docs/SKILL.md`) for the
layout, templates and style. Run its link check before reporting the work as
done. Work isn't finished until both are updated.

## Picking up the work

Start with `Tracing/CONTINUE_ON_ANOTHER_LAPTOP.md` (setup, state, open items, next
steps). The pack's text, for reading and searching, is in `Tracing/pack_text/`
(regenerate with `python3 scripts/extract_pack.py`). Before calling a task done,
check its Build List row line by line against the code and tests
(`Tracing/AUDIT_2026-10-01.md` shows how).
