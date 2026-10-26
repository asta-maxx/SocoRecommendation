---
tags: [concept]
---
# Logs

A **log** is the engine's diary: a running list of everything it does, written as it happens.

## Our logs are "structured"
Each line isn't a free sentence. It's a small record with **labelled fields**, like a row in a spreadsheet:

| Field | Example |
|---|---|
| time | 2026-09-23 19:47:06.925 (always UTC) |
| level | INFO, or ERROR when something failed |
| what happened | "request", "job started", "job failed" |
| environment | dev, test or production |
| extra details | path `/health`, status 200, took 61.7 ms |

Because every line uses the same labels, tools can answer questions like *"how many requests failed today?"* or *"how long did last night's job take?"* without anyone reading line by line.

> [!example] Like a flight recorder. When something goes wrong, you replay the log to see exactly what happened and when.

## What gets logged
- **Every request:** what was asked, the answer code, and how long it took.
- **Every job:** a "started" line, then either "finished" (with its duration) or "failed" (with the error).

## How this connects
- Added in → [[ENG-02 - Service skeleton and settings]].
- Later, the weekly reports and speed checks (ENG-24, ENG-25) are built from what the engine measures and logs.
- Lives in the monitoring part of the → [[Recommendation Engine]].
