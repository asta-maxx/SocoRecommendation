# ENG-04: Engine sync, copy platform events, orders and served lists

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days of starting) |
| **Waits on** | ENG-02 (built), DB-02 (read-only login), APP-12 (`updated_at` on the platform side: reported built, not yet in the dev data) |
| **Needed by** | ENG-06, ENG-10, ENG-25, DB-16, ENG-27, ENG-28, ENG-29 |
| **Status** | **Built** (1 Oct 2026, on dev). All nine parts built and the checks (a)–(g) pass on constructed data; the real backfill ran into the dev engine database. Becomes Passed when re-run on **test** (Definitions: every check runs on test). Waits on APP-12, the test environment and ENG-29 (`rec_serve_log`, `tracking_info`) |
| **Spec** | Build List v1.3 ENG-04 (and ENG-29 items 4, 7; DB-16 step 4; Settings sheet "Engine sync", "Keep event data"); DS-017 v2.5 §7; SDA v1.6 SD-29, SD-30, SD-27; Capture Register X-02, X-08, D8, F74, E1 |

> **Replaces** the 22 Sep design of this item (`POST /v1/events`, `INGEST_TOKEN`, the four-pair reconciliation and the event source switch, built 29 Sep). DS-017 v2.5 §7: *"POST /v1/events, INGEST_TOKEN on events and the queued forwarding in v2.2 are retired."* The endpoint, the token and the switch were removed in the ENG-02 and ENG-03 realignments (see `Tracing/REALIGNMENT_v1.3.md`). The old check record `Tracing/checks/ENG-04_2026-09-29.md` is kept as history only.

---

## 1. What the item requires

The Build List v1.3 row, verbatim:

> Replaces POST /v1/events, which is retired (API contract v2.4, section 7).
>
> 1. Backfill: copy everything the platform holds in postevents, orders and recommendationrequests into ml_events and ml_orders, keyed on the platform _id. It can be restarted without creating duplicates.
> 2. Incremental read every 5 minutes (a setting), per collection: the rows with updated_at later than the checkpoint, ordered by updated_at then _id, re-reading a 2-minute overlap.
> 3. Upsert: a row already held is updated, never skipped, so an undo (undone_at), an order status change, a return request or new seen_ids arrive.
> 4. Save the checkpoint in ml_sync_state only after the batch is written.
> 5. Keep on every copy: the source collection, source _id, event_id, undo_of, undone_at, created_at (the original event time) and updated_at. Map native event types to the E codes (capture register, sheet 4).
> 6. Retention: at least 365 days from the original event time, under the engine's own expiry. The platform's 90-day expiry never deletes an engine copy. An update never resets the original time.
> 7. Alerts: a lag of more than 15 minutes on any collection, or a failed run, alerts the service owner (Allen), who restarts from the last checkpoint.
> 8. Daily reconciliation per collection, for the previous day: the set of ids matches, and for changed rows the field values match (undone_at, order_status, statusLog, return_info, seen_ids). Equal counts alone do not pass. Mismatches are logged and re-read.
> 9. Keep each order's status history: whenever the sync sees a new order_status, store it with its time (updated_at), so the engine knows an order reached Delivered or Return Requested even if it changes later.

**How to check it is done:**

> On test: (a) the reconciliation report shows matching ids and field values; (b) a like undone after it was copied updates the existing copy; (c) stopping the sync for an hour and restarting loses nothing and duplicates nothing; (d) two rows with the same updated_at across a page boundary are both copied; (e) a failure before the checkpoint re-reads that batch; (f) the alert fires in a test outage; (g) the retention setting is shown.

**ENG-29 changes two parts on top of this row** (Build List v1.3, ENG-29):

- **Item 4:** *"tracking_info (APP-08) is the history of each order … Status changes the sync observes itself (ENG-04 point 9, if built) are kept as a cross-check only. The daily reconciliation compares tracking_info in place of statusLog and return_info."* The platform has no `statusLog` or `return_info`. This item already compares `tracking_info` (§2.8); part 9 is built and kept as the cross-check.
- **Item 7:** *"Add rec_serve_log (APP-15) to the sync, read the same way as recommendationrequests."* Not in this item: `rec_serve_log` doesn't exist on the platform yet, and ENG-29 adds it to `SYNC_SOURCES`.

