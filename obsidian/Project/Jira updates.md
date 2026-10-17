---
tags: [project, tool]
---
# Jira updates

**In one line:** a script that keeps my Jira tasks up to date from what's done here, and that can't touch anyone else's work.

## What it does
When a task's status changes here (for example ENG-16 becomes **Built**), it adds a short comment to my matching Jira task, and can move that task forward (for example to "In Review"). That's all it ever does.

## Matching my Jira tasks to the build list
My Jira tasks are worded differently from the build list, but they're the same work. The script reads each of my Jira tasks and finds the build-list task it's about, by the words they share (or by the ENG number, if a Jira task mentions one). It shows me every match and how sure it is. Only the matches it's sure of are accepted automatically, after I've seen them; the unclear ones I add myself or leave out.

## The safety rules
- It does nothing unless I say `--apply`.
- One Jira project only, and only tasks assigned to **Allen Matthew**: it checks each task again just before changing it.
- Only tasks that are mine in the build list too.
- It runs with my own token, so every change shows as mine.
- It can only add a comment or move a task forward. It can't create, edit, reassign, delete or move anything back.
- At most 20 changes a run, and every change is written down in a log.
- It never posts the same update twice.

## Connected (17 Oct 2026)
- Project **SRE** ("SOCO Recommendation Engine"), as me. It also holds 71 tasks of other people: the script never touches them.
- My Jira tasks use the older plan's names (RE-09 to RE-22), so I matched them to the build list by hand: only my sprint 3 and 4 sub-tasks. Sprints 1 and 2 are already Done and left alone.
- Built means In Progress in Jira (not Done until checked on the test server); Passed means Done.
- **First update, 17 Oct 2026 (approved by me):** 9 of my SRE tasks updated with a comment, a status move and the proof of the work attached (29 changes). RE-09 (filters) is Done; RE-10 to RE-13, RE-16, RE-18, RE-19 and RE-21 are In Progress until they're checked on the test server. Nothing else in Jira was touched.

## How to use it
1. Put my Jira email and token in `.env`; fill in the site and project in `settings/jira_sync.toml`.
2. `check` → copy my account id into the settings.
3. `discover` → look at the matches → `approve`.
4. `plan` to see what it would do, then `sync --apply`. `--every 30` keeps it going.

## How this connects
- Statuses come from the task notes → [[Task Board]].
- **Technical version:** `docs/engineering/JIRA_SYNC.md` in the repo.
