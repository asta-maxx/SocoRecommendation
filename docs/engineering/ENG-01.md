# ENG-01: Engine server, database and environments

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | DB-02 (new read-only platform login, Aravinth) |
| **Needed by** | DB-12, ENG-02 |
| **Status** | **Waiting** (24 Sep 2026; realigned to pack v1.3 on 1 Oct 2026). Code done; dev (laptop) set up and verified with 16 of 16 collections. **14 Oct 2026: the test server is available and is set up now; production is set up later (§4.4).** Production still needs its server and cluster (SD-03), DB-02 rotation, then DB-12. Becomes Passed when §6 runs clean on test and production and the result is saved (the check names all three environments and the production read-only login) |
| **Spec** | Build List v1.3 ENG-01; SDA v1.6 SD-04, SD-06, SD-08, SD-18 (and its collections table), SD-29; DS-017 v2.5 §2, §7, §9 step 1; AS-06, AS-09; X-08 |

---

## 1. What the item requires

From the Build List v1.3 row, *What to build*:

> 1. Three environments: dev, test and production, each with its own engine database.
> 2. The engine database holds every engine collection, all prefixed ml_: ml_events, ml_orders, ml_sync_state, ml_item_state, ml_deletions, ml_user_interest_scores, ml_product_scores, ml_promoter_scores, ml_promoter_scores_monthly, ml_opportunity_scores, ml_user_candidates, ml_fraud_flags, ml_fraud_cases, ml_job_runs, ml_config_changes, ml_measurements.
> 3. Deploy in the same private network as SOCO_BE, and give Aravinth the private address for DB-12.
> 4. Passwords and tokens live only in server environment settings, never in code, the settings file or any shared file.

*How to check it is done*:

> The engine runs in all three environments. The production engine reaches the platform database read-only.

### 1.1 What changed in pack v1.3 (realigned 1 Oct 2026)

ENG-01 was built on 24 Sep to the 22 Sep pack, which named **twelve** collections.
The v1.2 change log (28 Sep) adds four for the engine sync: *"ENG-01 | Four new
engine collections. | Engine sync"*. Commit `bc6e82c` brought the code in line:

| | 22 Sep design | v1.3 |
|---|---|---|
| Collections | 12 | 16: adds `ml_orders`, `ml_sync_state`, `ml_item_state`, `ml_deletions` |
| How a copy is identified | unique index `uniq_event_id` on `event_id` | the document `_id` **is** the platform `_id` (DS-017 §7: "unique on the platform _id"); `uniq_event_id` is dropped |
| Time field in indexes | `server_ts` | `created_at`, the original event time |
| Retention | no expiry index (nothing agreed) | expiry index `retention` on `created_at`, 365 days (SD-29, X-08) |
| Index setup | `create_index` only | `_ensure_index` replaces an index whose definition changed |

The full impact on ENG-01 to ENG-04 is in `Tracing/REALIGNMENT_v1.3.md`.

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–4 are the Build List's parts, and A–C are extras.

### 1. Three environments, each with its own engine database (`reco/config/__init__.py`): done on dev; test and production waiting

- **`ENGINE_ENVIRONMENTS = ("dev", "test", "production")`** (SD-04).
- **`Settings.engine_env`** is read from `ENGINE_ENV`, defaults to `dev`, and is normalised (trimmed, lower case). Any other value fails validation.
- **Engine database name:** when `ML_MONGO_DB` is unset, `Settings.from_env()` uses `soco_engine_<engine_env>`, so two environments never share an engine database by default. An explicit `ML_MONGO_DB` always wins.
- **Model default:** the `Settings` model's own default for `ml_mongo_db` is `soco_engine_dev`. It was `soco`, which equalled the platform database.

Unchanged by v1.3.

### 2. The sixteen collections and their indexes (`reco/store/writers.py`): done on dev

`ENGINE_COLLECTIONS` in `reco/config/__init__.py` lists the sixteen names, in the
Build List's order. It is the one place they are written down. What each new one
holds, from the SDA v1.6 collections table (under SD-18):