> **Since ENG-29 (1 Oct 2026, `f7c82f3`):** the sync has a **fourth source**, `rec_serve_log` → `ml_events` (`event_type: serve_log`; compared fields `origin`, `outcome`, `elapsed_ms`; `updated_at` dropped 1 Oct, see below), and the order copies carry the `tracking_info` stages and times (ENG-29 items 4 and 7). The collection doesn't exist on dev yet (APP-15), so it copies 0 rows. Checklist line 4.10 now expects **4** sources with `backfill done`. See `docs/engineering/ENG-29.md` §2.7.

> **Updated 1 Oct 2026 (audit, `6c3ef46`, `2b585af`, `964f4ec`), `rec_serve_log`:**
> it is **append-only**: written once per list request (DS-017 §4.3), so it needs
> no `updated_at` (question 3 answered, `Tracing/REALIGNMENT_v1.3.md`). The
> incremental read carries on **by `_id`** from the backfill's `after_id`, first
> stepping back `sync_overlap_minutes` (2) of `_id` time, because several SOCO_BE
> servers write it and their `_id`s can land slightly out of order; copies are
> upserts, so the re-read never duplicates. Its time field is **`at`** (Capture
> Register F80; then `time`, `timestamp`, `created_at`, then the `_id`). The
> reconciliation compares `origin`, `outcome`, `elapsed_ms` (no `updated_at`).
> Test: `test_a_serve_log_row_written_slightly_out_of_order_is_still_copied`.
> The rest of the 1 Oct audit is under parts 7 and 9, extras B and E, and §3.

**Settings sheet (fixed for Wave 1A):** Engine sync *"every 5 minutes, re-reading a 2-minute overlap; alert when more than 15 minutes behind"* (range 1 to 15 minutes); Keep event data *"engine copies: at least 365 days from the event time"*.

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–9 are the Build List's parts, A–E are extras (D and E added 1 Oct).

