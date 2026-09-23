# reco — SOCO M1 interest model

A separate Python 3.12 / FastAPI service computing SOCO's M1 interest model. It
reads the SOCO MongoDB **read-only** and writes **only** to collections prefixed
`ml_`.

Built: the score store, both scoring methods (recency decay and time windows),
the purchase reversal, category resolution, the cold-start ladder, and a read
path that stamps every response with the rung, method and model version.

Open: the `ml_`-scoped write credential, and `LEGACY_LABEL_MAP` from
`categories.js` — without it legacy category names are dropped and counted
rather than merged. Both are tracked in [`Tracing/TASK_LOG.md`](Tracing/TASK_LOG.md).

---

# Running it

Every command below is run from **`C:\Revealer\Soco\reco`**.

## 1 · One-time setup

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # then fill in the two connection strings
```

> **If the install fails on `pydantic-core`** you are on a Python version with no
> prebuilt wheels for the pinned releases, and pip falls back to compiling from
> Rust. Either install **Python 3.12** — which is what RE-00a pins and what
> `requirements.txt` is pinned against — or install the dependencies unpinned:
>
> ```powershell
> .venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" pymongo pydantic python-dotenv pytest pytest-asyncio
> ```
>
> Unpinned works and the suite passes, but it is not the pinned runtime. Treat it
> as a stopgap, not the answer.

## 2 · Start the backend

```powershell
$env:DATA_PROFILE="demo"
.venv\Scripts\python.exe -m uvicorn reco.main:app --port 8100
```

Add `--reload` while editing. Then check it:

```powershell
curl http://127.0.0.1:8100/health
```

A healthy reply has **`"mongo":{"app":true,"ml":true}`**. If `ml` is `false` see
*The cluster is paused* below.

Interactive API docs: **http://127.0.0.1:8100/docs**

## 3 · Open the dashboard

Double-click **`C:\Revealer\Soco\dashboard.html`**. It needs the backend on port
8100 and says so plainly if it cannot reach it.

Two views: **Overview** (the whole population at a glance) and **Walkthrough**
(the nine DS-014 demonstration steps, with the narration and arrow-key
navigation).

## 4 · Rebuild the demo data from scratch

Only needed after a fresh cluster, or when Kala sends a new dataset.

```powershell
$env:DATA_PROFILE="demo"

# a. unpack reference\demo.zip into reference\demo\  (once per new dataset)

# b. load the generated data into MongoDB
.venv\Scripts\python.exe scripts\load_demo_data.py

# c. score it — three runs, one per method
.venv\Scripts\python.exe scripts\run_refresh.py --as-of-dataset
.venv\Scripts\python.exe scripts\run_refresh.py --as-of-dataset --method recency_decay_h_inf
.venv\Scripts\python.exe scripts\run_refresh.py --as-of-dataset --method time_windows

# d. Kala's checks — expect 14 passed, 0 failed, 4 pending
.venv\Scripts\python.exe reference\run_data_checks.py --dir reference\demo
```

`--as-of-dataset` ages events from the dataset's own reference date rather than
from the clock, which is what reproduces its expected values exactly. Drop it for
a live run.

The four pending checks are correct and permanent: checks 5 and 7 derive their
expected values from decay arithmetic and decline to grade the two non-decay
methods. **The line to watch is `0 failed`.**

## 5 · Tests

```powershell
.venv\Scripts\python.exe -m pytest -q          # everything
.venv\Scripts\python.exe -m pytest -q -m "not mongo"   # no database needed
```

Store tests skip cleanly when MongoDB is unreachable, so a fresh checkout runs
green before anyone has a connection string.

---

# When something is wrong

### The cluster is paused

By far the most common. Symptom: `/health` shows `"ml":false`, the dashboard
shows its red banner, and the log carries
`SSL handshake failed ... TLSV1_ALERT_INTERNAL_ERROR`.

TCP connects and TLS is then refused — that is what a **paused Atlas cluster**
looks like, not a certificate or firewall problem. Free-tier clusters pause
themselves after a spell of no use.

**Fix:** Atlas → Database → find the cluster → **Resume**. A few minutes, then
restart the backend. Nothing is lost; the scores are still there.

To tell a paused cluster from a network problem, compare the two — SOCO's
cluster reachable while yours is not means the fault is at their end, not yours.

### The dashboard shows "Cannot reach the engine"

The backend is not running, or is on another port. Go back to step 2.

### Scores look stale, or a user shows categories it should not

Re-run step 4c. Each refresh sweeps rows it did not rewrite, so a category a user
has stopped scoring in is removed rather than left behind.

### `/overview` returns 500 but `/health` is 200

The service is up and the database is not. Same cause as *The cluster is paused*.

## Layout

```
reco/
  main.py            FastAPI app. Wiring only, no logic.
  config.py          One Settings object. Every DS-007 v1.1 parameter.
  api/health.py      GET /health
  domain/scores.py   The score document and its rules
  data/mongo.py      Two clients: app (read-only) and ml (ml_ writes only)
  domain/events.py   The one event shape the methods see
  domain/service_contract.py  POST /v1/recommendations and POST /v1/events (RE-00d)
  data/ids.py        str <-> ObjectId, in one place
  data/readers.py    The only module that reads sources. One adapter per shape.
  data/writers.py    The only module that writes ml_ collections
  methods/           Empty. Method A and Method B land here.
  eval/              Empty. Conformance and the data checks land here.
