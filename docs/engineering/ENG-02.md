# ENG-02: Service skeleton, settings and health check

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | ENG-01 (built on dev; its server parts come later) |
| **Needed by** | ENG-03, ENG-04, ENG-05, ENG-07 |
| **Status** | **Built.** First built 24 Sep 2026 to the 22 Sep row (check passed on dev, `Tracing/checks/ENG-02_2026-09-24.md`); **realigned to the v1.3 row on 1 Oct 2026** (commit `71b6981`), and its check passed again on dev the same day. Becomes Passed when re-run on test (Definitions: every check runs on test) |
| **Spec** | Build List v1.3 ENG-02; SDA v1.6 SD-01, SD-05 to SD-10, SD-26 to SD-28; DS-017 v2.5 §3, §7; Settings sheet (v1.3); AS-04; X-02 |

> **What changed on 1 Oct (v1.3).** The engine no longer receives events.
> `POST /v1/events` is retired (DS-017 v2.5 §7; X-02), and the engine sync
> (ENG-04) copies the platform's events instead. So the SD-05 module **`events`
> is now `sync`**, and the API has no event endpoint (SD-01). The bearer-token
> check moved to `reco/api/auth.py`: `INGEST_TOKEN` is now the serving token for
> `POST /v1/recommendations` (DS-017 v2.5 §3, AS-04). The settings file follows
> the v1.3 Settings sheet: surface modes off | internal | live, the engine sync
> timings, the eligibility refresh, and a new `[lists]` section. It is committed
> at `config_version = "2"`. Background: `Tracing/REALIGNMENT_v1.3.md`.

---

## 1. What the item requires

The Build List v1.3 row, quoted:

> 1. One Python service, in two modes: the API (serving, fraud cases, health) and scheduled jobs (including the engine sync, ENG-04).
> 2. Modules: api, config, slots, store, platform, eligibility, ranking, fallback, sync, jobs, fraud, monitoring.
>    - Only platform reads the platform database.
>    - Only store writes, and only to the engine database.
> 3. One versioned settings file holding every value on the Settings sheet. It is reloaded at least once a minute. A broken file keeps the last good version and logs the fault. With no good version at all, it uses the defaults on the Settings sheet.
> 4. Every settings change is logged in ml_config_changes with the time, the old value, the new value and who made it.
> 5. GET /health returns 200 when both databases can be read, and 503 otherwise.
> 6. Structured logs for every request and job.

**How to check it is done:** "Change a setting: it takes effect within a minute
and is logged. Break the file: the service keeps running. Stop a database:
/health returns 503."

Against the 22 Sep row, v1.3 changes part 1 (no events in the API; the sync is
a job) and part 2 (`sync` replaces `events`). The Change register says it in one
line: *"v1.2, 28 Sep 2026, ENG-02: Module events renamed sync; no event
endpoint."* Parts 3–6 are unchanged, but part 3 follows the v1.3 Settings sheet.

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–6 are the Build List's parts, and A–C are extras.

### 1. Two modes: API and jobs: built

- **API mode:** `uvicorn reco.main:app`, unchanged, so the Dockerfile still works.
  - Routers today: `health` and `profiles` (the M1 demo views). There is **no event endpoint** (SD-01; DS-017 v2.5 §7). The router `reco/api/events.py` was removed on 1 Oct.
  - `POST /v1/recommendations` and the fraud case API arrive with ENG-06 and ENG-21.
- **Jobs mode:** `python -m reco.jobs <job>` (`reco/jobs/__main__.py`). It opens both connections, ensures the engine collections and indexes, loads the settings once, runs the job and exits.
  - Exit code 0 on success, 1 on failure, so a scheduler can see the result.
  - `--list` prints the jobs.
- **Jobs registered now:**

  | Job | Runs | From |
  |---|---|---|
  | `interest` | The M1 refresh for both Wave 1A methods (`recency_decay`, `time_windows`) | M1 demo |
  | `sync` | One engine sync pass over `postevents`, `orders`, `recommendationrequests` | ENG-04 |
  | `sync_loop` | A pass every `events.sync_interval_minutes` | ENG-04 |
  | `sync_check` | The sync lag alert on its own | ENG-04 |
  | `reconcile_sync` | Yesterday's reconciliation (IST day) | ENG-04 |

  The 22 Sep `reconcile_events` job (count-based, against the old collections) was removed on 1 Oct.
