# ENG-02: Service skeleton, settings and health check

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | ENG-01 (built on dev; its server parts come later) |
| **Needed by** | ENG-03, ENG-04, ENG-05, ENG-07 |
| **Status** | **Built** (24 Sep 2026). All six parts built; the check **passed on dev** (`Tracing/checks/ENG-02_2026-09-24.md`). Becomes Passed when re-run on test (Definitions: every check runs on test) |
| **Spec** | Build List ENG-02; SDA SD-01, SD-05 to SD-10, SD-26 to SD-28; Settings sheet |

---

## 1. What the item requires

From the Build List row:

1. One Python service, in two modes: the API (serving, events, fraud cases, health) and scheduled jobs.
2. Modules: `api`, `config`, `slots`, `store`, `platform`, `eligibility`, `ranking`, `fallback`, `events`, `jobs`, `fraud`, `monitoring`. Only `platform` reads the platform database. Only `store` writes, and only to the engine database.
3. One versioned settings file holding every value on the Settings sheet:
   - reloaded at least once a minute;
   - a broken file keeps the last good version and logs the fault;
   - with no good version at all, the Settings-sheet defaults apply.
4. Every settings change logged in `ml_config_changes`, with the time, the old value, the new value and who made it.
5. `GET /health` returns 200 when both databases can be read, and 503 otherwise.
6. Structured logs for every request and job.

**Check:**
- Change a setting: it takes effect within a minute and is logged.
- Break the file: the service keeps running.
- Stop a database: `/health` returns 503.

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–6 are the Build List's parts, and A–B are extras.

### 1. Two modes: API and jobs: built

- **API mode:** `uvicorn reco.main:app`, unchanged, so the Dockerfile still works.
- **Jobs mode:** `python -m reco.jobs <job>` (`reco/jobs/__main__.py`). It opens both connections, ensures the engine collections and indexes, runs the job and exits.
  - Exit code 0 on success, 1 on failure, so a scheduler can see the result.
  - `--list` prints the jobs.
- **Jobs registered now:** `interest` runs the M1 refresh for both Wave 1A methods (`recency_decay`, `time_windows`).
- **Later:** ENG-07 adds the 2 AM IST scheduler and the other nightly jobs to `JOBS`.
- **Why two modes (SD-01):** heavy work never runs inside a request, and a failed job never touches the feed.

### 2. The twelve modules and the two gatekeepers: built

The package holds exactly the twelve modules of SD-05, each with a docstring
stating its job and the items that fill it.

| Moved from | To |
|---|---|
| `reco/config.py` | `reco/config/__init__.py` (a package; parts 3–4 add to it) |
| `reco/data/readers.py`, `ids.py`, `categories.json`; `reco/domain/categories.py`, `event_contract.py` | `reco/platform/` (`event_contract.py` renamed `demo_event_contract.py`) |
| `reco/data/writers.py`; `reco/domain/scores.py` | `reco/store/` |
| `reco/methods/*`; `reco/domain/events.py` | `reco/slots/interest/` |
| `reco/read_path.py`; `reco/domain/profile.py` | `reco/fallback/` |
| `reco/refresh.py` | `reco/jobs/refresh.py` |
| `reco/domain/service_contract.py` | `reco/api/contract.py` (to be reworked to DS-017 v2.2 by ENG-04/ENG-06) |
| `reco/data/mongo.py` (both clients) | Split: `reco/platform/connection.py` (platform, read-only) and `reco/store/connection.py` (engine) |
| `reco/data/`, `reco/domain/`, `reco/methods/`, `reco/eval/` (empty) | Removed |

All moves used `git mv`, so history is kept.

**Gatekeepers (SD-06):**
- The platform client exists only in `reco/platform/connection.py`, so nothing outside `platform` can reach SOCO's data.
- The entry points (`main.py`, `api/health.py`, `jobs/__main__.py`) may open, close and ping it, and nothing else.
- Writes still pass through the `ml_`-only guard in `reco/store/writers.py`.
- **Demo profile exception:** `platform.connection.source_db` reads `ml_demo_*` sources through the engine connection (read only), because the demo generator wrote them there. ENG-10 keeps this profile.

**Enforced by `tests/test_module_layout.py`** (reads the source, needs no database):
- exactly the twelve packages, each with a docstring;
- no import of the platform connection, and no use of `app_db`, outside `platform` and the three entry points;
- the entry points use only `init_client`, `close_client`, `verify_database` and `ping` on it;
- no database write call (`insert_*`, `update_*`, `delete_*`, `bulk_write`, `create_index`, `drop`…) outside `store`.

