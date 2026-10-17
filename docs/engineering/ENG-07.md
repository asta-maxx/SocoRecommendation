# ENG-07: Daily refresh jobs (nightly batches, ml_job_runs, the 2 AM IST scheduler)

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days) |
| **Waits on** | ENG-02 (built: jobs mode, settings file, structured logs) |
| **Needed by** | ENG-09, ENG-10, ENG-14, ENG-16, ENG-17, ENG-18, ENG-21, ENG-25 |
| **Status** | **Built** (1 Oct 2026, on dev) for the framework and M1. The batch rule, `ml_job_runs`, the score-row fields and the scheduler are done, and the Build List check passes with a real `SIGKILL`. Audit fixes the same day (`2b585af`): a failed run records `rows_written: 0`; a watcher in the API alerts on runs stuck `running` over 2 hours (`job_stuck`); `refresh_cadence` and `refresh_time_ist` are locked (fixed for Wave 1A). The other nightly jobs (M2 method two, M5, M8 and its monthly copy, M6, the fraud rules) arrive with their own items and join the same framework. Becomes Passed when the check runs on **test** (Definitions: every check runs on test) |
| **Spec** | Build List v1.3 ENG-07 (and Settings sheet "M1 interest / Refresh"); SDA v1.6 SD-17, SD-19, SD-20, SD-21, SD-22; ENG-02 items 1, 3, 6 (jobs mode, settings read at the start of a job, structured job logs); ENG-04 item 7 (alerts) and item 8 (daily reconciliation) |

---

## 1. What the item requires

The Build List v1.3 row, *What to build*, verbatim:

> A scheduler runs at 2 AM IST daily:
> - M1 (both methods);
> - M2 method two candidates;
> - M5 (both methods);
> - M8 (both methods, plus the monthly copy on the 1st);
> - M6;
> - the fraud rules.
>
> Each job writes a complete new batch and only then marks it current. A request never reads a half-written batch. A failed job leaves the previous batch in use.
>
> Every run is recorded in ml_job_runs: job, data window, rows written, duration, success or failure, and job_run_id.
>
> Every score row carries: what is scored, slot, method, model_version, config_version, score, confidence (where the method has one), data window, computed_at and job_run_id.

*How to check it is done*:

> Kill a job halfway: requests keep reading the previous batch. ml_job_runs shows the failure.

The same rules in the SDA v1.6:

- **SD-17:** "A request does no model calculation. It only reads stored scores … All model calculation happens in the scheduled jobs."
- **SD-19:** the score-row fields (as above).
- **SD-20:** "A refresh writes a complete new batch and only then marks it as current. A request never reads a half-written batch. If a refresh fails, the previous batch stays in use."
- **SD-21:** "Every job run is recorded in ml_job_runs: what ran, over what window, rows written, and whether it succeeded."
- **SD-22:** "Refreshes run daily at 2 AM IST for the three two-method slots, M2 method two candidates, M6 and the fraud rules. The engine sync runs every 5 minutes, and the daily reconciliation runs after the 2 AM refreshes. The times are settings."

Settings sheet: *M1 interest | Refresh | daily, 2 AM IST | ENG-07 | hourly to weekly | Fixed for Wave 1A.*

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–6 are the Build List's parts, A–C are extras.
Commit `008390a` (1 Oct 2026), plus the scheduler change of the same day (run time
read from the settings file, reconciliation last) and commit `7442bda` (every
non-batch job run in `ml_job_runs`; one interest method failing no longer stops the
other).

### 1. The scheduler at 2 AM IST: done (dev); how it runs on the servers is open

`reco/jobs/scheduler.py`:

- **`next_run(now, at="02:00") -> datetime`**: the next `at` (HH:MM, IST) strictly after `now`, returned in UTC. IST is a fixed `+05:30` (India has no daylight saving), so there is no DST edge.
- **The time is a setting (SD-22: "The times are settings").** `run_forever` re-reads the settings file (`config_sync.reload`) before each wait and passes `live.current().interest.refresh_time_ist` (`"02:00"`).
  - **Fix, 1 Oct 2026 (audit, `2b585af`): the time and the cadence are locked for Wave 1A.** The Settings sheet row reads *"M1 interest | Refresh | daily, 2 AM IST | ENG-07 | hourly to weekly | Fixed for Wave 1A"*, and the sheet says a value changes only where its *When it changes* column allows. So `reco/config/tunables.py` now types them `refresh_time_ist: Literal["02:00"]` and `refresh_cadence: Literal["daily"]`: a settings file with another value is rejected (the engine keeps the settings in force, as for any invalid file, ENG-02). They stay settings, as SD-22 asks, but with one allowed value. This closes the open decision in §7.
- **`run_forever(settings, jobs)`**: loop: reload settings, compute the next run, log `next nightly run` with `due`, sleep, reload settings again (a job reads the settings once, at its start: ENG-02 item 3), then `run_nightly`.
- **`run_nightly(settings, jobs) -> list[str]`**: runs every name in `NIGHTLY` **one after another**. A job that raises is recorded, alerted with `alert("job_failed", …, job=, error=)` (`reco/monitoring/alerts.py`: a CRITICAL log line with `"alert": true` and owner Allen, as in ENG-04 item 7), and the **next job still runs**. Returns the names that failed.