- **Later:** ENG-07 adds the 2 AM IST scheduler and the other nightly jobs to `JOBS`.
- **Why two modes (SD-01):** heavy work never runs inside a request, and a failed job never touches the feed. SD-01 (v1.6) lists the engine sync every 5 minutes among the scheduled jobs.

### 2. The twelve modules and the two gatekeepers: built

The package holds exactly the twelve modules of SD-05 (v1.6), each with a
docstring stating its job and the items that fill it:

`api`, `config`, `slots`, `store`, `platform`, `eligibility`, `ranking`,
`fallback`, **`sync`**, `jobs`, `fraud`, `monitoring`.

**`events` → `sync` (1 Oct, v1.3).** The 22 Sep row named an `events` module,
which ENG-04 (22 Sep version) filled with the event ingest (`reco/events/ingest.py`)
and the count-based reconciliation (`reco/events/reconcile.py`). Both were
removed with `POST /v1/events`. `reco/sync/` replaces the package. SD-05 v1.6
gives its job: *"Reads postevents, orders, recommendationrequests and
rec_serve_log by updated_at, and posts, users, businessregisters, products and
productvariants in full every 15 minutes, through the platform module. Writes
the engine copies through the store module. Keeps checkpoints, runs the backfill
and the daily reconciliation."* ENG-04 fills it (`copies.py`, `run.py`,
`reconcile.py`).

The original reorganisation (24 Sep) moved the M1 demo code into the modules:

| Moved from | To |
|---|---|
| `reco/config.py` | `reco/config/__init__.py` (a package; parts 3–4 add to it) |
| `reco/data/readers.py`, `ids.py`, `categories.json`; `reco/domain/categories.py`, `event_contract.py` | `reco/platform/` (`event_contract.py` renamed `demo_event_contract.py`) |
| `reco/data/writers.py`; `reco/domain/scores.py` | `reco/store/` |
| `reco/methods/*`; `reco/domain/events.py` | `reco/slots/interest/` |
| `reco/read_path.py`; `reco/domain/profile.py` | `reco/fallback/` |
| `reco/refresh.py` | `reco/jobs/refresh.py` |
| `reco/domain/service_contract.py` | `reco/api/contract.py` (to be reworked to DS-017 v2.5 by ENG-06) |
| `reco/data/mongo.py` (both clients) | Split: `reco/platform/connection.py` (platform, read-only) and `reco/store/connection.py` (engine) |
| `reco/data/`, `reco/domain/`, `reco/methods/`, `reco/eval/` (empty) | Removed |
| `reco/events/` (ingest, reconcile), `reco/api/events.py` | Removed 1 Oct; `reco/sync/` added |

All moves used `git mv`, so history is kept.

**Gatekeepers (SD-06):**
- The platform client exists only in `reco/platform/connection.py`, so nothing outside `platform` can reach SOCO's data. The sync reads the platform through `platform`, and writes its copies through `store`.
- The entry points (`main.py`, `api/health.py`, `jobs/__main__.py`) may open, close and ping it, and nothing else.
- Writes still pass through the `ml_`-only guard in `reco/store/writers.py`.
- **Demo profile exception:** `platform.connection.source_db` reads `ml_demo_*` sources through the engine connection (read only), because the demo generator wrote them there. ENG-10 keeps this profile.

**Enforced by `tests/test_module_layout.py`** (reads the source, needs no database, 16 tests):
- exactly the twelve packages (`MODULES`, now with `sync`), each with a docstring;
- no import of the platform connection, and no use of `app_db`, outside `platform` and the three entry points;
- the entry points use only `init_client`, `close_client`, `verify_database` and `ping` on it;
- no database write call (`insert_*`, `update_*`, `delete_*`, `bulk_write`, `create_index`, `drop`…) outside `store`.

### 3. Versioned settings file with reload: built

**The file:** `settings/engine.toml`, TOML **(choice: read with the standard
library's `tomllib`, allows comments)**. It holds every value on the v1.3
Settings sheet, grouped as the sheet groups them, each commented with its item
and allowed range. It is committed at **`config_version = "2"`** (1 Oct; it was
`"1"` for the 22 Sep sheet), and its values equal the sheet's (a test asserts
this).

