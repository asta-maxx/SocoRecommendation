# Jira updates for Allen's tasks (`scripts/jira_sync.py`)

Not a Build List item: a tool (Allen, 17 Oct 2026) that keeps **Allen Matthew's** Jira issues in step with the repo, and is built so it cannot touch anything else.

## What it does

From each task note in `obsidian/Tasks/` (frontmatter `task`, `status`, `owner`; the "In one line" and the status callout) it adds one comment to the matching Jira issue when that task's status or summary changes, and, if configured, moves the issue forward to the Jira status that corresponds (for example Built → In Review, Passed → Done). Nothing else.

## Matching (the Jira tasks are worded differently)

`discover` reads Allen's issues in the project (summary and description) and scores each against every one of Allen's Build List tasks (model, name, what to build) plus the vault note's title. An ENG id written in the issue wins outright (score 1). Otherwise: a TF-IDF cosine over the words (stop words removed), 0 to 1. **Confident** = score ≥ 0.35 and at least 0.08 ahead of the next task. One task may map to several issues. `discover` writes `Tracing/jira/proposed_matches.json` and prints every match with its score and runner-up; `approve` copies only the confident ones into `settings/jira_sync.toml [issues]` (never changing a line already there). Unclear ones are added by hand or left out.

## Guardrails

| # | Rule | Where |
|---|---|---|
| 1 | Dry run unless `sync --apply` | `main`, `Jira.request` |
| 2 | One project: every issue key must start with `project_key`, and the issue's own project must be it | `Config.validate`, `Jira._allowed`, `Jira.verify_issue` |
| 3 | Only issues in `[issues]`, written there by `approve` (confident matches) or by Allen | `eligible_tasks` |
| 4 | Allen's task twice over: owner Allen in the Build List v1.4 and in the vault note | `eligible_tasks` |
| 5 | The issue is re-read just before each write; assignee must be Allen's accountId and display name | `Jira.verify_issue` |
| 6 | The API token must be Allen's (`/myself`), so every change is made as Allen | `Jira.check_identity` |
| 7 | One function sends every request; it allows only: GET myself, the project, the search (project and Allen as assignee), one issue, its comments, its transitions; POST a comment, POST a transition, on an issue verified in this run | `Jira._allowed`, `Jira.request` |
| 8 | Transitions only forward along `jira_status_order` | `forward` |
| 9 | At most `max_writes_per_run` (default 20, 1 to 50) writes per run; a failed write stops the run | `Jira.request` |
| 10 | Every write and every refusal appended to `Tracing/jira/audit.jsonl` (git-ignored) | `Jira.audit` |
| 11 | A comment carries `[reco-sync ENG-NN <fingerprint>]`; the same update is never posted twice | `already_posted` |

Never: create, edit fields, assign, delete, link, bulk-change, or touch another project or another person's issue. No Claude attribution in comments. Credentials (`JIRA_EMAIL`, `JIRA_API_TOKEN`) come from `.env` and are never printed.

## Setting it up (once)

1. Create an API token as Allen (https://id.atlassian.com/manage-profile/security/api-tokens); put `JIRA_EMAIL` and `JIRA_API_TOKEN` in `.env`.
2. In `settings/jira_sync.toml` fill `base_url` and `project_key`, then run `python scripts/jira_sync.py check`: it prints the token's user and accountId and the project. Copy the accountId into `allen_account_id`.
3. Set `jira_status_order` to the project's workflow, and `[transitions]` if issues should move (leave it empty to only comment).
4. `python scripts/jira_sync.py discover`, read the list, then `approve`; add any others by hand.
5. `python scripts/jira_sync.py plan` (dry run), then `sync --apply`. To keep it going: `sync --apply --every 30`.

## Tests

`tests/test_jira_sync.py`, 32, against a pretend Jira: bad settings refuse (wrong site, no project, no accountId, another project's key, two tasks on one issue, an unknown status, too many writes); the shipped settings file refuses until filled in; nine forbidden requests never leave (delete, edit, create, assign, another project, links, bulk); no write in a dry run or to an unverified issue; a token that is not Allen's stops the run; an issue assigned to someone else, or moved to another project, is skipped and logged; a task the Build List gives to someone else is refused; one comment and one forward move per issue, the comment marked and without Claude attribution; never posted twice; never moved backwards; the write cap; a dry run writes nothing; reworded issues match their tasks; an ENG id wins; an unclear issue is not confident; `approve` copies only confident matches. Results, 17 Oct 2026: 32 passed.

## 17 Oct 2026: connected to SRE, mapped by hand

- `check`: the token is Allen Matthew's; project **SRE** ("SOCO Recommendation Engine") on `https://mysoco.atlassian.net`. SRE also holds 71 issues assigned to other people: none is in `[issues]`, and guardrail 5 would skip any that were.
- `discover`: 33 issues of Allen's (sprint stories SRE-10, 42, 71, 98 and their sub-tasks), named after the earlier plan (RE-00a to RE-22, PT-10). No match was confident: the wording differs from the Build List v1.4. So the mapping is **Jira issue → ENG task(s)**, made by hand: sprint 3 and 4 sub-tasks only (SRE-72 to 79, 99 to 104); sprints 1 and 2 are already Done and the sprint stories are not listed. An issue covering several tasks takes the least advanced status.
- SRE's workflow: To Do → In Progress → Done. Built → In Progress (its acceptance check has not run on the test server yet); Passed → Done.
- `[notes]` adds one explaining line to an issue's comment (SRE-100: reason_code is null in Wave 1A).
- `plan` shows each comment in full. Nothing has been written to Jira; `sync --apply` waits for Allen's approval.
- Tests: 42 passed (searches limited to the project; editing or deleting comments refused; an issue refused whole when any of its tasks is not Allen's; least-advanced status; Passed to Done; notes; `approve` writes under `[issues]` only).