| Collection | Holds | Filled by |
|---|---|---|
| `ml_orders` | Copies of orders, with `order_status` and `tracking_info` | ENG-04 (engine sync) |
| `ml_sync_state` | Checkpoint and lag per source collection | ENG-04 |
| `ml_item_state` | Current eligibility state of posts, accounts and products | ENG-27 (SD-31) |
| `ml_deletions` | Accounts confirmed deleted on the platform, and when their engine data was purged | ENG-28 |

`ensure_engine_collections(settings) -> list[str]`:

- **Idempotent:** lists the existing collections and creates only the missing ones. It returns the names it created.
- **Guarded:** every name passes through `_collection()`, the `ml_`-only write guard, before anything is created. `test_namespace_guard.py` covers this function too.
- **Copies are keyed on the platform `_id`.** The engine sync (ENG-04) writes each copy with the platform row's `_id` as its own `_id`, so MongoDB's built-in unique `_id_` index is the de-duplication key (DS-017 §7). The 22 Sep unique index `uniq_event_id` on `event_id` is **dropped if present**: `event_id` is an opaque platform value, and keying on it would conflict with the `_id` upsert.
- **`ml_events` indexes:**
  - `user_time`: `{user_id: 1, created_at: -1}`. A user's events, newest first.
  - `request_id`: `{request_id: 1}`. Everything about one served list.
  - `code_time`: `{event_code: 1, created_at: -1}`. One E code over a time window.
  - `retention`: `{created_at: 1}`, `expireAfterSeconds = 31536000` (365 days).
- **`ml_orders` indexes:**
  - `buyer_time`: `{buyer_id: 1, created_at: -1}`.
  - `checkout_id`: `{checkout_id: 1}`. One basket.
  - `retention`: as on `ml_events`.
- **Retention (SD-29, X-08, Settings sheet "Keep event data").** "Engine copies are kept at least 365 days from the original event time, under the engine's own expiry … An update keeps the original event time" (SD-29). The expiry index is on `created_at`, the **original** platform event time, never on `updated_at` or the time of copying. A re-copy therefore never extends or shortens a row's life, and the platform's 90-day expiry (DB-01) never touches the copies. The 365 comes from `events.retention_days` in `settings/engine.toml` (a fixed setting: "Fixed for Wave 1A"), multiplied by 86,400.
- **`_ensure_index(collection, keys, name, **options)`** (new, 1 Oct). MongoDB refuses to create an index under an existing name with a different definition. The dev database `SoCo` still had `user_time` on `server_ts` from the 22 Sep design, so `_ensure_index` compares keys and options, and drops and recreates the index when they differ. Identical indexes are left alone.
- **`ml_config_changes`:** unique `uniq_config_version` and `changed_at` (ENG-02 item 4).
- **Other collections** get their indexes with the item that first writes them: `ml_sync_state` is keyed by source collection (its `_id`), `ml_item_state` and `ml_deletions` with ENG-27 and ENG-28, the score and fraud collections with ENG-07, ENG-14, ENG-16, ENG-17, ENG-21, ENG-24/25. `ml_user_interest_scores` keeps its indexes from `ensure_indexes()`.

### 2 (continued). Startup and health

- **`reco/main.py` lifespan:**
  1. `init_client` for both connections
  2. `verify_database` for both
  3. `ensure_engine_collections`
  4. `ensure_indexes`
  5. load the settings file and start its reload loop (ENG-02)

  A failure in steps 3–4 is logged, not fatal.
- **Startup log** includes `env=<engine_env>`.
- **`GET /health`** body includes `"environment"`. Since ENG-02 it returns 200 only when both databases answer, and 503 otherwise (SD-28).

### 3. Deploy next to SOCO_BE; hand over the private address (DB-12): waiting

Not started: there is no server yet (SD-03 hosting, Aravinth). See §4 for where each
environment runs, and §6 for the steps once the server exists.

### 4. Secrets only in the server environment (SD-08): done

- **Before `.env` is loaded:** `_SERVER_ENGINE_ENV` captures `ENGINE_ENV` as the server set it.
- **If the server says `production`:** `load_dotenv()` is **not called**, so `.env` is ignored.
- **If `production` came from `.env`:** `_require_production_env_from_server()` raises `RuntimeError` in `Settings.from_env()`. The server didn't set it, so the credentials beside it probably came from the file too.
- **dev and test** may use `.env`, which stays gitignored.
- **Connection strings stay out of output.** They remain `repr=False`, and neither the setup script nor the error messages print them.

