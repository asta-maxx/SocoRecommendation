# ENG-01: Engine server, database and environments

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | DB-02 (new read-only platform login, Aravinth) |
| **Needed by** | DB-12, ENG-02 |
| **Status** | **Waiting** (24 Sep 2026). Code done; dev (laptop) set up and verified. Blocked on Aravinth: test and production servers and clusters (SD-03), DB-02 rotation, then DB-12. Becomes Passed when §6 runs clean on test and production and the result is saved |
| **Spec** | Build List ENG-01; SDA SD-04, SD-06, SD-08, SD-18; DS-017 §2, §7; AS-06, AS-09; X-08 |

---

## 1. What the item requires

From the Build List row:

1. Three environments (dev, test and production), each with its own engine database.
2. The engine database holds every engine collection, all prefixed `ml_`:
   - `ml_events`
   - `ml_user_interest_scores`
   - `ml_product_scores`
   - `ml_promoter_scores`
   - `ml_promoter_scores_monthly`
   - `ml_opportunity_scores`
   - `ml_user_candidates`
   - `ml_fraud_flags`
   - `ml_fraud_cases`
   - `ml_job_runs`
   - `ml_config_changes`
   - `ml_measurements`
3. Deploy in the same private network as SOCO_BE, and give Aravinth the private address for DB-12.
4. Passwords and tokens live only in server environment settings, never in code, the settings file or any shared file.

**Check:** the engine runs in all three environments, and the production engine
reaches the platform database read-only.

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–4 are the Build List's parts, and A–C are extras.

### 1. Three environments, each with its own engine database (`reco/config.py`): done on dev; test and production waiting

- **`ENGINE_ENVIRONMENTS = ("dev", "test", "production")`** (SD-04).
- **`Settings.engine_env`** is read from `ENGINE_ENV`, defaults to `dev`, and is normalised (trimmed, lower case). Any other value fails validation.
- **Engine database name:** when `ML_MONGO_DB` is unset, `Settings.from_env()` uses `soco_engine_<engine_env>`, so two environments never share an engine database by default. An explicit `ML_MONGO_DB` always wins.
- **Model default:** the `Settings` model's own default for `ml_mongo_db` is `soco_engine_dev`. It was `soco`, which equalled the platform database.

### 2. The twelve collections (`reco/data/writers.py`): done on dev

`ENGINE_COLLECTIONS` in `reco/config.py` lists the twelve names. It is the one
place they are written down.

`ensure_engine_collections(settings) -> list[str]`:

- **Idempotent:** lists the existing collections and creates only the missing ones. It returns the names it created.
- **Guarded:** every name passes through `_collection()`, the `ml_`-only write guard, before anything is created. `test_namespace_guard.py` now covers this function too.
- **Creates the `ml_events` indexes** stated in ENG-04 and DS-017 §7:
  - `uniq_event_id`: `{event_id: 1}`, unique. The de-duplication key.
  - `user_time`: `{user_id: 1, server_ts: -1}`. Indexed on user and time.
  - `request_id`: `{request_id: 1}`.
- **No TTL index.** `ml_events` keeps at least 365 days (X-08), and no expiry is added without written agreement between Allen and Aravinth.
- **Other collections** get their indexes with the item that first writes them (ENG-07, ENG-14, ENG-16, ENG-17, ENG-21, ENG-24/25). `ml_user_interest_scores` keeps its existing indexes from `ensure_indexes()`.

### 2 (continued). Startup and health

- **`reco/main.py` lifespan:**
  1. `init_clients`
  2. `verify_databases`
  3. `ensure_engine_collections`
  4. `ensure_indexes`

  A failure in steps 3–4 is logged, not fatal. That behaviour is unchanged from before, and ENG-02 revisits it.
- **Startup log** now includes `env=<engine_env>`.
- **`GET /health`** body now includes `"environment"`. The endpoint still returns 200 regardless of database state; the 200/503 behaviour is ENG-02.

### 3. Deploy next to SOCO_BE; hand over the private address (DB-12): waiting

Not started: there is no server yet (SD-03 hosting, Aravinth). See §4 for where each
environment runs, and §6 for the steps once the server exists.

### 4. Secrets only in the server environment (SD-08): done

- **Before `.env` is loaded:** `_SERVER_ENGINE_ENV` captures `ENGINE_ENV` as the server set it.
- **If the server says `production`:** `load_dotenv()` is **not called**, so `.env` is ignored.
- **If `production` came from `.env`:** `_require_production_env_from_server()` raises `RuntimeError` in `Settings.from_env()`. The server didn't set it, so the credentials beside it probably came from the file too.
- **dev and test** may use `.env`, which stays gitignored.
- **Connection strings stay out of output.** They remain `repr=False`, and neither the setup script nor the error messages print them.