**How many values (counted from the code, 1 Oct):** **155** settings in 14
sections, plus the `config_version` and `changed_by` header. 153 are single
values; the other two are the maps `lists.category_map` and
`lists.status_spellings`, which start empty, so `Tunables().values()` lists 153
keys. The 22 Sep file held 144.

**What v1.3 changed in the file (1 Oct):**

| Section | Change | Sheet row |
|---|---|---|
| `[serving]` | `surface_mode_feed`, `surface_mode_product`: `off` \| `internal` \| `live` (was off \| live). Internal = engine lists for `lists.test_accounts` only, 503 to everyone else (SD-10) | Serving: Surface modes (ENG-06, ENG-24) |
| `[events]` | **Added** `sync_interval_minutes = 5` (1–15), `sync_overlap_minutes = 2` (fixed), `sync_lag_alert_minutes = 15` (fixed) | Events: Engine sync (ENG-04) |
| `[events]` | **Removed** `forward_batch_max`, `forward_timeout_seconds`: the SOCO_BE forward is retired | — |
| `[events]` | `session_background_minutes` renamed **`session_away_minutes = 30`** (fixed): a new session after 30 minutes or more away, background or closed | Session (APP-01) |
| `[events]` | `retention_days = 365` (fixed) now means engine copies kept at least 365 days from the original event time (SD-29) | DB-01, ENG-04 |
| `[filters]` | **Added** `eligibility_refresh_minutes = 15` (5–60) | Filters: Eligibility refresh (ENG-27, ENG-08) |
| `[lists]` | **New section** (below) | Lists |

**The `[lists]` section** (`Lists` in `reco/config/tunables.py`). The sheet
says these are maintained by Allen; every change is a new `config_version`,
logged in `ml_config_changes` like any other.

| Key | Holds | Starts |
|---|---|---|
| `category_map` | Platform category name (any case) → one of the 23. Unmapped categories are reported daily and left out of category scoring, never guessed | `{}` |
| `status_spellings` | Stored spelling → the value the engine compares with, ignoring case | `{}` |
| `order_status.delivered`, `.cancelled`, `.rejected`, `.return_requested`, `.returned` | The exact stored `order_status` values (AS-23, checked by ENG-23 V8) | `Delivered`, `Cancelled`, `Rejected`, `Return Requested`, `Returned` |
| `exemptions` | Accounts flagged but never actioned (ENG-21, X-21) | `[]` |
| `test_accounts` | Accounts left out of learning, measurement and fraud; the accounts internal mode serves | `[]` |

Each `exemptions` / `test_accounts` entry is an `AccountEntry`, as the sheet
lists: `account_id` (a 24-character hex id, lower-cased), `reason`, `expiry`
(a date) and `changed_by`. A malformed id or a blank reason or author rejects
the file. The Settings sheet tags the Lists rows ENG-03, ENG-21 and ENG-06;
ENG-29 builds the adapters that use them.

**The model:** `reco/config/tunables.py`, `Tunables`. Its defaults *are* the
Settings sheet's starting values. Validation follows the sheet:

| Sheet says | Enforced as |
|---|---|
| An allowed range | Pydantic `ge`/`le` (`between(value, low, high)`) |
| Fixed for Wave 1A, no range | Range of one value (`fixed(value)`) |
| "Sum to 1" | Model validators on each weight group (ranking, retrieval shares, product, opportunity, promoter, window weights) |
| off / internal / live | `Literal["off", "internal", "live"]`: no shadow mode (SD-10) |

- **Unknown keys** are refused (`extra="forbid"`).
- **Where the pack is silent or mixed (choices):**
  - The promoter slot's method names are `shrinkage` and `cohort_percentile`.
  - Both surfaces start `off`, because the sheet's value is "live, each only if its checks pass" and none has passed (ENG-24).
  - The sheet's Engine sync row gives a range (1 to 15 minutes) and also says "Fixed for Wave 1A". The interval is coded `between(5, 1, 15)` so the range can be used; the overlap and lag alert are `fixed`. The rule it must satisfy: the launch value is 5 minutes.