The tokens follow the same rule (DS-017 v2.5 §2, *Secrets*). `INGEST_TOKEN` is
kept as the name of the **serving** token for `POST /v1/recommendations` now that
`POST /v1/events` is retired (DS-017 §2, *Authentication*); it is generated and
handed to Aravinth privately (DS-017 §9, step 1). `ADMIN_TOKEN` arrives with
ENG-21.

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
- creates the collections and indexes, replacing any index whose definition changed;
- counts the collections present;
- pings the platform database.

It exits 0 only if all sixteen are present and the platform ping succeeds.

Output on a fresh throwaway database, 1 Oct 2026:

```
environment      dev
engine database  reco_demo_eng01 on soco.4b7z1ko.mongodb.net
platform (read)  soco on nex-dev.cob9whd.mongodb.net
created          ml_events, ml_orders, ml_sync_state, ml_item_state, ml_deletions, ml_user_interest_scores, ml_product_scores, ml_promoter_scores, ml_promoter_scores_monthly, ml_opportunity_scores, ml_user_candidates, ml_fraud_flags, ml_fraud_cases, ml_job_runs, ml_config_changes, ml_measurements
engine check     16 of 16 collections present
platform ping    ok
```

The dev database `SoCo`, read on 1 Oct 2026: 16 of 16 present, `ml_events`
indexes `_id_`, `request_id`, `user_time` (on `created_at`), `code_time`,
`retention` (31536000 s); `uniq_event_id` gone. `ml_orders` has `buyer_time`,
`checkout_id` and `retention`.

### C. Extra: platform login is read-only (checked 24 Sep 2026; re-run 1 Oct 2026)

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
| Reads `users`, `posts`, `postevents`, `orders`, `follows`, `products` | All readable (`users`: 15 documents on 1 Oct) |

This login is used for now. When Aravinth rotates it (DB-02), only the password
in `APP_MONGO_URI` changes. Re-run the same check afterwards:

```bash
.venv/bin/python scripts/check_platform_access.py
```

The script (added 25 Sep 2026) prints hosts, database names, role names, any
data-writing actions, and whether six platform collections are readable. It
never prints a connection string, and exits 0 only if the login can read and
holds no data-writing action.

v1.3 widens DB-02's read list to thirteen collections: `postevents`, `orders`,
`recommendationrequests`, `rec_serve_log`, `posts`, `users`, `businessregisters`,
`products`, `productvariants`, `categories`, `follows`, `followers`, `carts`
(DS-017 v2.5 §7). The script samples six of them; ENG-03 reads the rest.

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

One value in the settings file (`settings/engine.toml`, ENG-02) is used here:

| Setting | Meaning | Value | Source |
|---|---|---|---|
| `events.retention_days` | Engine copies in `ml_events` and `ml_orders` kept this many days from the original event time | 365 (fixed) | SD-29, X-08; Settings sheet "Keep event data", "Fixed for Wave 1A" |

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
| **Platform data it reads** | `soco` on `nex-dev.cob9whd` | Constructed platform-shaped data (ENG-29 item 8, DB-13), never live SOCO data | The launch database, through the DB-02 read-only login |
| **Called by** | Nobody but Allen | Test SOCO_BE and test app build (DB-13) | Production SOCO_BE and the admin panel |
| **Settings and secrets** | `.env` | Server environment (so test behaves like production) | Server environment only (SD-08; enforced in code) |
| **State** | Set up, 16/16 collections (1 Oct) | Server available (14 Oct); being set up (§4.4) | Later (§4.4): cluster, server, DB-02, DB-12 |

### 4.2 Conditions that go with this decision

- **Keep test and production apart.** Use separate servers, or at least separate containers with resource limits. The ENG-20 load test runs on test and must not slow production.
- **Test never reads live SOCO data.** DB-13 and ENG-29 item 8 require constructed data. The checks create their own users, orders and blocks.
- **Put production's engine database near its server.** The production cluster goes in the same cloud region as the production server. Every request reads it within the 200 ms p95 budget (SD-25).
- **Dev reaches Atlas over the internet.** The laptop's IP must be on the access list of each cluster dev uses. Dev is never in SOCO_BE's network, because nothing calls it.