`INGEST_TOKEN` and `ADMIN_TOKEN` are not added yet. They arrive with ENG-04 and
ENG-21 and follow the same rule.

### A. Extra: the engine database is never the platform database (AS-09, SD-06): done

`Settings._engine_db_is_not_the_platform_db` (a model validator) refuses a
configuration where both of these hold:

- `_hosts_of(APP_MONGO_URI) == _hosts_of(ML_MONGO_URI)`: the same server set, **and**
- `APP_MONGO_DB` equals `ML_MONGO_DB`, ignoring case.

How `_hosts_of(uri)` works:

- It strips the scheme (`mongodb://` or `mongodb+srv://`), the `user:password@` part, the path and the options.
- It returns the sorted, lower-cased host list with ports.
- Credentials therefore never enter the comparison or the error message. A test asserts the password isn't in the error.

Why case is ignored: two names differing only in case are one database on a
case-insensitive filesystem, and Atlas refuses to create both.

| Pairing | Result |
|---|---|
| Different clusters, same name | Allowed (the dev setup today: `soco` / `SoCo` on different clusters) |
| Same cluster, different name | Allowed |
| Same cluster, same name | Refused at startup |

### B. Extra: setup script (`scripts/setup_engine_db.py`): done

Run once per environment. It is idempotent.

```bash
ENGINE_ENV=dev  .venv/bin/python scripts/setup_engine_db.py
ENGINE_ENV=test .venv/bin/python scripts/setup_engine_db.py
```

It:

- prints the environment, and each database's name and hosts (never a URI);
- creates the collections and indexes;
- counts the collections present;
- pings the platform database.

It exits 0 only if all twelve are present and the platform ping succeeds.

Output on dev, 24 Sep 2026:

```
environment      dev
engine database  SoCo on soco.4b7z1ko.mongodb.net
platform (read)  soco on nex-dev.cob9whd.mongodb.net
created          ml_events, ml_product_scores, ml_promoter_scores, ml_promoter_scores_monthly, ml_opportunity_scores, ml_user_candidates, ml_fraud_flags, ml_fraud_cases, ml_job_runs, ml_config_changes, ml_measurements
engine check     12 of 12 collections present
platform ping    ok
```

`ml_user_interest_scores` already existed from the M1 build.

---

## 3. Configuration reference

| Variable | Meaning | Default | Production |
|---|---|---|---|
| `ENGINE_ENV` | `dev`, `test` or `production` | `dev` | Must be set in the server environment |
| `APP_MONGO_URI` | Platform database connection (read-only login, DB-02) | localhost | Server env only |
| `APP_MONGO_DB` | Platform database name | `soco` | Server env only |
| `ML_MONGO_URI` | Engine database connection | localhost | Server env only |
| `ML_MONGO_DB` | Engine database name | `soco_engine_<ENGINE_ENV>` | Server env only |
| `MONGO_TIMEOUT_SECONDS` | Server selection timeout | 10 | — |

---

## 4. Environments

### 4.1 Where each environment runs (decided 24 Sep 2026)

The pack fixes that there are three environments, each with its own engine
database (SD-04), and that production sits in SOCO_BE's private network (SD-03,
AS-06). It does not say where each one physically runs. We decided:

| | dev | test | production |
|---|---|---|---|
| **Runs on** | Allen's laptop | A server | A server in SOCO_BE's private network (SD-03) |
| **Engine database** | `SoCo` on `soco.4b7z1ko` (build cluster) | Own database on its own Atlas cluster, created later | Own database on its own Atlas cluster, created later |
| **Platform data it reads** | `soco` on `nex-dev.cob9whd` | A copy of platform data, or constructed data (DB-13), never live SOCO data | The launch database, through the DB-02 read-only login |
| **Called by** | Nobody but Allen | Test SOCO_BE and test app build (DB-13) | Production SOCO_BE and the admin panel |
| **Settings and secrets** | `.env` | Server environment (so test behaves like production) | Server environment only (SD-08; enforced in code) |
| **State** | Set up, 12/12 collections | Waiting: cluster, server, DB-13 | Waiting: cluster, server, DB-02, DB-12 |

### 4.2 Conditions that go with this decision

- **Keep test and production apart.** Use separate servers, or at least separate containers with resource limits. The ENG-20 load test runs on test and must not slow production.
- **Test never reads live SOCO data.** DB-13 requires a copy or constructed data. The checks create their own users, orders and blocks.
- **Put production's engine database near its server.** The production cluster goes in the same cloud region as the production server. Every request reads it within the 200 ms p95 budget (SD-25).
- **Dev reaches Atlas over the internet.** The laptop's IP must be on the access list of each cluster dev uses. Dev is never in SOCO_BE's network, because nothing calls it.