**Rules (`reco/config/live.py`, pure, no database):**
- `read_file(path)`: never raises. It reports a fault for a missing file, invalid TOML, or any value outside the sheet (naming the setting).
- `decide(in_force, candidate)`:
  - **accept** when `config_version` changed;
  - **refuse** when values changed but `config_version` did not (SD-07: every change needs a new version);
  - **nothing to do** when both are unchanged.
- `current()`: the `Tunables` in force. Read at the moment of use.
- `RELOAD_SECONDS = 30`: the sheet asks for at least once a minute (SD-09).

**Keeping it in force (`reco/config/sync.py`):**
- **`load_at_start`**, run at API startup and at the start of every job:
  1. Use the file if good.
  2. Else use the last good version recorded in `ml_config_changes`.
  3. Else use the Settings-sheet defaults.

  A good file with the same version as the last record but different values is refused, and the recorded version is used. Because the last good version is recorded in `ml_config_changes`, "no good version has ever loaded" survives restarts, not just the current process.
- **`reload`**, every 30 s in the API (`reload_loop`, a background task started and cancelled in the lifespan):
  - skips an unchanged file (by SHA-256 fingerprint);
  - logs a broken file once, at ERROR, and keeps the settings in force;
  - applies and records a good change.
- **Resilience:** if the engine database can't be read or written, the file still goes into force in memory. Only the record is skipped, and the next process to start records it.

`reco/config/sync.py` is the *settings* sync. It is not the `reco/sync` module
(the engine sync, ENG-04).

**Who reads it:**
- `reco/jobs/refresh.py`, `reco/fallback/read_path.py` and `reco/api/profiles.py` read `live.current()`.
- The engine sync (`reco/sync/run.py`, ENG-04) reads `events.sync_interval_minutes`, `sync_overlap_minutes` and `sync_lag_alert_minutes`; the expiry index on the engine copies (`reco/store/writers.py`) reads `events.retention_days`.
- The M1 methods still take the `P-02`…`P-27` map they were written for. `Tunables.m1()` builds it from the sheet's values.
- `refresh(tunables=...)` lets a caller pin values. Only the demo-dataset tests do that, with DS-007.

**Environment `Settings` (`reco/config/__init__.py`):** every DS-007 tunable
field, `EventWeights`, `tunables()` and the `P02_…`–`P27_…` environment variables
are removed. They're replaced by `settings_file` (`SETTINGS_FILE`, default
`settings/engine.toml`). Tunables now live only in the file (SD-07); the
environment holds only connections, tokens, the environment name, the data
profile and logging (SD-08).

### 4. Settings changes logged in `ml_config_changes`: built

`reco/store/writers.py`:
- `record_config_change(settings, record) -> bool` inserts one record.
- `read_latest_config_change(settings)` returns the newest record by `changed_at`.
- `ensure_engine_collections` adds two indexes:
  - `uniq_config_version` (unique), so when the API and a job both see a new version, only one records it; the other gets `False`, which is expected;
  - `changed_at`.

Each record holds:

| Field | Holds |
|---|---|
| `changed_at` | UTC time of the change |
| `config_version`, `previous_version` | The new version and the one it replaced |
| `changed_by` | From the file: **who** made the change (choice: the file names its author) |
| `environment` | dev, test or production |
| `source` | The file path |
| `changes` | `[{key, old, new}]` per changed value, keys dotted (`interest.stale_after_hours`) |
| `values` | The full snapshot, used to recover the last good version |

Each accepted change is also logged: `settings changed`, with `changed_keys` and `recorded`.
List edits (exemptions, test accounts, the category map) are recorded the same way.

### 5. `GET /health`: 200 or 503: built

`reco/api/health.py` pings both connections (SD-26, SD-28):

- **200:** both answer. The body has `"status": "ok"`.
- **503:** either fails. The body has `"status": "unavailable"`.
- The body reports `mongo: {app, ml}` either way, plus `environment`, `model_version`, `data_profile` and the source/target collections.

Before this, `/health` always returned 200.

### 6. Structured logs for every request and job: built

`reco/monitoring/logs.py`:

- **`configure_logging(settings)`:** replaces the root handler with one JSON object per line on stderr. Every line has these fields:
  - `ts`: UTC, milliseconds, `Z`;
  - `level`;
  - `logger`;
  - `message`;
  - `env`.

  Any `extra=` field becomes its own key, and exceptions go under `error`. Used by the API lifespan and jobs mode.
- **`log_request`:** HTTP middleware, registered in `main.py`. It writes one `reco.request` line per request with `method`, `path`, `status` and `duration_ms`. A handler that raises is still logged, as status 500.
- **`job_run(job, **fields)`:** an async context manager that logs `job started`, then `job finished` (`outcome: succeeded`, `duration_ms`) or `job failed` (level ERROR, with the error). It re-raises, so the failure still reaches the caller. Every job above, the sync jobs included, runs inside it.

Live output on dev, 1 Oct 2026:

```json
{"ts": "2026-10-01T09:06:04.405Z", "level": "INFO", "logger": "reco.request", "message": "request", "env": "dev", "method": "GET", "path": "/health", "status": 200, "duration_ms": 51.2}
```

Uvicorn's own access log still prints in its own format. The `reco.request`
line is the structured record.

### A. Extra: import rewrite and test updates: done

- **Imports:** every import in `reco/`, `scripts/` and `tests/` points at the new paths.
- **Collection-name test:** `test_collection_config.py` now exempts the `reco/config` package, not the old `config.py`.
- **Method-contract test:** `test_method_contract.py` forbids scoring methods from importing either connection.
- **Version-free tests (1 Oct):** `tests/test_tunables.py` reads the committed `config_version` (`V`) and uses the next one (`NEXT`), and `scripts/run_checklist.sh` §2 does the same. Neither pins a number, so raising the version never breaks them.

### B. Extra: behaviour changes from the Settings sheet: done

Moving M1 from DS-007 to the Settings sheet changes these values. The pack sets them:

| Value | Before (DS-007) | Now (Settings sheet) | Effect today |
|---|---|---|---|
| Score too old (rung 4) | 24 h | **48 h** | A score is stale only when older than 48 h |
| Not interested / hide | 0 | **−5** | No effect yet: no reader produces those events. ENG-10 wires it |
| Search | 3 | **0** (no sheet value; E11 deferred) | A search event scores nothing |
| Like, save, share, comment, business follow | absent | 3, 4, 4, 4, 5 | In the file; M1 reads them in ENG-10 |
| Method split | P-22, 90% incumbent | 50 per slot, share on method two | Used by ENG-05 |

**Tests changed to match:**
- Stale-score cases in `test_read_path.py` use 60-hour-old scores, past the new 48 h.
- `test_method_a_expected.py`, `test_event_contract.py` and `test_refresh.py` compare against Kala's demo dataset, whose expected answers were generated with DS-007. They pin `DS007_M1_TUNABLES`, labelled as such in `tests/conftest.py`.
- Every other test uses `m1_tunables({...})`: the Settings sheet with named, validated changes.

### C. Extra: `POST /v1/events` retired; the serving token moved: done (1 Oct)

- **Removed:** `reco/api/events.py` (the endpoint), `reco/events/ingest.py`, `reco/events/reconcile.py`, the `reconcile_events` job, their writers in `reco/store/writers.py`, and `tests/test_events_ingest.py`, `tests/test_events_reconcile.py`. DS-017 v2.5 §7: *"POST /v1/events, INGEST_TOKEN on events and the queued forwarding in v2.2 are retired."* X-02.
- **The token check:** `reco/api/auth.py`, `token_ok(settings, authorization)`. It accepts `Authorization: Bearer <INGEST_TOKEN>`, compared in constant time (`hmac.compare_digest`). With no token set, every call is refused and the fault logged. The name `INGEST_TOKEN` is kept for the **serving token** that SOCO_BE sends on `POST /v1/recommendations` (DS-017 v2.5 §3, AS-04). No route uses it yet: ENG-06 wires it to `POST /v1/recommendations`. The fraud case API uses its own `ADMIN_TOKEN` (ENG-21).
- **Scripts:** `scripts/generate_ingest_token.py` describes the token as the serving token. `scripts/show_events.py` now shows what the sync has copied (by source and E code), `ml_orders`, and each source's checkpoint and last success from `ml_sync_state`.

---

## 3. Configuration reference

