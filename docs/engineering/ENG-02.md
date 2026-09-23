# ENG-02: Service skeleton, settings and health check

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | ENG-01 (built on dev; its server parts come later) |
| **Needed by** | ENG-03, ENG-04, ENG-05, ENG-07 |
| **Status** | **In progress** (24 Sep 2026). Parts 1, 2, 5 and 6 built on dev; parts 3 and 4 (the settings file) next |
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

Numbered as in the Obsidian note: 1–6 are the Build List's parts, and A is an extra.

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

### 3. Versioned settings file with reload: next

Not started yet. See §7.

### 4. Settings changes logged in `ml_config_changes`: next

Not started yet; built with part 3.

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

---

## 3. Configuration reference

No new environment variables yet. Parts 3–4 add the settings file path.

---

## 4. Tests

| File | Covers |
|---|---|
| `tests/test_module_layout.py` | Part 2: twelve modules, gatekeepers, write calls only in `store` (16 tests) |
| `tests/test_health.py` | Part 5: 200 when both answer; 503 for each failure combination; environment in the body |
| `tests/test_logs.py` | Parts 1 and 6: JSON fields, extras, request lines (including a raising handler), job start, finish and failure, `--list` |

Result on 24 Sep 2026: **398 unit tests passed** and 1 skipped (pre-existing).
Before part 6: **30 Atlas database tests passed**.

A live run on dev (`uvicorn reco.main:app`) returned `/health` 200 with both
connections true, and wrote the JSON request lines above.

---

## 5. Runbook

```bash
.venv/bin/python -m uvicorn reco.main:app --port 8100   # API mode
.venv/bin/python -m reco.jobs --list                     # jobs mode: list
.venv/bin/python -m reco.jobs interest                   # jobs mode: M1 refresh, both methods
curl -i http://127.0.0.1:8100/health                     # 200, or 503 if a database is down
```

---

## 6. Open

| Open item | Needs |
|---|---|
| Part 3: settings file, reload, last-good, defaults | Next |
| Part 4: `ml_config_changes` log | With part 3 |
| Run the ENG-02 check on dev and save `ENG-02_<date>` | Parts 3–4 |

---

## 7. Plan for parts 3 and 4

Everything below follows the pack. Where the pack is silent, the choice is
marked **(choice)**.

- **One file:** `settings/engine.toml` **(choice: TOML, read with the standard library's `tomllib`, allows comments)**. It holds every value on the Build List's Settings sheet, grouped as the sheet groups them, and each value is validated against the sheet's *Allowed range*.
- **Versioned:** the file carries `config_version` and `changed_by` **(choice: how "who made it" is recorded)**. A changed file that keeps the same `config_version`, or has no `changed_by`, is treated as broken.
- **Reload:** the API checks the file every 30 seconds (the sheet asks for at least once a minute); jobs read it at the start of each run.
  - **Broken file:** keep the last good version and log the fault.
  - **No good version ever:** use the Settings-sheet defaults.
- **`ml_config_changes`:** one document per accepted change, holding the time, `config_version`, `changed_by`, and each changed key with its old and new value, plus a full snapshot. A restart with a broken file can then recover the last good version from the database.
- **Secrets and connections stay in the environment (SD-08):** URIs, database names, `ENGINE_ENV`, `DATA_PROFILE`, `LOG_LEVEL`. The old `P02_…`/`P27_…` environment tunables are removed. Tunables live only in the file (SD-07).
- **M1 behaviour changes** that follow from moving to the Settings sheet's values:

  | Value | Before (DS-007) | Settings sheet |
  |---|---|---|
  | Score too old (rung 4) | 24 h | **48 h** |
  | Not interested / hide weight | 0 | **−5** (range −20 to 50) |
  | Search weight | 3 | **removed** (E11 deferred) |
  | Like, save, share, comment, business follow | not present | **3, 4, 4, 4, 5** (in the file now; M1 reads them in ENG-10) |
  | Method split | 90% incumbent (P-22) | **50** per slot, share on method two (ENG-05 uses it) |

  Tests that pin DS-007 values are updated to the Settings sheet.

---

## 8. Files changed (so far)

| File | Change |
|---|---|
| `reco/**` | Moved into the twelve modules (see part 2) |
| `reco/platform/connection.py`, `reco/store/connection.py` | New: the split connections |
| `reco/api/health.py` | 200/503 |
| `reco/monitoring/logs.py` | New: JSON logs, request middleware, job logging |
| `reco/jobs/__main__.py` | New: jobs mode |
| `reco/main.py` | JSON logging, request middleware, split connections |
| `reco/*/__init__.py` | Docstrings for the twelve modules |
| `scripts/*.py` | New import paths and split connections |
| `tests/test_module_layout.py`, `test_health.py`, `test_logs.py` | New |
| Other `tests/*.py` | New import paths; `test_collection_config.py` exempts `reco/config`; `test_method_contract.py` forbids both connections |