### 4.3 When the test and production clusters are created

For each of the two environments:

1. Create an Atlas cluster, in the production server's region for production.
2. Create an engine database user with read/write on that environment's engine database only.
3. Add the server's address to the cluster's access list.
4. Set the settings in that server's environment, then run the §6 runbook.

### 4.4 Test now, production later (decided 14 Oct 2026)

The test server is available: `83.147.36.203`, access port 1097 (14 Oct 2026; the port
answers TCP but sends no SSH banner, so it is likely remote desktop or another access
service). Allen clones the repo there and runs §6. Its address must be on the
Atlas access list of every cluster test uses. Decision: set up **test now**; set up
**production later**. Every check the Build List runs "on test" can now run
there, so the built items (ENG-02 to ENG-05, ENG-07, ENG-08, ENG-29) can
move from Built to Passed once their checks pass there.

What this does not change:

- **ENG-01 stays Waiting.** Its check is "The engine runs in all three
  environments. The production engine reaches the platform database read-only."
  It passes only once production is up.
- §4.2 still holds: test reads constructed platform-shaped data (ENG-29 item 8),
  never live SOCO data; its secrets go in the server environment.
- The production deadline is the go-live rule (ENG-24): the surfaces cannot go
  live until production runs, DB-12 is open and APP-21 has passed there.

---

## 5. Tests

`tests/test_engine_environment.py`:

- The environments list, the default, normalisation, and refusal of unknown values.
- Per-environment default engine database names.
- SD-08: production from a `.env` file is refused; production from the server, and dev/test from a file, are accepted.
- Host parsing for `mongodb+srv://` and multi-host `mongodb://` strings.
- The engine-equals-platform guard: allowed pairings, refused pairings (including different-case names), and the password not appearing in the error.
- The sixteen collection names (`test_engine_collections_are_the_sixteen_in_eng01`).
- **Against MongoDB:**
  - all sixteen created exactly once;
  - `ml_events` and `ml_orders` each have `retention` on `created_at` with `expireAfterSeconds` 365 × 86,400;
  - on a collection carrying the 22 Sep indexes (`uniq_event_id`, `user_time` on `server_ts`), setup drops `uniq_event_id` and rebuilds `user_time` on `created_at`.

**Fixture:** `tests/conftest.py` and `tests/test_readers.py` give the platform side
its own database (`<TEST_DB>_platform`), as AS-09 requires.

Run them:

```bash
.venv/bin/python -m pytest -m "not mongo"      # unit tests, no database
.venv/bin/python -m pytest -m mongo            # uses ML_MONGO_URI, database reco_test
```

The database tests use the throwaway `reco_test` database (override with
`TEST_MONGO_DB`) on the cluster in `ML_MONGO_URI`. They drop only collections
inside it. Never point `ML_MONGO_URI` at SOCO's cluster while running them.

> Two runs sharing `reco_test` at the same time interfere: one run drops
> collections the other just created ("collection … already exists"). Give each
> concurrent run its own `TEST_MONGO_DB`.

Result on 1 Oct 2026 (after the v1.3 realignment):

- `tests/test_engine_environment.py`: **23 passed** (19 unit, 4 database; Atlas build cluster, `TEST_MONGO_DB=reco_test_eng01`).
- Whole unit suite (`-m "not mongo"`): **509 passed, 1 skipped**.

---

## 6. Runbook: bringing up an environment

1. **Engine database:** choose its cluster and name. The name must not be the platform database's.
2. **Engine login:** create an Atlas database user with read/write on **that engine database only**. It needs `createIndex` and `dropIndex` there: setup replaces changed indexes.
3. **Platform login:** use the DB-02 read-only login for the platform database.
4. **Settings:**
   - dev and test: put them in `.env`.
   - production: set them in the server environment, and make sure no `.env` file is present.
5. **Setup:** run `ENGINE_ENV=<env> python scripts/setup_engine_db.py` and expect exit 0 with 16 of 16.
6. **Start and verify:** start the service and confirm `/health` returns 200, shows the right `environment`, and both connections true.
7. **Production only:** confirm the platform login cannot write (§2 C, `scripts/check_platform_access.py`), and give Aravinth the private address for DB-12.