| Variable | Meaning | Default |
|---|---|---|
| `SETTINGS_FILE` | Path to the settings file, relative to the repo root unless absolute | `settings/engine.toml` |
| `INGEST_TOKEN` | The serving token: SOCO_BE sends it as a bearer token on `POST /v1/recommendations` (DS-017 v2.5 §3). Server environment only (SD-08). Empty = every call refused | empty |

Removed: `P02_QUALIFIED_VIEW_SECONDS` … `P27_COLD_START_WINDOW_DAYS`. Tunables
come only from the file.

**Changing a setting:**
1. Edit `settings/engine.toml` inside the value's range.
2. Raise `config_version` (it is `"2"` now, so the next is `"3"`) and set `changed_by`.
3. Save. The API picks it up within 30 seconds; jobs pick it up at their next start.

The same steps apply to the `[lists]` entries (an exemption, a test account, a
category mapping).

---

## 4. Tests

| File | Covers |
|---|---|
| `tests/test_module_layout.py` | Part 2: twelve modules (with `sync`), gatekeepers, write calls only in `store` (16 tests) |
| `tests/test_health.py` | Part 5: 200 when both answer; 503 for each failure combination; environment in the body (5 tests) |
| `tests/test_logs.py` | Parts 1 and 6: JSON fields, extras, request lines (including a raising handler), job start, finish and failure, `--list` (7 tests) |
| `tests/test_tunables.py` | Parts 3 and 4: the file holds exactly the sheet's values; ranges, fixed values, sums; surfaces start off; file faults; the decision rules; load and reload (change, broken file, same-version refusal, defaults, last-good from the database, no double record); the unique change log on Atlas (54 tests, one of them on Atlas) |
| `tests/test_config.py` | The environment settings hold no tunables; old `P…` variables are ignored (6 tests) |

**Result on 1 Oct 2026 (laptop, after the realignment):**
- Whole unit suite (`-m 'not mongo'`): **509 passed**, 1 skipped (pre-existing).
- The five ENG-02 files above, with the Atlas test: **88 passed**.

Earlier result, 24 Sep 2026 (22 Sep row): 432 unit tests passed, 1 skipped, and
31 Atlas database tests passed.

Not yet covered by a dedicated test: the `[lists]` entry rules (`AccountEntry`)
and `reco/api/auth.py`. Both are exercised when ENG-06 and ENG-29 use them.

**The ENG-02 check**, run live on dev:
- **24 Sep 2026** (record `Tracing/checks/ENG-02_2026-09-24.md`): a settings change was picked up in 29 s and recorded with old, new and who; a broken file was rejected and the service kept answering; with the engine database unreachable, `/health` returned 503.
- **1 Oct 2026**, after the realignment, the `scripts/run_checklist.sh` §2 steps against a throwaway settings copy and a throwaway database: `/health` 200; 503 with the engine database unreachable; a `reco.request` line per request; version 2 → 3 (`interest.popularity_window_days` 30 → 45, by "Demo") in force and recorded within 30 s; a broken file rejected while `/health` stayed 200; a change without a new version refused. All passed.

---

## 5. Runbook

```bash
.venv/bin/python -m uvicorn reco.main:app --port 8100   # API mode
.venv/bin/python -m reco.jobs --list                     # jobs mode: list
.venv/bin/python -m reco.jobs interest                   # jobs mode: M1 refresh, both methods
.venv/bin/python -m reco.jobs sync                       # jobs mode: one engine sync pass (ENG-04)
curl -i http://127.0.0.1:8100/health                     # 200, or 503 if a database is down
```

Settings changes: see §3. The change history is in `ml_config_changes`. Print it with:

```bash
.venv/bin/python scripts/show_config_changes.py                    # the engine database in .env
ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_config_changes.py
```

One line per version (when, previous → new, who), then each changed key with
its old and new value. Read-only.

**Whole checklist:** `bash scripts/run_checklist.sh`, §2 is this item. It uses
ports 8190/8191 and the throwaway database `reco_demo`, and reads the committed
`config_version` rather than assuming one.

---

**Re-checked:** 28 Sep 2026 on dev, all checks pass (`Tracing/checks/Checklist_2026-09-28.md`);
29 Sep 2026, §2 9/9 (`Tracing/checks/Checklist_2026-09-29.md`); 1 Oct 2026 after the
v1.3 realignment, see §4.