Layout: `reco/sync/copies.py` (what is copied and the shape of a copy), `reco/sync/run.py` (backfill, incremental, checkpoints, lag alert), `reco/sync/reconcile.py` (daily reconciliation). Reads go only through `reco/platform/fetch.py` and writes only through `reco/store/writers.py` (ENG-02's module rule). Jobs in `reco/jobs/__main__.py`:

```
python -m reco.jobs sync             # one pass over every source (backfill first if unfinished)
python -m reco.jobs sync_loop        # a pass every sync_interval_minutes, settings re-read each pass
python -m reco.jobs sync_check       # the lag alert on its own
python -m reco.jobs reconcile_sync   # yesterday's reconciliation (IST day)
```

### 1. Backfill, keyed on the platform `_id`, restartable: done

`run.backfill(settings, source)`, reading with `fetch.read_page_by_id` (rows in `_id` order, after the last `_id`, `PAGE_SIZE` = 500 per page).

- **Sources** (`copies.SYNC_SOURCES`): `postevents` → `ml_events`, `orders` → `ml_orders`, `recommendationrequests` → `ml_events` (as the E1 served-list record, Capture Register E1).
- **Keyed on the platform `_id`:** the copy's `_id` *is* the platform `_id` (DS-017 §7: "unique on the platform _id").
- **Restartable:** `ml_sync_state.backfill = {done, started_at, finished_at, after_id, copied}`. `after_id` is saved after each page is written, so a stopped backfill carries on after the last written page, and any re-read is an upsert, never a duplicate.
- **Hand-off to the incremental read:** when the backfill finishes, the checkpoint is set to the time the backfill **started**, so a row changed while the backfill ran is read again by the first incremental pass. *Choice (the pack is silent); rule it must satisfy: DS-017 §7 "before the first incremental read, the service copies everything the platform still holds", with nothing lost between the two.*
- **Page size 500.** *Choice (the pack sets none); rule: one page must fit in one bulk write and be re-read whole after a failure (item 4).*

**Real run, 1 Oct 2026, into the dev engine database `SoCo`:** postevents **146**, orders **8**, recommendationrequests **12**, in about 3 s.

> **Time-critical.** DB-01 / X-08 keep the platform's 90-day expiry on short-lived `postevents` types and on `recommendationrequests`. Whatever is not copied before it reaches 90 days is gone. The backfill must be run on every environment (test, then production) as soon as it exists. The oldest dev copy is from 23 Jun 2026.

### 2. Incremental read every 5 minutes, by `updated_at`, with a 2-minute overlap: built; waits on APP-12 for real data

`run.incremental(settings, source)`, reading with `fetch.read_page_by_updated_at`:

- Rows with `updated_at >= checkpoint − sync_overlap_minutes` (2), sorted by `(updated_at, _id)`.
- **Keyset paging:** after the first page the query is `updated_at > at OR (updated_at = at AND _id > last_id)`, so two rows with the same `updated_at` either side of a page boundary are both read (check d).
- **Every 5 minutes:** `run.sync_forever` (job `sync_loop`) runs a pass, then sleeps `events.sync_interval_minutes` (5, range 1–15). It re-reads the settings before each pass (`config_sync.reload`), so a changed interval takes effect with no restart (ENG-02).
- One source failing doesn't stop the others; the pass still ends in failure, so the job exits non-zero.

**Data reality (dev platform, 1 Oct 2026):** `postevents.updated_at` on **0 of 146** rows, `orders.updated_at` on **3 of 8**, `recommendationrequests.updated_at` on **0 of 12**. F74 / APP-12 are "reported built, verification pending" but the field isn't in this database yet. **Until APP-12 lands, the incremental read sees no changes.** Meanwhile:

- the backfill has copied everything there is;
- the daily reconciliation (part 8) reads the day by `created_at` (or `server_ts`) **and** by the `_id` time, so a row **created** yesterday is found and copied, about a day late;
- a change to an **older** row that doesn't move `updated_at` (an undo of last week's like, a `tracking_info` entry on an old order) is visible to neither. That is exactly what APP-12 fixes; the reconciliation is how APP-12 is verified (APP-12 row: "Verification pending: the ENG-04 reconciliation").

### 3. Upsert: a row already held is updated, never skipped: done

`writers.upsert_copies(settings, target, copies, copied_at)`: one `UpdateOne({_id}, {$set: copy + last_copied_at, $setOnInsert: first_copied_at}, upsert=True)` per row, in one ordered `bulk_write`. A re-read row replaces the held fields (so `undone_at`, a new `order_status`, a return request or new `seen_ids` arrive), `first_copied_at` is set once, and nothing is ever inserted twice. Check (b) is a like undone after it was copied: one copy, `undone_at` set, `created_at` and `first_copied_at` unchanged.

### 4. Checkpoint saved only after the batch is written: done

`ml_sync_state`, one document per source collection (`_id` = the collection name):

| Field | Meaning |
|---|---|
| `backfill` | `{done, started_at, finished_at, after_id, copied}` |
| `checkpoint` | the latest `updated_at` written; the next read starts 2 minutes before it |
| `current_as_of` | when the last **successful** pass started: every row changed before then has been copied |
| `last_run` | `{started_at, finished_at, outcome, copied, error}` |

In both `backfill` and `incremental`, the position (`after_id` / `checkpoint`) is written **after** `write_page` returns. A failure in between leaves the old position, so the next pass re-reads that page; the upsert (part 3) makes the re-read harmless (check e).

### 5. What every copy keeps; E codes: done

`copies.make_copy(source, doc, statuses)` builds a copy from the ENG-03 record for its kind (`records.parse_postevent`, `parse_order`, `parse_served_list`) plus:

| Field | From |
|---|---|
| `_id`, `source_id` | the platform `_id` (and as text) |
| `source` | the platform collection |
| `kind` | `postevent`, `order` or `served_list` |
| `event_id`, `undo_of`, `undone_at` | the platform row (ENG-03 record) |
| `created_at` | the **original** event time from the platform row (or the `_id` time when missing, ENG-03) |
| `updated_at` | the platform row's |
| `event_code` | the E code from Capture Register sheet 4 (`reco.platform.native_events`, via ENG-03); `None` for a type sheet 4 maps to "—" |
| `platform` | the whole platform row as read (without `_id`) |
| `first_copied_at`, `last_copied_at` | set by the writer |

A served list (`recommendationrequests`) is copied as `event_type: served_list`, `event_code: E1`, `scored: False`, with `seen_ids` as text: a platform list is a fallback list unless its `policy_id` says otherwise (F06).

**Keeping the whole platform row** under `platform` is a *choice (the pack is silent); rule: the reconciliation must compare field values exactly (item 8, SD-30)*, and a parsed field may be normalised (ids to text, statuses mapped), so the comparison is made against the row as read.

Real dev copies, 1 Oct 2026 (`scripts/show_events.py`): `postevents` E2 5, E3 3, E4 6, E5 63, E9 50, no code 19; `recommendationrequests` E1 12.

### 6. Retention: 365 days from the original event time: done (index from ENG-01)

`writers.ensure_engine_collections` (ENG-01) creates a `retention` expiry index on `created_at` on both `ml_events` and `ml_orders`, `expireAfterSeconds = events.retention_days × 86400` (365, fixed). The copy's `created_at` is the platform's original time, and `upsert_copies` never moves it, so an update never resets the clock (SD-29). The platform's 90-day expiry deletes platform rows only; nothing deletes an engine copy except this index (X-08, D8). Routine expiry is not account deletion (ENG-28).

### 7. Lag and failure alerts to the service owner: done

`run.check_lag(settings)`, called at the end of every pass and on its own by the `sync_check` job:

- **lag = now − `current_as_of`** (the start of the last successful pass). *Choice (the pack defines "behind" but not how it is measured); rule: SD-30 "a sync more than 15 minutes behind".* Measured from the pass start, not from the newest `updated_at`, so a quiet collection with no new rows isn't reported as behind.
- Alerts when lag > `events.sync_lag_alert_minutes` (15, fixed), when the last run failed, or when a source has state but no successful pass yet.
- `run.sync_source` also alerts the moment a source fails (`reason: sync_failed`), records `last_run.outcome = failed` and the error, and re-raises.

**The watcher (1 Oct 2026 audit, `2b585af`): the lag check no longer depends on
the sync.** Until then the lag check ran only at the end of a sync pass or in
the `sync_check` job, so a sync process that had died or hung (the very case
item 7 is for) raised nothing. `reco/monitoring/watch.py`, `watch_loop`, now runs
**inside the API process** (started and cancelled in `reco/main.py`'s lifespan,
beside the settings reload) and calls `run.check_lag` every
`events.sync_interval_minutes` (5), independently of any sync. The API is the one
process that is always up (SD-01). An error in the watcher is logged and it
carries on. It also runs the stuck-run alert (extra E).

`reco/monitoring/alerts.py`, `alert(reason, message, **fields)`: a **CRITICAL** structured log line on logger `reco.alert` with `"alert": true`, `"reason"` and `"owner": "Allen"`. *Choice: the pack names who is alerted (the service owner, Allen) but not the channel. Until one is chosen the log line is the alert, and a log collector can route on the one field.* Restart is "from the last checkpoint": simply run the next pass.

### 8. Daily reconciliation: ids and field values: done

`reconcile.reconcile_day(settings, day=None)` (job `reconcile_sync`), per source:

1. **The day:** the previous **IST** day by default. *Choice (the pack names no day boundary); rule: the jobs run on IST (2 AM IST, ENG-07; SDA "the daily reconciliation runs after the 2 AM refreshes").*
2. **Platform side** (`fetch.read_touched`): rows whose own time (`created_at`; for served lists `server_ts` or `created_at`), `updated_at` or `_id` time falls in the day.
3. **Engine side** (`writers.read_copies_touched`): copies of that source whose `created_at` or `updated_at` falls in the day, plus the copies of every platform id found.
4. **Ids:** `missing` (on the platform, not held), `extra` (held, not among the day's platform rows).
5. **Field values:** for every row on both sides, the compared fields must equal the platform row exactly (`copy.platform[field] == platform[field]`):

   | Source | Compared |
   |---|---|
   | postevents | `undone_at`, `undo_of`, `updated_at` |
   | orders | `order_status`, `tracking_info`, `updated_at` (ENG-29 item 4: `tracking_info` in place of `statusLog` and `return_info`) |
   | recommendationrequests | `seen_ids`, `updated_at` |

6. **Equal counts alone don't pass:** `passed` only if there are no missing, mismatched or extra ids.
7. **Logged and re-read:** every missing and mismatched row, and every extra id the platform still holds, is copied again through `run.write_page`. An extra id the platform no longer holds is reported (`extra_not_on_platform`) and left for ENG-28.
8. **Saved:** one document per source per day in `ml_measurements` (`measure: sync_reconciliation`, `source`, `day`; replaced on a re-run), with counts and up to 50 listed ids per kind. Logged at INFO when passed, WARNING when not. SD-27 tracks "the daily reconciliation result".

**DB-16 step 4** needs Allen to "confirm in writing that the reconciliation has passed on 7 days in a row" on each environment before the old collections are dropped. The 7 daily results are in `ml_measurements`; the written confirmation is Allen's.

**Real run, 1 Oct 2026:** yesterday's reconciliation (2026-09-30) passed on all three sources (0 rows that day). Re-run for 2026-09-24 (96 postevents, 2 served lists) in a throwaway database: passed; after one copy was deleted and another's `undone_at` changed, it reported `missing 1, mismatched 1 ['undone_at'], re-read 2, NOT PASSED`, and passed on the next run.

### 9. Each order's status history: done (a cross-check under ENG-29)

`copies.with_history(copy, held)`: for orders, `run.write_page` reads the held copies first and carries `status_history` forward, appending `{status, at: updated_at}` whenever the status now seen differs from the last one held (falls back to `created_at` when `updated_at` is missing). Tested: Placed → Delivered → Return Requested gives three entries and `is_returned`.

**Fixes, 1 Oct 2026 (audit, `2b585af`):**
- The new status is compared with the last one held **ignoring case**
  (`records.status_is`), so `Delivered` then `delivered` is one entry, not two
  (Build List v1.3 ENG-03: "Status fields: compared ignoring case").
- A `tracking_info` entry whose text matches no stage in `lists.tracking_stages`
  is **stored as read and logged** (`reco.sync` WARNING "tracking_info entries with
  no stage", with the order id and up to five texts), never rejected: DS-017 §6.4,
  "any other value is stored and logged". Test:
  `test_an_order_history_entry_with_no_stage_is_logged`. (The case-insensitive
  compare has no test of its own.)

ENG-29 item 4 makes `tracking_info` the order's history; this list is kept **as a cross-check only**. It sees only the statuses the sync happened to observe, so before APP-12 it holds one entry per order.

### A. Extra: the alert module: done

`reco/monitoring/alerts.py` (part 7). One function, one logger, one owner constant, so ENG-24's monitoring and any later channel plug in at one place.

### B. Extra: `scripts/show_events.py`: done

Read-only view of the sync: `ml_events` copies by source and E code, the `ml_orders` count, each source's backfill / checkpoint / `current_as_of` / last run, and the latest reconciliation results. Prints counts, codes and times only, no user ids.

**Check (g), "the retention setting is shown" (1 Oct 2026 audit, `2b585af`):** the
script now prints the retention: the `retention` index's `expireAfterSeconds` in
days, beside the setting in force. Run on dev (`SoCo`), 1 Oct 2026:

```
ml_orders: 8 orders
retention: copies kept 365 days from the original event time (setting events.retention_days = 365; index on created_at)
sync state:
```

Before, (g) was shown only by a test and by reading `settings/engine.toml`.

### C. Extra: the real backfill into dev: done

Run on 1 Oct 2026 against the dev platform with the read-only login, into `SoCo` (§1). Re-run on the same day into a throwaway database for the demo: same counts, a second pass copied 0 and duplicated nothing.

---

### D. Extra: every pass and every reconciliation recorded in `ml_job_runs`: done (1 Oct, `7442bda`)

SD-21: "Every job run is recorded in ml_job_runs: what ran, over what window,
rows written, and whether it succeeded." `sync_once` runs inside
`reco.jobs.batches.recorded_run(settings, "sync")` (rows_written = rows copied;
detail = copied and failed per source); `reconcile_day` inside
`recorded_run(settings, "reconcile_sync", data_window=<the IST day>)`
(rows_written = rows re-read; detail.passed per source); the `sync_check` job
as `sync_check`. A failed pass is recorded with its error; a killed one is
marked failed ("abandoned") when the same job next starts. The reconciliation
also runs last in the nightly jobs (SD-22, ENG-07). Test:
`test_every_sync_and_reconciliation_run_is_recorded`.

### E. Extra: an alert for job runs stuck "running": done (1 Oct 2026 audit)

`watch.stuck_runs` (run by the watcher, part 7) reads `ml_job_runs` for runs still
`outcome: running` more than **2 hours** after `started_at`
(`writers.read_running_jobs`) and raises `alert("job_stuck", …)` for each, with the
job, method, run id and start time. A killed process runs no handler, so its run
would otherwise stay "running" until the same job next starts (extra D). ENG-07:
"ml_job_runs shows the failure". *Choice: the pack sets no time. Rule it must
satisfy: well past any Wave 1A job on today's data, so a slow run is not reported.*
Test: `tests/test_watch.py::test_a_run_left_running_too_long_is_alerted`.

## 3. Configuration reference

No new environment variables. Settings (`settings/engine.toml`, `[events]`, validated in `reco/config/tunables.py`; from the Settings sheet):

| Setting | Value | Rule |
|---|---|---|
| `sync_interval_minutes` | 5 | fixed for Wave 1A since the 1 Oct audit (the sheet's 1–15 range is for later waves; ENG-02 §2 part 3) |
| `sync_overlap_minutes` | 2 | fixed |
| `sync_lag_alert_minutes` | 15 | fixed |
| `retention_days` | 365 | fixed (at least 365, SD-29) |

Code constants (choices, §2): `run.PAGE_SIZE = 500`; `reconcile.IST`; `reconcile.LISTED = 50`; `alerts.SERVICE_OWNER = "Allen"`; `watch.STUCK_AFTER = 2 h` (1 Oct audit).

---

## 4. Environments

| Environment | State (1 Oct 2026) |
|---|---|
| dev (laptop, engine DB `SoCo`) | Backfill done on all three sources; reconciliation of 2026-09-30 passed |
| test | Not yet: the server and its constructed data come with ENG-01 / ENG-29 item 8. The official check runs here |
| production | Not yet. The backfill must run before the oldest rows reach the platform's 90 days |

The lag alert now runs in the API process (the watcher, part 7), so on a server the alert works as long as the API is up, whether or not `sync_loop` is. On the laptop this means an API started against `SoCo` without `sync_loop` running logs a `sync_lag` alert per source every 5 minutes once the copies are more than 15 minutes old: expected, and the reminder to run `sync_loop`. `sync_loop` is not yet scheduled anywhere; on a server it runs as its own long-lived job process (SDA: "the engine sync (every 5 minutes)"). `reconcile_sync` belongs after the 2 AM refreshes (ENG-07).

---

## 5. Tests

`tests/test_sync.py`, on constructed platform-shaped data (the platform side is the throwaway `<TEST_MONGO_DB>_platform` database, written as the platform would):

| Check | Test |
|---|---|
| copies (no DB) | source fields and E code kept; served list as E1 with `seen_ids`; status history adds only a new status; the three sources |
| (g) retention | `test_retention_is_the_setting` (≥ 365); the index itself: `tests/test_engine_environment.py::test_copies_expire_365_days_after_the_original_event_time` |
| part 1 | backfill copies everything keyed on `_id`, a second pass adds nothing; a stopped backfill restarts after its last page |
| (b) | `test_an_undo_updates_the_existing_copy` |
| part 9 | `test_an_order_keeps_its_status_history` |
| (c) | `test_an_hour_stopped_loses_and_duplicates_nothing`: checkpoint set an hour back, 10 rows changed in that hour, all copied once |
| (d) | `test_same_updated_at_across_a_page_boundary`: 5 rows, one `updated_at`, page size 2 |
| (e) | `test_a_failure_before_the_checkpoint_rereads_the_batch` |
| (f) | `test_the_alert_fires_when_the_sync_is_behind` (16 minutes); `test_the_alert_fires_when_a_run_fails` (a test outage of the platform read: `sync_failed` and `sync_lag`) |
| (a) | `test_reconciliation_passes_when_ids_and_fields_match`; `test_reconciliation_finds_and_rereads_what_the_sync_missed` (a changed `undone_at` and a new `tracking_info` entry without `updated_at`, and a new row with no `updated_at`: found, re-read, then passes) |

```bash
TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q tests/test_sync.py
```

**Results, 1 Oct 2026:**
- `tests/test_sync.py`: **16 passed** (11 database tests marked `mongo`, 5 without). Re-run the same day with `TEST_MONGO_DB=reco_test_eng04doc`: 16 passed.
- Full suite at commit `6c4299c`: **541 passed, 1 skipped**.

**After the audit fixes, 1 Oct 2026:** `tests/test_sync.py` now has **19** tests
(extra D's run-diary test, the out-of-order serve-log row, the tracking entry with
no stage) and `tests/test_watch.py` 2 (stuck run; ENG-02's late settings record).
Both **passed** (19 + 2), run with ENG-02's and ENG-03's files: 181 passed, 0
failed. Whole suite after `964f4ec`: **634 passed, 1 skipped**. Demo step 8's
selection: 10 passed, 9 deselected.

> ~~Run the suite with its own `TEST_MONGO_DB` when another suite may be running: two runs sharing `reco_test` race on collection creation.~~ Since 1 Oct (audit, `tests/conftest.py`) each run gets its own `reco_test_<pid>` and `reco_test_<pid>_platform`, dropped at the end; `TEST_MONGO_DB` still overrides.

`scripts/run_checklist.sh` section 4 runs these per check (4.1–4.9), then a real backfill from the platform into `reco_demo` (4.10, expects 3 sources with `backfill done`; **4** since ENG-29) and yesterday's real reconciliation (4.11, expects `"passed": true`).

---

## 6. Runbook

```bash
# One pass (backfill first if unfinished). Exit code non-zero if any source failed.
.venv/bin/python -m reco.jobs sync

# Every 5 minutes, until stopped.
.venv/bin/python -m reco.jobs sync_loop

# What has been copied, how far behind each source is, and the latest reconciliations (read-only).
.venv/bin/python scripts/show_events.py

# The lag alert on its own. (The API also runs it every 5 minutes, with the stuck-run alert: reco/monitoring/watch.py.)
.venv/bin/python -m reco.jobs sync_check

# Yesterday's reconciliation (IST day).
.venv/bin/python -m reco.jobs reconcile_sync
```

**When the alert fires** (`"alert": true`, `"owner": "Allen"` in the logs): `reason: job_stuck` means a job run has said "running" for over 2 hours (killed or hung): check the process, then rerun the job. Otherwise read `reason` and `source`, check `scripts/show_events.py` for `last run failed` and the error in `ml_sync_state.last_run.error`, fix the cause (usually the platform connection), then run `python -m reco.jobs sync`. It restarts from the saved checkpoint (or the backfill's `after_id`); re-reads are upserts.

**A reconciliation for a given day:** `reconcile.reconcile_day(settings, "YYYY-MM-DD")` (no CLI argument yet).

**Starting over on an environment** (never needed in normal running): delete that source's `ml_sync_state` document; the next pass re-runs the backfill, as upserts.

---

## 7. Open

| Open item | Waits on |
|---|---|
| `updated_at` on every platform row, so the incremental read sees changes (0/146 postevents, 3/8 orders, 0/12 served lists on 1 Oct) | **APP-12** (Aravinth); verified by this reconciliation |
| Run the checks (a)–(g) on test, then mark Passed | The test environment (ENG-01) and its constructed data (ENG-29 item 8) |
| Run the backfill on test and production before rows reach 90 days | Those environments |
| `rec_serve_log` copied for real | ENG-29 item 7 added it to the sync; APP-15 (the collection doesn't exist yet). Q3 **answered 1 Oct**: append-only, no `updated_at` needed, read by `_id` with the overlap |
| `tracking_info` as the order history; part 9 as the cross-check | **ENG-29** item 4 (the reconciliation already compares `tracking_info`) |
| Schedule `sync_loop` and `reconcile_sync` | ENG-07 and the servers |
| An alert channel beyond the log line | A decision (ENG-24 monitoring) |
| DB-16 step 4: written confirmation that the reconciliation passed 7 days in a row | Allen, per environment, after APP-12 |
| ~~Do migrated `postevents` rows keep their `_id` and get an `updated_at`?~~ Q10 **answered 1 Oct**: not needed, the backfill runs after the migration (DB-16 step 4) and keys on `_id` (`Tracing/REALIGNMENT_v1.3.md`) | — |

---

## 8. Files changed

Commit `6c4299c` (1 Oct 2026):

| File | Change |
|---|---|
| `reco/sync/copies.py` | New: `SYNC_SOURCES`, `make_copy`, `with_history` |
| `reco/sync/run.py` | New: `backfill`, `incremental`, `write_page`, `sync_source`, `sync_once`, `check_lag`, `sync_forever` |
| `reco/sync/reconcile.py` | New: `reconcile_day`, `reconcile_source`, `day_bounds` |
| `reco/monitoring/alerts.py` | New: `alert` |
| `reco/platform/fetch.py` | `read_page_by_id`, `read_page_by_updated_at`, `read_by_ids`, `read_touched` |
| `reco/store/writers.py` | `upsert_copies`, `read_copies`, `read_copies_touched`, `read/write_sync_state`, `read_all_sync_state`, `record_sync_reconciliation` |
| `reco/jobs/__main__.py` | Jobs `sync`, `sync_loop`, `sync_check`, `reconcile_sync` |
| `scripts/show_events.py` | Shows sync state and reconciliation results |
| `scripts/run_checklist.sh` | Section 4 (4.1–4.11) |
| `tests/test_sync.py` | New: 16 tests |

1 Oct 2026, audit (`6c3ef46`, `2b585af`, `964f4ec`):

| File | Change |
|---|---|
| `reco/monitoring/watch.py` | New: `watch_loop`, `watch_once`, `stuck_runs` (part 7, extra E) |
| `reco/main.py` | Starts and stops the watcher with the API |
| `reco/store/writers.py` | `read_running_jobs` |
| `reco/sync/copies.py` | `rec_serve_log` append-only, time field `at`, compared `origin`/`outcome`/`elapsed_ms`; status history ignores case; unknown tracking stages logged |
| `reco/sync/run.py` | Append-only incremental read by `_id`, with the overlap re-read |
| `reco/platform/records.py` | `parse_serve_log` reads `at` first (F80) |
| `scripts/show_events.py` | Prints the retention (check g) |
| `tests/test_sync.py`, `tests/test_watch.py`, `tests/test_platform_dataset.py` | Two sync tests; the watcher tests; serve-log copies counted as distinct rows |

## 9. Demo

The live demo script, in plain language, is `obsidian/Demos/Demo - ENG-04.md`.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks with those of every other finished item, prints PASS/FAIL per line and drops `reco_demo` at the end.