### 3. Versioned settings file with reload: built

**The file:** `settings/engine.toml`, TOML **(choice: read with the standard
library's `tomllib`, allows comments)**. It holds all **144 values** on the
Settings sheet, grouped as the sheet groups them, each commented with its item
and allowed range. The file is committed at `config_version = "1"`, and its
values equal the sheet's (a test asserts this).

**The model:** `reco/config/tunables.py`, `Tunables`. Its defaults *are* the
Settings sheet's starting values. Validation follows the sheet:

| Sheet says | Enforced as |
|---|---|
| An allowed range | Pydantic `ge`/`le` (`between(value, low, high)`) |
| Fixed for Wave 1A, no range | Range of one value (`fixed(value)`) |
| "Sum to 1" | Model validators on each weight group (ranking, retrieval shares, product, opportunity, promoter, window weights) |
| off / live | `Literal["off", "live"]`: no shadow mode |

- **Unknown keys** are refused (`extra="forbid"`).
- **Where the pack is silent (choice):**
  - The promoter slot's method names are `shrinkage` and `cohort_percentile`.
  - Both surfaces start `off`, because the sheet's value is "live, each only if its checks pass" and none has passed (ENG-24).

**Rules (`reco/config/live.py`, pure, no database):**
- `read_file(path)`: never raises. It reports a fault for a missing file, invalid TOML, or any value outside the sheet (naming the setting).
- `decide(in_force, candidate)`:
  - **accept** when `config_version` changed;
  - **refuse** when values changed but `config_version` did not (SD-07: every change needs a new version);
  - **nothing to do** when both are unchanged.
- `current()`: the `Tunables` in force. Read at the moment of use.
- `RELOAD_SECONDS = 30`: the sheet asks for at least once a minute.

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

**Who reads it:**
- `reco/jobs/refresh.py`, `reco/fallback/read_path.py` and `reco/api/profiles.py` read `live.current()`.
- The M1 methods still take the `P-02`…`P-27` map they were written for. `Tunables.m1()` builds it from the sheet's values.
- `refresh(tunables=...)` lets a caller pin values. Only the demo-dataset tests do that, with DS-007.

**Environment `Settings` (`reco/config/__init__.py`):** every DS-007 tunable
field, `EventWeights`, `tunables()` and the `P02_…`–`P27_…` environment variables
are removed. They're replaced by `settings_file` (`SETTINGS_FILE`, default
`settings/engine.toml`). Tunables now live only in the file (SD-07); the
environment holds only connections, the environment name, the data profile and
logging (SD-08).

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

### 5. `GET /health`: 200 or 503: built

`reco/api/health.py` pings both connections:

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
- **`job_run(job, **fields)`:** an async context manager that logs `job started`, then `job finished` (`outcome: succeeded`, `duration_ms`) or `job failed` (level ERROR, with the error). It re-raises, so the failure still reaches the caller.

Live output on dev, 24 Sep 2026:

```json
{"ts": "2026-09-23T19:47:06.925Z", "level": "INFO", "logger": "reco.request", "message": "request", "env": "dev", "method": "GET", "path": "/health", "status": 200, "duration_ms": 61.7}
```

Uvicorn's own access log still prints in its own format. The `reco.request`
line is the structured record.

### A. Extra: import rewrite and test updates: done

- **Imports:** every import in `reco/`, `scripts/` and `tests/` points at the new paths.
- **Collection-name test:** `test_collection_config.py` now exempts the `reco/config` package, not the old `config.py`.
- **Method-contract test:** `test_method_contract.py` forbids scoring methods from importing either connection.

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

---

## 3. Configuration reference

| Variable | Meaning | Default |
|---|---|---|
| `SETTINGS_FILE` | Path to the settings file, relative to the repo root unless absolute | `settings/engine.toml` |

Removed: `P02_QUALIFIED_VIEW_SECONDS` … `P27_COLD_START_WINDOW_DAYS`. Tunables
come only from the file.

**Changing a setting:**
1. Edit `settings/engine.toml` inside the value's range.
2. Raise `config_version` and set `changed_by`.
3. Save. The API picks it up within 30 seconds; jobs pick it up at their next start.

---

## 4. Tests

