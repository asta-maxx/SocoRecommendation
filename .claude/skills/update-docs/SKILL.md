---
name: update-docs
description: Update both documentation sets for SOCO engine work. The technical doc goes in docs/engineering/, the plain-language notes in the Obsidian vault in obsidian/. Use after finishing or changing any ENG item, recording a decision, or learning a fact that changes what the docs say. Also use when the user asks to "update the docs" or "document this".
---

# Update the technical and plain-language docs

Every piece of engine work is documented **twice**:

| Where | For | Style |
|---|---|---|
| `docs/engineering/<ITEM>.md` | Engineers: Allen, Aravinth, whoever maintains this | Precise and technical: spec references, code names, commands, results |
| `obsidian/` (Obsidian vault) | Allen, reading quickly | Plain words, comparisons, and how each idea connects to earlier ones |

Both are updated in the **same turn** as the work. Neither is optional.

## Never touch

- `docs/updated/`: the Wave 1A pack. It is final, read-only reference, and everything follows it.
- Older docs (`SERVICE_CONTRACT.md`, `EVENT_CONTRACT.md`, `OPEN_QUESTIONS.md`, `HANDOFF.md`, `docs/*.html/pdf`, `reference/`): superseded. Leave them as they are.
- User edits in the vault: Obsidian reformats tables and the user edits notes. Read a note before editing it and keep its current state; don't revert formatting.

## 1. Technical doc: `docs/engineering/<ITEM>.md`

One file per build-list item, named by its ID (`ENG-02.md`). `docs/engineering/ENG-01.md` is the model to follow. Sections, in order:

1. **Header table:** owner, step, waits on, needed by, status (the build list's values: To build, In progress, Waiting, Built, Testing, Failed, Passed), and spec references (build list row, SD-nn, AS-nn, E/F/X codes).
2. **What the item requires:** the build list row, including its *How to check it is done*.
3. **What was built:** one subsection per subtask, numbered the same way as the Obsidian note (1, 2… for the Build List parts, A, B… for extras), with its status. For each: which file, function or setting; how it behaves; why (cite the spec).
4. **Configuration reference:** any new or changed settings or environment variables.
5. **Environments:** only if the item changes where or how something runs.
6. **Tests:** what they cover, how to run them, and the **actual result with date** (counts of passed, failed and skipped). Never claim a result that wasn't run.
7. **Runbook:** how to operate or re-check it.
8. **Open:** what's left and what each piece waits on.
9. **Files changed:** a table.

Rules:

- Every behaviour cites where it comes from in the pack.
- Where the pack is silent and a choice was made, say so, and name the rule the choice must satisfy.
- Record decisions with their date.
- Never paste secrets or connection strings. Show hosts and database names only.

## 2. Obsidian vault: `obsidian/`

Layout:

```
obsidian/
  Home.md                      start page, links everything
  Project/                     Wave 1A, The Pack, People, Build Steps, Before Wave 1A - the M1 demo
  Concepts/                    one idea per note (Engine Database, Collections, Environments…)
  Tasks/
    Task Board.md              every ENG item with its status
    <ITEM> - <plain title>.md  one note per task
```

### Task note: `obsidian/Tasks/<ITEM> - <plain title>.md`

Frontmatter:

```yaml
---
tags: [task, step-<n>]
task: <ITEM>
status: <build-list status>
owner: Allen
---
```

Sections:

- **In one line:** what the task does, as you'd tell a friend.
- **Why this task:** where it sits in the build steps, and what depends on it.
- **What came before:** the earlier state, with links to the notes that explain it.
- **Subtasks, one by one:** required. See below.
- **Result (date):** what now works, stated plainly, including test counts.
- **Decided:** any decisions, with dates, if there were some.
- **Still to do:** a table of *what* and *waiting on*.
- **How this connects:** always last. Use these four lines:
  - **Before it:** `[[…]]`
  - **Built on:** `[[…]]`
  - **Next:** `[[<next item> - <title>]]`, with one line on what it adds.
  - **Technical version:** `docs/engineering/<ITEM>.md`

### Subtasks, one by one (required in every task note)

Split the task into its subtasks and explain **each one** simply.

- **Numbered subtasks** (1, 2, 3…) are the parts of the item's Build List row, in its own order. Include the ones not done yet.
- **Lettered extras** (A, B, C…) are anything we added beyond the row, such as a safety check or a helper script.

Each subtask is a `###` heading with a status mark: ✅ done, ⏳ waiting (say on what), 🔨 in progress, ❌ failed. Where it differs by environment, say so: "✅ laptop / ⏳ servers". Under it, four bullets:

- **What it asks:** the requirement, as you'd tell a friend. Extras skip this bullet.
- **What we did:** concretely, in plain words: what now happens, and when. A file or setting name may appear only if you explain it in the same sentence.
- **Why it matters:** the problem it prevents, or what it enables later.
- **Status:** done, or what it's waiting on. Include numbers where there are some ("11 of 12 created").

End the subtask with a link to the concept note it relies on (`→ [[Concept]]`).

While a task is in progress, update each subtask as it moves. Don't wait for the whole task to finish. `obsidian/Tasks/ENG-01 - Engine home and databases.md` is the model.

### Plain-language style

- Explain every technical word the first time it appears in a note, or link to the Concept note that does.
- Use comparisons where they help (drawers for collections, a book's index for indexes, overnight prep in a kitchen for nightly jobs).
- Short sentences. Tables for comparisons. Callouts (`> [!note]`, `> [!tip]`, `> [!warning]`, `> [!example]`) for asides.
- Say **why** each link matters, not just that it exists: "Its 12 collections were created in → [[ENG-01 - …]]".

### Keep the rest of the vault in step

- **New idea** introduced by the work → add `Concepts/<Idea>.md`. It ends with its own **How this connects** section. Link it from `Home.md` if it's a main piece.
- **Changed fact** in an existing note (a status, a location, a decision) → update that note too. Grep the vault for the old fact.
- **`Tasks/Task Board.md`** → tick or retitle the item, and link its note.
- **The previous task note's "Next" link** now resolves. Check it still describes what was done.

## 3. Check before finishing

Run the link checker. Every `[[link]]` must resolve to a note, except the single deliberate "Next" link to a task not yet written.

```bash
python3 .claude/skills/update-docs/check_links.py
```

Then tell the user, in one or two lines, which technical doc and which vault notes changed.
