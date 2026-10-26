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
  Demos/
    How to demo a task.md      the general guide; lists every demo
    Demo - <ITEM>.md           one demo per task that has something to show
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
  - **Demo:** `[[Demo - <ITEM>]]`, once the demo exists
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

### Demo note: `obsidian/Demos/Demo - <ITEM>.md` (required once a task has anything to show)

A script for showing the task working to someone, live. `obsidian/Demos/Demo - ENG-02.md` is the model. Frontmatter: `tags: [demo]`, `task: <ITEM>`, `duration: about N minutes`.

Sections:

- **What this demo proves:** quote the item's *How to check it is done* line from the Build List. The demo acts that check out.
- **Setup:** what to start before the audience watches, and which terminal window does what.
- **Steps:** one `###` heading per step, each with:
  - **Say:** one plain sentence for the audience;
  - **Run:** the exact command, in a code block;
  - **They should see:** the output, abridged.
- **What you can't show yet:** a table of *part / why not / waiting on*. Be upfront.
- **Clean up:** what to stop or delete.
- **How this connects:** Proves → the task note; → [[How to demo a task]]; previous and next demo.

Rules for demo commands:

- **Run every command before writing it down.** Paste real output, trimmed, never invented.
- **Anything that writes uses a throwaway database** (`ML_MONGO_DB=reco_demo`) and a throwaway copy of any file it edits. Clean up by dropping `reco_demo`.
- **Never print a secret.** No `cat .env`, no connection strings. Use scripts that print hosts and database names only.
- **Prefer a script in `scripts/`** over a long inline command when a step would otherwise need more than a few lines of Python.

**The checklist script.** `scripts/run_checklist.sh` runs every finished task's check and prints PASS/FAIL per line. When a task is built, add a numbered section for it there (its Build List check plus any real-data check), and the matching rows to `obsidian/Demos/Checklist.md`. Run the whole script before reporting the task done.

When adding a demo, also:
- link it from the task note's **How this connects** (`**Demo:**`);
- add it to `Home.md` → *Demos*, to `How to demo a task` → *The demos*, and to the Task Board line (`· [[Demo - <ITEM>|demo]]`).

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