Entry points (`reco/jobs/__main__.py`, ENG-02's jobs mode):

```bash
.venv/bin/python -m reco.jobs nightly      # every nightly job once, now; exit 1 if any failed
.venv/bin/python -m reco.jobs scheduler    # wait for the set time (02:00 IST), run them, repeat
```

`nightly` raises `RuntimeError("nightly jobs failed: …")` after the whole list has
run, so the process exits 1 and a cron wrapper sees the failure.

**Not decided (1 Oct 2026):** on the servers, the nightly run can be either the
`scheduler` loop as a long-running process, or cron calling `nightly` at 02:00 IST.
Both use the same code. The choice waits on the servers (ENG-01 item 3, SD-03).
Whichever is chosen, **only one** may run per environment: see §7, "overlapping runs".

### 2. The nightly job list: M1 and the reconciliation now; the rest wait on their items

`scheduler.NIGHTLY` holds the job names, in run order. Each item adds its job when it is built:

| Build List job | Job name | Status | Brought by |
|---|---|---|---|
| M1, both methods | `interest` | **Running** as batches (both methods) | here; since 14 Oct its input is the engine copies (ENG-10) |
| M2 method two candidates | `similar_posts` | **Built** 16 Oct, in `NIGHTLY` after `interest` (writes `ml_user_candidates`) | ENG-14 |
| M5, both methods | `product_ranking` | **Built** 17 Oct, in `NIGHTLY` after `promoter`; one batch per method into `ml_product_scores` | ENG-17 |
| M8, both methods, monthly copy on the 1st | `promoter` | **Built** 17 Oct, in `NIGHTLY` after `similar_posts`; one batch per method; the monthly copy runs inside the job on the 1st | ENG-16 |
| M6 | | waiting | ENG-18 |
| The fraud rules | | waiting | ENG-21 |
| ENG-29 item 1: the daily unmapped-category check (not in this row; it joined the list) | `category_check` | **Running** (since `f7c82f3`, 1 Oct) | ENG-29 |
| The engine sync's daily reconciliation (SD-22: "after the 2 AM refreshes") | `reconcile_sync` | **Running**, always **last** | ENG-04 item 8 |

So today `NIGHTLY = ("interest", "category_check", "reconcile_sync")` (re-checked
1 Oct 2026). A test asserts the reconciliation stays last.

**The monthly copy of M8 on the 1st** is not scheduled yet: the scheduler has no
monthly trigger. It arrives with M8 (ENG-16), which decides how the run on the 1st
also writes the copy.

**M1's input today.** `interest` still reads through the older platform readers
(`reco/platform/readers.py`), not the engine's copies. On dev on 1 Oct it read 146
events for 5 users and dropped 113 (58 unresolved category, 55 unknown type).
ENG-10 moves it onto `ml_events` with the v1.3 sources and weights.

### 3. A complete new batch, and only then current: done

`reco/jobs/batches.py`, **`run_batch(settings, *, job, slot, method, collection, data_window, work)`**:

1. Records any earlier run of the same `job` + `method` still marked `running` as failed (item A).
2. Creates a new `ml_job_runs` record with `_id = job_run_id` (a UUID4), `outcome: "running"`, `is_current: false`.
3. Calls `work(job_run_id)`. The job writes **every** row of its batch carrying that `job_run_id`, beside the current batch (never over it), and returns the row count.
4. On success: sets `outcome: "succeeded"`, `rows_written`, `finished_at`, `duration_seconds`; **then** `writers.mark_current(job, method, job_run_id)`.
5. Clears old batches: `writers.delete_batches_except(collection, method, keep=[new, replaced])`.

**How a request reads only the current batch.** `writers.current_job_run_id(job, method)`
returns the `_id` of the `ml_job_runs` record with `is_current: true` (latest
`finished_at` first). `writers.read_user_scores`, the score read path used by
`reco/fallback/read_path.get_profile`, now filters on that `job_run_id`. The demo
endpoints in `reco/api/profiles.py` (`users`, `overview`) do the same. A row of a
batch that is not yet current, or never will be, is invisible to them.

**The switch.** `mark_current` sets the new record `is_current: true` first, then
unsets the others. In between, two records are current and the reader picks the
later `finished_at`, the new one. At every moment some complete batch is current.

**Keeping the replaced batch one more night (our choice, 1 Oct 2026).** The pack
says when a batch becomes current, not when an old one may go. A request that
looked up the current `job_run_id` just before the switch may still be reading it,
so the batch it replaced is kept until the next success; older ones are deleted.
The rule this must satisfy: SD-20, "A request never reads a half-written batch",
which includes a batch deleted under it.

**Score identity.** `ensure_indexes` replaces the unique index
`uniq_user_category_method_version` with **`uniq_user_category_method_version_run`**
on `(user_id, category, method, model_version, job_run_id)`, so a new batch is
written beside the current one instead of overwriting it. A new index
`method_run` on `(method, job_run_id)` serves the deletions. The old index is
dropped if present.

**M1 as batches.** `reco/jobs/__main__._interest` runs both methods, each as its
own `run_batch` (job `interest`, slot `interest`, method `recency_decay` or
`time_windows`, collection `ml_user_interest_scores`). `reco/jobs/refresh.refresh`
takes `job_run_id`; with it, rows join the batch and nothing is swept in place.
Without it (a direct call outside a job), the old in-place rewrite still applies.

Rows written outside any job run carry `job_run_id: null`. While a method has no
current batch, `read_user_scores` reads exactly those (filter `job_run_id: None`);
once a batch is current they are ignored, and the next success deletes them.

### 4. A failed job leaves the previous batch in use: done

In `run_batch`, `work` is wrapped in `except BaseException`, so an ordinary
exception **and** a cancelled task are both
handled (a cancelled task: `asyncio.CancelledError`, e.g. the process stopped with Ctrl+C):

- the run record gets `outcome: "failed"`, `error` (the `repr`, cut to 500 characters), `finished_at`, `duration_seconds`, and **`rows_written: 0`** (fix, 1 Oct 2026, `2b585af`: the Build List lists *rows written* for every run, and a failed run's rows are all removed, so 0 is the true count; before, the field was missing);
- its partial rows are deleted (`delete_batches_except(…, only=job_run_id)`);
- `mark_current` is never reached, so the previous batch stays current;
- the exception is re-raised, so `run_nightly` alerts `job_failed` and moves on to the next job.

**Within one job (since `7442bda`).** `_interest` runs each method through
`_interest_method`, catching a failure so the other method still runs. Afterwards
the job raises `RuntimeError("interest failed for <method>")`, so `run_nightly`
still alerts. The failed method's previous batch stays current; the other method's
new batch becomes current as normal.

A kill (`SIGKILL`, a power loss) runs none of this: see item A.

### 5. Every run in `ml_job_runs`: done

One document per run. `_id` **is** the `job_run_id`.

| Field | Content |
|---|---|
| `_id` | `job_run_id`, UUID4 string |
| `job` | e.g. `interest` |
| `slot` | e.g. `interest` |
| `method` | e.g. `recency_decay`, `time_windows` |
| `collection` | where the rows went, e.g. `ml_user_interest_scores` |
| `data_window` | `{from, to}`: the events the run reads (item 6) |
| `config_version` | the settings file version in force at the start |
| `model_version` | `MODEL_VERSION` (default `1.0.0`) |
| `started_at`, `finished_at` | UTC |
| `outcome` | `running`, `succeeded` or `failed` |
| `rows_written` | on success; `0` on a handled failure (since 1 Oct); absent for an abandoned run |
| `duration_seconds` | on success or a handled failure; absent for an abandoned run |
| `error` | on failure; `abandoned: stopped before it finished` for a killed run |
| `is_current` | true on the batch requests read, one per `job` + `method` |
| `detail` | jobs without a batch only (below) |

Indexes (`ensure_engine_collections`): `job_current` on
`(job, method, is_current, finished_at desc)`, and `started_at` (desc).
`writers`: `record_job_run`, `update_job_run`, `abandon_running`,
`current_job_run_id`, `mark_current`, `delete_batches_except`, `read_job_runs`.

**Jobs that write no batch (since `7442bda`, SD-21 "every job run").**
`reco/jobs/batches.recorded_run(settings, job, *, data_window=None)` is an async
context manager. It marks earlier `running` records of the same job as abandoned
(as item A), inserts a `running` record, and on exit sets `succeeded` or `failed`
(with `error`), `finished_at`, `duration_seconds`, `rows_written` and `detail`,
which the caller fills in. `slot` and `method` are `null`; `is_current` stays false
(there is no batch). Used by:

| Job | `data_window` | `rows_written` | `detail` |
|---|---|---|---|
| `sync` (each pass, including every `sync_loop` pass; `reco/sync/run.py`) | `{from: null, to: <now>}` | rows copied | `{copied: {source: n}, failed: [sources]}` |
| `reconcile_sync` (`reco/sync/reconcile.reconcile_day`) | the IST day, e.g. `2026-09-29T18:30Z` to `2026-09-30T18:30Z` | rows re-read | `{day, passed: {source: bool}}` |
| `sync_check` (the lag check run on its own) | `null` | 0 | `{alerts: [sources over the lag limit]}` |

The reconciliation still writes its per-source result to `ml_measurements` (ENG-04 item 8).

### 6. Every score row carries its provenance: done for M1

`reco/store/scores.InterestScore` gains `job_run_id`, `config_version`,
`slot` (`"interest"`), `confidence` and `data_window`; `to_document()` also writes
`score`. SD-19's list against the stored row:

| SD-19 / Build List | Field on `ml_user_interest_scores` |
|---|---|
| what is scored | `user_id` + `category` |
| slot | `slot` = `interest` |
| method | `method` |
| model_version | `model_version` |
| config_version | `config_version` (the run's) |
| score | `score` = `share` (the M1 score is the share; `raw` and `event_count` stay as before) |
| confidence (where the method has one) | `confidence` = `null`: neither interest method has one (ENG-10). M8 stores one (ENG-16) |
| data window | `data_window` `{from, to}` |
| computed_at | `computed_at` |
| job_run_id | `job_run_id` |

**Data window per method** (`reco/jobs/refresh.data_window`): recency decay reads
every event up to the run time, so `from` is `null`; time windows reads the last
`max(interest.window_bounds_days)` days (90). Our reading of "data window" for a
method with no lower bound; the pack does not define the field's shape.

`from_document` drops `score` on read (it is derived from `share`), so a stored row
still round-trips through the model's validators.

### A. Extra: detecting a killed run: done (our choice)

A `SIGKILL` stops the process with no handler, so the run record stays
`outcome: "running"` and its partial rows stay in the collection. Neither is ever
read: the run was never marked current.

**The pack is silent on how a killed run is detected.** Our choice (1 Oct 2026): the
next `run_batch` for the same `job` + `method` calls `writers.abandon_running`, which
sets every record of that pair still `running` to `failed`, with
`error: "abandoned: stopped before it finished"` and `finished_at` = the time it was
noticed. A warning `earlier runs never finished; recorded as failed` is logged. The
killed run's rows are deleted at the next success (they are in neither `keep`
slot). The rule it satisfies: the Build List check, "ml_job_runs shows the failure".

Limits: the failure is recorded when the next run starts (normally the next night),
not at the moment of the kill; `duration_seconds` is absent.

**Fix, 1 Oct 2026 (audit, `2b585af`): a watcher alerts on a stuck run the same
day.** Waiting for the next run meant a killed run said `running` for up to a day,
and for ever if that job never ran again, with no alert. `reco/monitoring/watch.py`
now runs inside the **API process** (started in `reco/main.py`'s lifespan, so it
does not depend on the jobs process it watches), every `events.sync_interval_minutes`
(5):

- `stuck_runs()`: every `ml_job_runs` record still `outcome: "running"` whose `started_at` is more than **2 hours** ago (`STUCK_AFTER`; `writers.read_running_jobs`) raises `alert("job_stuck", …, job, method, job_run_id, started_at)`.
- The same loop runs the sync's lag check (ENG-04 item 7).

The watcher only alerts; it changes no record. The next run of that job still
records the run as abandoned (above). *Choice:* the pack sets no time for a stuck
run; 2 hours is well past any Wave 1A job on today's data (the nightly run takes
about 3 s on dev). Rule it satisfies: the Build List check, *"ml_job_runs shows
the failure"*, and SD-21. Test: `tests/test_watch.py::test_a_run_left_running_too_long_is_alerted`
(a run started 3 h ago is alerted, one started 5 min ago is not).

### B. Extra: `scripts/show_job_runs.py`: done

Read-only. Prints `ml_job_runs` newest first (id prefix, job, method, outcome, rows,
duration, `CURRENT`, error), then the score rows held per batch. Ids and counts
only, no user ids.

### C. Extra: `scripts/demo_kill_job.py`, the check with a real kill: done

Refuses any database but `reco_demo`. With four made-up users `DEMO-U1..4` and the
`recency_decay` method: a complete batch ("fashion"); a slow batch ("beauty", one
user a second) in a child process, killed with `SIGKILL` after about 2.5 s; what a
request reads; then the next batch ("travel"), which records the killed run as
failed. Its made-up batches replace that method's current batch in `reco_demo`,
which is why it runs only there.

---

## 3. Configuration reference

| Setting | Where | Value | Read by |
|---|---|---|---|
| `interest.refresh_time_ist` | `settings/engine.toml` | `"02:00"` (IST); **the only value accepted** since 1 Oct (fixed for Wave 1A) | `scheduler.run_forever`, before each wait |
| `interest.refresh_cadence` | `settings/engine.toml` | `"daily"`; **the only value accepted** since 1 Oct | not read: the scheduler always runs daily (Settings sheet: fixed for Wave 1A) |
| `events.sync_interval_minutes` | `settings/engine.toml` | 5 (fixed) | the watcher's interval (§2 A) |
| `interest.window_bounds_days` | `settings/engine.toml` | `[7, 30, 90]` | `refresh.data_window` (time windows: last 90 days) |
| `MODEL_VERSION` | environment | `1.0.0` | `model_version` on runs and rows |
| `ML_MONGO_DB` | environment | e.g. `reco_demo` for demos | where batches and `ml_job_runs` go |

No new environment variables.

## 4. Environments

The scheduler runs wherever the engine's jobs mode runs. dev (laptop): run by hand
(`nightly`) or left looping (`scheduler`). test and production: on the servers, as
the loop or from cron (open, §2 item 1). Each environment has its own engine
database, so each has its own `ml_job_runs` and batches (ENG-01).

## 5. Tests

`tests/test_nightly.py`, **11 tests**:

| Test | Database | Covers |
|---|---|---|
| `test_the_next_run_is_2am_ist` (3 cases) | no | before 02:00, exactly 02:00, and a UTC evening that is already the next IST day |
| `test_the_run_time_is_the_setting_and_reconciliation_runs_last` | no | `refresh_time_ist` is `02:00`; `next_run` honours another time; `reconcile_sync` is last |
| `test_a_failed_nightly_job_does_not_stop_the_others` | no | a failing job is alerted (`job_failed`), the next one runs |
| `test_one_interest_method_failing_still_runs_the_other` | no | `recency_decay` fails: `time_windows` still runs, and the job fails naming `recency_decay` |
| `test_a_batch_is_read_only_once_complete_and_current` | yes | success marks current; the `ml_job_runs` fields |
| `test_every_score_row_carries_its_provenance` | yes | SD-19 fields on the row; `score == share` |
| `test_a_new_batch_replaces_the_old_one_and_older_batches_are_cleared` | yes | three batches: the newest is read, the replaced one is kept, the oldest deleted |
| `test_a_failure_halfway_keeps_the_previous_batch` | yes | exception after 2 of 4 users: previous batch read and current, failure recorded, partial rows gone |
| `test_a_killed_run_is_recorded_as_failed_and_never_read` | yes | a run left `running` with half its rows: never read; the next run marks it `abandoned`; its rows cleared |

`tests/test_watch.py` (new, 1 Oct, `2b585af`): `test_a_run_left_running_too_long_is_alerted`
(database) covers the watcher's stuck-run alert; the file's other test is ENG-02's
(a settings record that failed is retried).

`tests/test_sync.py::test_every_sync_and_reconciliation_run_is_recorded`
(database) covers `recorded_run`: a sync pass, a reconciliation and a failed sync
pass give `sync succeeded`, `reconcile_sync succeeded`, `sync failed` in
`ml_job_runs`, with rows written, `detail.passed` and the day's data window.
`tests/test_score_model.py` and `tests/test_score_store.py` were updated for the
new key and fields.

```bash
TEST_MONGO_DB=reco_test_eng07 TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q tests/test_nightly.py
.venv/bin/python -m pytest -q -m "not mongo"
```

**Results on 1 Oct 2026, after the audit fixes** (dev; Atlas build cluster, per-run test database, dropped afterwards):

- `tests/test_nightly.py tests/test_watch.py`: **13 passed** (11 + 2).
- Full suite: **634 passed, 1 skipped**.

**Earlier results on 1 Oct 2026** (before the audit fixes; `TEST_MONGO_DB=reco_test_eng07`, dropped afterwards):

- `tests/test_nightly.py`: **11 passed** (6 unit, 5 database).
- `tests/test_sync.py -k every_sync_and_reconciliation`: **1 passed**.
- The checklist's 7.1 selection (`-k '2am or does_not_stop or run_time'`): **5 passed**.
- Whole unit suite (`-m "not mongo"`): **531 passed, 1 skipped**.

**Real runs on 1 Oct 2026** (throwaway `reco_demo`, dropped afterwards):

`ML_MONGO_DB=reco_demo .venv/bin/python scripts/demo_kill_job.py`:

```
1. a complete batch (everyone 'fashion')
   a request reads: DEMO-U1=fashion, DEMO-U2=fashion
2. a slow batch ('beauty'), killed halfway
    wrote DEMO-U1
    wrote DEMO-U2
   killed (SIGKILL: nothing in the job could run after it)
3. straight after the kill
   a request reads: DEMO-U1=fashion, DEMO-U2=fashion
    a36b1909  succeeded CURRENT
    1f82b556  running
4. the next night's batch ('travel')
earlier runs never finished; recorded as failed
   a request reads: DEMO-U1=travel, DEMO-U2=travel
    a36b1909  succeeded
    1f82b556  failed             abandoned: stopped before it finished
    f529f074  succeeded CURRENT
```

(How many users the slow batch writes before the kill varies, one or two.)

`ML_MONGO_DB=reco_demo .venv/bin/python -m reco.jobs nightly` (exit 0, about 2.8 s
of job time), run straight after the kill demo: `recency_decay` and `time_windows`
each scored 15 of 38 users and wrote 54 rows; both batches CURRENT; then
`reconcile_sync` for 30 Sep passed on all three sources and was recorded in
`ml_job_runs`. `scripts/show_job_runs.py` afterwards:

```
ml_job_runs in reco_demo (dev), newest first:
  fefff609  reconcile_sync None            succeeded rows     0   0.427s
  2bd6c6cb  interest  time_windows    succeeded rows    54   0.819s  CURRENT
  64a466da  interest  recency_decay   succeeded rows    54   1.154s  CURRENT
  f529f074  interest  recency_decay   succeeded rows     4   0.195s
  1f82b556  interest  recency_decay   failed    rows     -       -s           abandoned: stopped before it finished
  a36b1909  interest  recency_decay   succeeded rows     4   0.205s
score rows in ml_user_interest_scores by batch:
  recency_decay   f529f074  4
  recency_decay   64a466da  54
  time_windows    2bd6c6cb  54
```

The `reconcile_sync` record has `data_window` 29 Sep 18:30Z to 30 Sep 18:30Z (the
IST day 30 Sep), `rows_written` 0 (nothing re-read) and `detail.passed` true for
`postevents`, `orders` and `recommendationrequests`. The score rows show the rule: for `recency_decay`, the current batch
(`64a466da`) and the one it replaced (`f529f074`, kept one more night); the older
`a36b1909` and the killed `1f82b556` are gone.

**Re-run after the audit fixes, 1 Oct 2026** (demo rehearsal, `reco_demo`, dropped
afterwards): the kill demo gave the same result (killed run `running`, then
`failed: abandoned`, requests reading the previous batch); `nightly` exited 0 in
about 3.1 s with `jobs: ["interest", "category_check", "reconcile_sync"]`: both
interest methods 54 rows and CURRENT, `category_check` succeeded (alert: 42
unmapped labels, ENG-29), and `reconcile_sync` passed on **four** sources (with
`rec_serve_log`, ENG-29 item 7).

**Checklist** (`scripts/run_checklist.sh`, section 7): 7.1 schedule, run time and
order (5 passed); 7.2 complete-then-current and provenance (3); 7.3 failure halfway
(1); 7.4 killed run (1); 7.5 the real `SIGKILL` demo; 7.6 the real nightly run, both
methods CURRENT. The whole script was not re-run for this note.

## 6. Runbook

**Run the nightly jobs now:**

```bash
.venv/bin/python -m reco.jobs nightly; echo $?    # 0 = every job succeeded
.venv/bin/python scripts/show_job_runs.py          # what ran, what is current
```

**Leave the scheduler running:** `.venv/bin/python -m reco.jobs scheduler`. It logs
`next nightly run` with the due time (UTC) before each wait.

**A job failed** (a `job_failed` alert, or `nightly` exits 1):

1. `show_job_runs.py`: the failed run shows its `error`; the previous batch is still `CURRENT`, so serving is unaffected.
2. Fix the cause, then re-run `nightly` (or the job on its own, e.g. `python -m reco.jobs interest`). A success becomes current at once.
3. The fallback ladder (ENG-09, not built yet) treats a score over 48 hours old as stale (rung 4), so one missed night stays fresh; two in a row need attention.

**A run shows `running` long after it should have finished** (since 1 Oct, a
`job_stuck` alert after 2 hours, from the watcher in the API): the process was
killed or hung. Check first that no run is really still going (only one scheduler
per environment); stop a hung one. Nothing needs cleaning by hand: the next run of
that job and method records it as failed and its rows are cleared at the next
success. The alert repeats every 5 minutes until then.

## 7. Open

| Open item | Needs |
|---|---|
| The other nightly jobs (M2 method two, ENG-14, added 16 Oct): M5 (ENG-17), M8 (ENG-16), M6 (ENG-18), the fraud rules (ENG-21) | Their items; each adds its name to `NIGHTLY`, before `reconcile_sync` |
| The monthly trigger for M8's copy on the 1st: the scheduler has none | ENG-16 |
| ~~M1's input from `ml_events` instead of the older readers~~ | Done 14 Oct 2026 (ENG-10) |
| On the servers: the `scheduler` loop or cron calling `nightly` | The servers (ENG-01, SD-03); decide then |
| Overlapping runs are not prevented: if two runs of the same job + method overlap (two schedulers, or cron plus the loop), the second records the first as abandoned while it still runs | Run one scheduler per environment; add a lock if the server setup needs one |
| Run the check on **test**, then mark Passed | The test environment (ENG-01) |
| Alert channel: alerts are CRITICAL log lines until one is chosen | As ENG-04 item 7 |

Closed on 1 Oct 2026 (audit, `2b585af`): a killed run left `running` with no
alert (now `job_stuck` after 2 h, §2 A); a failed run with no `rows_written` (now
0, §2.4); `refresh_time_ist` / `refresh_cadence` changeable although fixed for
Wave 1A (now locked, §2.1).

## 8. Files changed

| File | Change |
|---|---|
| `reco/jobs/batches.py` | New: `run_batch` |
| `reco/jobs/scheduler.py` | New: `NIGHTLY`, `next_run`, `run_nightly`, `run_forever`; since 1 Oct the time from `interest.refresh_time_ist` and `reconcile_sync` last |
| `reco/jobs/__main__.py` | `interest` runs each method as a batch; new jobs `nightly`, `scheduler` |
| `reco/jobs/refresh.py` | `job_run_id` parameter; `data_window`; no in-place sweep for a batch run |
| `reco/store/scores.py` | `InterestScore`: `job_run_id`, `config_version`, `slot`, `confidence`, `data_window`; `score` in the document; key includes `job_run_id` |
| `reco/store/writers.py` | `ml_job_runs` indexes and functions; `read_user_scores` reads the current batch only; score index `uniq_user_category_method_version_run`, `method_run` |
| `reco/api/profiles.py` | Demo endpoints read the current batch |
| `scripts/show_job_runs.py`, `scripts/demo_kill_job.py` | New |
| `scripts/run_checklist.sh` | Section 7 |
| `tests/test_nightly.py` | New, 11 tests |
| `reco/jobs/batches.py` (`7442bda`) | `recorded_run` for jobs that write no batch |
| `reco/jobs/__main__.py` (`7442bda`) | `_interest_method`; `sync_check` recorded |
| `reco/sync/run.py`, `reco/sync/reconcile.py` (`7442bda`) | Each sync pass and each reconciliation recorded in `ml_job_runs` |
| `tests/test_sync.py` (`7442bda`) | `test_every_sync_and_reconciliation_run_is_recorded` |
| `tests/test_score_model.py`, `tests/test_score_store.py` | New key and fields |
| `reco/jobs/batches.py` (`2b585af`) | `rows_written: 0` on a handled failure |
| `reco/monitoring/watch.py` (`2b585af`) | New: `stuck_runs`, `watch_once`, `watch_loop` |
| `reco/main.py` (`2b585af`) | Starts and stops the watcher with the API |
| `reco/store/writers.py` (`2b585af`) | `read_running_jobs` |
| `reco/config/tunables.py` (`2b585af`) | `refresh_cadence: Literal["daily"]`, `refresh_time_ist: Literal["02:00"]` |
| `tests/test_watch.py` (`2b585af`) | New: the stuck-run alert |

## 9. Demo

The live demo script, in plain language, is the Obsidian note
`obsidian/Demos/Demo - ENG-07.md`.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks
(section 7) with those of every other finished item.

## Update, 16 Oct 2026

**16 Oct 2026:** Passed (Kala S1).