| File | Covers |
|---|---|
| `tests/test_module_layout.py` | Part 2: twelve modules, gatekeepers, write calls only in `store` (16 tests) |
| `tests/test_health.py` | Part 5: 200 when both answer; 503 for each failure combination; environment in the body |
| `tests/test_logs.py` | Parts 1 and 6: JSON fields, extras, request lines (including a raising handler), job start, finish and failure, `--list` |
| `tests/test_tunables.py` | Parts 3 and 4: the file holds exactly the sheet's values; ranges, fixed values, sums; file faults; the decision rules; load and reload (change, broken file, same-version refusal, defaults, last-good from the database, no double record); the unique change log on Atlas |
| `tests/test_config.py` | Rewritten: the environment settings hold no tunables; old `P…` variables are ignored |

Result on 24 Sep 2026: **432 unit tests passed**, 1 skipped (pre-existing), and
**31 Atlas database tests passed**.

**The ENG-02 check** was run live on dev and passed. Full record:
`Tracing/checks/ENG-02_2026-09-24.md`.
- A settings change was picked up in 29 s and recorded with old, new and who.
- A broken file was rejected and the service kept answering.
- With the engine database unreachable, `/health` returned 503.

---

## 5. Runbook

```bash
.venv/bin/python -m uvicorn reco.main:app --port 8100   # API mode
.venv/bin/python -m reco.jobs --list                     # jobs mode: list
.venv/bin/python -m reco.jobs interest                   # jobs mode: M1 refresh, both methods
curl -i http://127.0.0.1:8100/health                     # 200, or 503 if a database is down
```

Settings changes: see §3. The change history is in `ml_config_changes`. Print it with:

```bash
.venv/bin/python scripts/show_config_changes.py                    # the engine database in .env
ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_config_changes.py
```

One line per version (when, previous → new, who), then each changed key with
its old and new value. Read-only.

---

**Re-checked 28 Sep 2026 on dev: all checks pass.** Record: `Tracing/checks/Checklist_2026-09-28.md`.

## 6. Open

| Open item | Needs |
|---|---|
| Re-run the check on **test**; then mark Passed | The test server (ENG-01, DB-13) |
| Copy `Tracing/checks/ENG-02_2026-09-24.md` to the shared "Wave1A checks" folder | Access to the folder (Sanjai) |

---

## 7. Files changed

| File | Change |
|---|---|
| `reco/**` | Moved into the twelve modules (see part 2) |
| `reco/platform/connection.py`, `reco/store/connection.py` | New: the split connections |
| `reco/api/health.py` | 200/503 |
| `reco/monitoring/logs.py` | New: JSON logs, request middleware, job logging |
| `reco/jobs/__main__.py` | New: jobs mode |
| `reco/main.py` | JSON logging, request middleware, split connections |
| `reco/*/__init__.py` | Docstrings for the twelve modules |
| `settings/engine.toml` | New: the settings file, version 1 |
| `reco/config/tunables.py`, `live.py`, `sync.py` | New: the model, the rules, load and reload |
| `reco/config/__init__.py` | DS-007 tunables removed; `settings_file` added |
| `reco/store/writers.py` | `record_config_change`, `read_latest_config_change`, `ml_config_changes` indexes |
| `reco/jobs/refresh.py`, `reco/fallback/read_path.py`, `reco/api/profiles.py` | Read the settings in force |
| `Tracing/checks/ENG-02_2026-09-24.md` | New: the check result |
| `.env.example` | `SETTINGS_FILE` |
| `scripts/show_config_changes.py` | New (25 Sep): prints the change log |
| `scripts/*.py` | New import paths and split connections |
| `tests/test_module_layout.py`, `test_health.py`, `test_logs.py`, `test_tunables.py` | New |
| `tests/test_config.py` | Rewritten for the environment settings only |
| `tests/conftest.py` | `m1_tunables`, `put_in_force`, `DS007_M1_TUNABLES`; the Settings-sheet defaults are put back in force around every test |
| Other `tests/*.py` | New import paths; `test_collection_config.py` exempts `reco/config`; `test_method_contract.py` forbids both connections |

## 8. Demo

The live demo script, in plain language, is the Obsidian note
`obsidian/Demos/Demo - ENG-02.md`. It runs against a throwaway settings copy and
the throwaway database `reco_demo`. Rehearsed on 25 Sep 2026: 200 → settings
change recorded (30 → 45, by "Demo") → 503 with the engine database unreachable.
`reco_demo` was dropped afterwards.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks, with those of every other finished item. It prints PASS/FAIL per line and cleans up after itself.