---

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pymongo.errors.ConfigurationError: no nameservers` from `init_client` | A `mongodb+srv://` URI needs a DNS SRV lookup. dnspython found no resolver in `/etc/resolv.conf`, which happens briefly while Wi-Fi reconnects or a VPN changes state | Retry. Check with `cat /etc/resolv.conf` and `dig SRV _mongodb._tcp.<cluster host>`. If persistent, toggle the VPN or set fixed DNS servers. Seen on dev on 28 Sep 2026; the next run passed |
| TCP connects, then `TLSV1_ALERT_INTERNAL_ERROR` | The Atlas cluster is paused | Resume it in Atlas |
| Everything touching Atlas is very slow, with no errors | The router's DNS returns malformed SRV answers (`dig SRV _mongodb._tcp.<host>` warns "malformed message packet"). Every connection waits on them | Set DNS to 1.1.1.1 / 8.8.8.8. Seen on dev on 29 Sep 2026 (router 192.168.1.1): the checklist took over 10 minutes and still passed 25/25 |
| Index setup refuses an index because one of the same name already exists | An engine database built to an older design keeps the old definition under the same name | Handled in code since 1 Oct: `_ensure_index` drops and recreates it. Seen on dev `SoCo` (`user_time` on `server_ts`) |

**Re-checked 28 Sep 2026 on dev: all checks pass.** Record: `Tracing/checks/Checklist_2026-09-28.md`.
**Re-checked 1 Oct 2026 on dev after the v1.3 realignment:** 16 of 16, platform login read-only, safety lock and SD-08 refusals as in §2.

## 7. Open

| Open item | Needs |
|---|---|
| Test: bring it up on the test server (§4.4, §6), with its own Atlas cluster and the constructed data of ENG-29 item 8 | The server's access details and a test cluster |
| Production Atlas cluster and engine database | Later (§4.4) |
| Production server | Later (§4.4); Aravinth (SD-03 hosting) |
| Rotate the platform login's password (DB-02); re-run the §2 C check afterwards | Aravinth (DB-02) |
| DB-02's row is missing from the v1.3 Build List sheet, though ENG-01, ENG-04, DB-12 and the Waits sheet still reference it | Kala (question 1 in `Tracing/REALIGNMENT_v1.3.md`) |
| Deploy in SOCO_BE's network; hand over the private address | Aravinth (SD-03 hosting, then DB-12) |
| Save the check result as `ENG-01_<date>` in "Wave1A checks" | The items above |
| `scripts/setup_engine_db.py` docstring still says "twelve" collections (its behaviour counts sixteen) | A one-word code fix |

---

## 8. Files changed

| File | Change |
|---|---|
| `reco/config/__init__.py` | `ENGINE_ENVIRONMENTS`, `ENGINE_COLLECTIONS` (sixteen since 1 Oct), `engine_env`, `_hosts_of`, engine≠platform validator, SD-08 dotenv handling |
| `reco/store/writers.py` | `ensure_engine_collections`; since 1 Oct: `_ensure_index`, `ml_orders` indexes, `retention` expiry on `created_at`, `uniq_event_id` dropped |
| `reco/main.py` | Calls it at startup; logs the environment |
| `reco/api/health.py` | `environment` in the body |
| `scripts/setup_engine_db.py` | New |
| `scripts/check_platform_access.py` | New (25 Sep): the read-only check in §2 C, repeatable |
| `scripts/run_checklist.sh` | Line 1.1 expects "16 of 16 collections present" (1 Oct) |
| `.env.example` | `ENGINE_ENV`; engine database is its own (AS-09) |
| `tests/test_engine_environment.py` | New; since 1 Oct: sixteen names, retention, `_id` keying |
| `tests/conftest.py`, `tests/test_readers.py`, `tests/test_namespace_guard.py` | Separate platform test DB; guard coverage |

## 9. Demo

The live demo script, in plain language, is the Obsidian note
`obsidian/Demos/Demo - ENG-01.md`.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks, with those of every other finished item. It prints PASS/FAIL per line and cleans up after itself.