### 4.3 When the test and production clusters are created

For each of the two environments:

1. Create an Atlas cluster, in the production server's region for production.
2. Create an engine database user with read/write on that environment's engine database only.
3. Add the server's address to the cluster's access list.
4. Set the settings in that server's environment, then run the §6 runbook.

---

## 5. Tests

`tests/test_engine_environment.py`:

- The environments list, the default, normalisation, and refusal of unknown values.
- Per-environment default engine database names.
- SD-08: production from a `.env` file is refused; production from the server, and dev/test from a file, are accepted.
- Host parsing for `mongodb+srv://` and multi-host `mongodb://` strings.
- The engine-equals-platform guard: allowed pairings, refused pairings (including different-case names), and the password not appearing in the error.
- The twelve collection names.
- **Against MongoDB:** collections created exactly once, and the `ml_events` indexes present with no expiry.

**Fixture change:** `tests/conftest.py` and `tests/test_readers.py` now give the
platform side its own database (`<TEST_DB>_platform`), as AS-09 requires. The
store tests seed and read `ml_` collections only, so this doesn't change what they test.

Run them:

```bash
.venv/bin/python -m pytest -m "not mongo"      # unit tests, no database
.venv/bin/python -m pytest -m mongo            # uses ML_MONGO_URI, database reco_test
```

The database tests use the throwaway `reco_test` database on the cluster in
`ML_MONGO_URI`. They drop only collections inside it. Never point `ML_MONGO_URI`
at SOCO's cluster while running them.

Result on 24 Sep 2026: **370 unit tests passed, 30 database tests passed** (Atlas
build cluster).

---

## 6. Runbook: bringing up an environment

1. **Engine database:** choose its cluster and name. The name must not be the platform database's.
2. **Engine login:** create an Atlas database user with read/write on **that engine database only**.
3. **Platform login:** use the DB-02 read-only login for the platform database.
4. **Settings:**
   - dev and test: put them in `.env`.
   - production: set them in the server environment, and make sure no `.env` file is present.
5. **Setup:** run `ENGINE_ENV=<env> python scripts/setup_engine_db.py` and expect exit 0 with 12/12.
6. **Start and verify:** start the service and confirm `/health` shows the right `environment` and both connections true.
7. **Production only:** confirm the platform login cannot write (the DB-02 check), and give Aravinth the private address for DB-12.

---

## 7. Open

| Open item | Needs |
|---|---|
| Test and production Atlas clusters and engine databases | Created later (§4.3); test also needs DB-13 |
| Test and production servers | Aravinth (SD-03 hosting) |
| Rotate the platform login's password (DB-02); re-run the §7.1 check afterwards | Aravinth (DB-02) |
| Deploy in SOCO_BE's network; hand over the private address | Aravinth (SD-03 hosting, then DB-12) |
| Save the check result as `ENG-01_<date>` in "Wave1A checks" | The three items above |

### C. Extra: platform login is read-only (checked 24 Sep 2026)

The dev platform login (`APP_MONGO_URI`) was checked **without attempting a write**.
If the login were not read-only, a test write would land in SOCO's data. Instead,
MongoDB was asked which roles and privileges the login holds:

```
db.runCommand({connectionStatus: 1, showPrivileges: true})
```

| Check | Result |
|---|---|
| Authenticated | Yes, `soco` on `nex-dev.cob9whd` |
| Roles | `SocoReadonly@admin` (custom) |
| Data-writing actions (insert, update, remove, create/drop collection or index, collMod, user/role changes) | **None** |
| Other actions | `killCursors` on `soco`: closes the login's own cursors; part of MongoDB's built-in `read` role; cannot change data |
| Reads `users`, `posts`, `postevents`, `orders`, `follows`, `products` | All readable (`users`: 13 documents) |

This login is used for now. When Aravinth rotates it (DB-02), only the password
in `APP_MONGO_URI` changes. Re-run the same check afterwards.

---

## 8. Files changed

| File | Change |
|---|---|
| `reco/config.py` | `ENGINE_ENVIRONMENTS`, `ENGINE_COLLECTIONS`, `engine_env`, `_hosts_of`, engine≠platform validator, SD-08 dotenv handling |
| `reco/data/writers.py` | `ensure_engine_collections` |
| `reco/main.py` | Calls it at startup; logs the environment |
| `reco/api/health.py` | `environment` in the body |
| `scripts/setup_engine_db.py` | New |
| `.env.example` | `ENGINE_ENV`; engine database is its own (AS-09) |
| `tests/test_engine_environment.py` | New |
| `tests/conftest.py`, `tests/test_readers.py`, `tests/test_namespace_guard.py` | Separate platform test DB; guard coverage |