scripts/
  setup_ml_collections.js   For the backend dev: collection, indexes, validator
  export_contract_schema.py docs/service_contract.schema.json, for SOCO_BE
HANDOFF.md                  For the backend dev: what to create and why
SERVICE_CONTRACT.md         For the backend dev: the recommendation call and the twelve events
```

## The four things this codebase will not let you do

1. **Write outside `ml_`.** `writers.py` obtains every collection handle through
   one guard that refuses any name not prefixed `ml_`. There is no second path to
   a writable handle, so the rule is something a test catches rather than
   something a reviewer has to notice.
2. **Store a score without its provenance.** `method`, `model_version`, `window`
   and `computed_at` have no defaults. A score missing one fails at construction,
   and the `$jsonSchema` validator in `scripts/` rejects it at the database too.
3. **Let two methods overwrite each other.** The unique index is
   `(user_id, category, method, model_version)`. Both methods, and successive
   generations of one method, coexist as distinct documents.
4. **Fabricate a uniform share.** `normalise_to_shares()` returns an empty map
   when a user's total raw is zero. A uniform spread is indistinguishable from a
   genuine even spread of interest and hides that the user is unknown — an empty
   result is the signal for the cold-start ladder.

## Collections are configuration, and so is shape

`DATA_PROFILE` moves the whole pipeline between generated and live data:

```
live  postevents / posts / registers / orders  ->  ml_user_interest_scores
demo  ml_demo_events / ml_demo_posts /             ml_user_interest_scores_demo
      ml_demo_users / ml_demo_orders
```

**Four sources, not two.** Method A reads the declared floor from the user record
and ages a purchase reversal from the order's creation timestamp, so the user and
order sources move with the profile too. Naming only the event source and the
score target would leave the demo unable to read the floor without a special
case — and a special case built to make a demonstration work is a finding about
the build, not a shortcut.

**A name is not enough.** A demo row carries its `categories` array on the event.
A `postevent` carries a `post_id` and no categories at all — the category
resolves through the post, which is a join. Those are structurally different
reads, so `readers.py` holds one adapter per shape, both producing the single
`domain.events.Event`. The methods see only that shape and never learn which
source they are reading. `test_readers.py` seeds both shapes and asserts they
produce the same event.

**The row's `weight` is a trap.** The generator writes `weight` onto every demo
row for the data checks' arithmetic. If the engine read it, P-06 would stop being
configuration — retuning a weight would change no score and nothing would fail
loudly to say so. `Event` has no field for it and forbids extras, so an adapter
cannot carry one through.

## Configuration

Every tunable is DS-007 **v1.1** (10 September 2026) and lives in
`config.Settings`, validated against its documented range. Nothing is read from
the database: a method that behaves differently depending on where it runs cannot
be evaluated.

Methods receive parameters through `settings.tunables()` — which deliberately
excludes connection strings, so a method cannot reach a database and the
no-I/O half of the method contract stays enforceable.

## Notes for whoever picks this up next

- `APP_MONGO_DB` and `ML_MONGO_DB` are **case sensitive**, and a wrong case is not
  an error — every read simply returns nothing. The service warns at startup
  rather than letting that look like an idle user.
- During the build the two URIs may address different clusters (real SOCO
  read-only on one, a scratch cluster for `ml_` on the other). **In production
  they must be the same database**: Q14 settled on a prefix convention inside the
  one database, because the app runs a single MongoDB connection.
- `.env` holds live credentials and is gitignored. Connection strings are marked
  `repr=False` so they stay out of tracebacks, fixture headers and CI logs.