## 6. Open

| Open item | Needs |
|---|---|
| Re-run the check on **test**; then mark Passed | The test server (ENG-01, DB-13) |
| Copy `Tracing/checks/ENG-02_2026-09-24.md` to the shared "Wave1A checks" folder | Access to the folder (Sanjai) |
| Wire `token_ok` to `POST /v1/recommendations` | ENG-06 |
| Fill `[lists]`: the category map, status spellings, test accounts and exemptions | ENG-29, ENG-23 V8; test accounts from Aravinth for internal mode |

---

## 7. Files changed

| File | Change |
|---|---|
| `reco/**` | Moved into the twelve modules (see part 2) |
| `reco/platform/connection.py`, `reco/store/connection.py` | New: the split connections |
| `reco/api/health.py` | 200/503 |
| `reco/monitoring/logs.py` | New: JSON logs, request middleware, job logging |
| `reco/jobs/__main__.py` | New: jobs mode. 1 Oct: `reconcile_events` removed; ENG-04 registers the sync jobs |
| `reco/main.py` | JSON logging, request middleware, split connections. 1 Oct: the events router removed |
| `reco/*/__init__.py` | Docstrings for the twelve modules |
| `reco/sync/__init__.py` | New (1 Oct): the `sync` module, replacing `events` |
| `reco/events/`, `reco/api/events.py` | Removed (1 Oct): `POST /v1/events` retired |
| `reco/api/auth.py` | New (1 Oct): `token_ok`, the serving-token check |
| `settings/engine.toml` | New: the settings file, version 1. 1 Oct: version 2, the v1.3 Settings sheet |
| `reco/config/tunables.py`, `live.py`, `sync.py` | New: the model, the rules, load and reload. 1 Oct: off/internal/live, sync and eligibility settings, `Lists`, `AccountEntry`, `OrderStatusValues` |
| `reco/config/__init__.py` | DS-007 tunables removed; `settings_file` added. 1 Oct: `ingest_token` described as the serving token |
| `reco/store/writers.py` | `record_config_change`, `read_latest_config_change`, `ml_config_changes` indexes. 1 Oct: the event-ingest writers removed |
| `reco/jobs/refresh.py`, `reco/fallback/read_path.py`, `reco/api/profiles.py` | Read the settings in force |
| `Tracing/checks/ENG-02_2026-09-24.md` | New: the check result |
| `.env.example` | `SETTINGS_FILE`. 1 Oct: `INGEST_TOKEN` described as the serving token |
| `scripts/show_config_changes.py` | New (25 Sep): prints the change log |
| `scripts/generate_ingest_token.py`, `scripts/show_events.py` | 1 Oct: serving token; what the sync has copied |
| `scripts/run_checklist.sh` | §2: the ENG-02 check; 1 Oct: no fixed settings version |
| `scripts/*.py` | New import paths and split connections |
| `tests/test_module_layout.py`, `test_health.py`, `test_logs.py`, `test_tunables.py` | New. 1 Oct: `sync` in `MODULES`; no pinned version |
| `tests/test_events_ingest.py`, `tests/test_events_reconcile.py` | Removed (1 Oct) |
| `tests/test_config.py` | Rewritten for the environment settings only |
| `tests/conftest.py` | `m1_tunables`, `put_in_force`, `DS007_M1_TUNABLES`; the Settings-sheet defaults are put back in force around every test |
| Other `tests/*.py` | New import paths; `test_collection_config.py` exempts `reco/config`; `test_method_contract.py` forbids both connections |

## 8. Demo

The live demo script, in plain language, is the Obsidian note
`obsidian/Demos/Demo - ENG-02.md`. It runs against a throwaway settings copy and
the throwaway database `reco_demo`. Rehearsed again on 1 Oct 2026 after the
realignment: 200 → 503 with the engine database unreachable → settings change
recorded (version 2 → 3, 30 → 45, by "Demo") → broken file rejected, still 200 →
unversioned change refused. The throwaway database was dropped afterwards.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks, with those of every other finished item. It prints PASS/FAIL per line and cleans up after itself.
