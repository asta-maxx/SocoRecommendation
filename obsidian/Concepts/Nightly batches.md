---
tags: [concept]
---
# Nightly batches

At **2 AM India time** every night (a setting), the engine recomputes its scores (interest, product ranking, promoter scores…). Last of all, the engine sync's daily audit runs → [[Engine sync]]. Each job writes a **whole new set** of scores, called a **batch**. Requests keep reading the old batch until the new one is finished.

> [!example] Like a restaurant printing tomorrow's menu overnight. Diners keep using tonight's menu. The new menus go on the tables only once they're all printed. A half-printed menu never reaches a table.

## The rules
1. **Write the whole batch first.** Every score row carries the batch's ID (`job_run_id`).
2. **Then mark it current.** Only once every row is written does the batch become the one requests read.
3. **A failed job changes nothing.** The previous batch stays in use and the failure is recorded.
4. **A killed job changes nothing either.** If the job is stopped dead, for example the server restarts, it can't record anything. Its record still says "running". The next run of that job marks it as failed ("abandoned"), and its half-written rows are cleared.
5. **One night's grace.** The batch that was just replaced is kept until the next night, so a request already reading it can finish. Older ones are deleted.

## The run diary: `ml_job_runs`
Every run gets a line: which job and method, the data window, how many rows, how long it took, and whether it succeeded or failed (with the error). It also says which batch is **current**.

## What every score row says about itself
What is scored, the slot, the method, the model and settings versions, the score, its confidence (where the method has one), the data window, when it was computed, and its batch ID. A number with no history can't be checked, so every row carries this.

## How this connects
- Built in → [[ENG-07 - Nightly jobs]].
- The jobs compute **both** methods of each slot → [[Two methods per slot]].
- The run diary is one of the engine's drawers → [[Collections]].
- Failures alert the service owner, like the sync's lag alert → [[Engine sync]], [[Logs]].
