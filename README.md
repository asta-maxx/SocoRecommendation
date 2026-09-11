# reco — SOCO M1 interest model

A separate Python 3.12 / FastAPI service computing SOCO's M1 interest model. It
reads the SOCO MongoDB **read-only** and writes **only** to collections prefixed
`ml_`.

Currently built: **P1 (service skeleton)** and **P2 (the score store, RE-02)**.
No scoring method exists yet — that is P4/P5, and the variant layer (P2 in the
sequence) comes before either of them.

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt
cp .env.example .env                                # then fill in the two URIs
uvicorn reco.main:app --reload --port 8100
curl http://localhost:8100/health
```

```bash
pytest                  # everything
pytest -m "not mongo"   # model and config only, no database needed
```

Store tests skip cleanly when MongoDB is unreachable, so a fresh checkout runs
green before anyone has a connection string.

## Layout

```
reco/
  main.py            FastAPI app. Wiring only, no logic.
  config.py          One Settings object. Every DS-007 v1.1 parameter.
  api/health.py      GET /health
  domain/scores.py   The score document and its rules
  data/mongo.py      Two clients: app (read-only) and ml (ml_ writes only)
  domain/events.py   The one event shape the methods see
  data/ids.py        str <-> ObjectId, in one place
  data/readers.py    The only module that reads sources. One adapter per shape.
  data/writers.py    The only module that writes ml_ collections
  methods/           Empty. Method A and Method B land here.
  eval/              Empty. Conformance and the data checks land here.
scripts/
  setup_ml_collections.js   For the backend dev: collection, indexes, validator
HANDOFF.md                  For the backend dev: what to create and why
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
