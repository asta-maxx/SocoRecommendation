# M1 score store — what to create in the SOCO database

For the backend developer. Everything here is additive: no application collection
is modified, renamed or read differently. The M1 engine reads SOCO **read-only**
and writes **only** to collections prefixed `ml_`.

Two things need doing, in this order:

1. Run `scripts/setup_ml_collections.js` — creates the collection, its indexes
   and a schema validator.
2. Create the `ml_`-scoped write user (§3) — needs admin privileges, so the
   script deliberately does not attempt it.

---

## 1. The collection

**`ml_user_interest_scores`** — one document per user **per category**.

A user with four scored categories has four documents, not one document with a
map inside it. That is deliberate: it makes a single category's score queryable,
indexable and comparable across methods without rewriting a whole user's record.

```json
{
  "user_id":       "652f1a...",
  "category":      "fashion & apparel",
  "raw":           42.5,
  "share":         0.34,
  "event_count":   7,
  "method":        "A_recency_decay",
  "model_version": "1.0.0",
  "window":        "all",
  "computed_at":   ISODate("2026-09-10T04:00:00Z")
}
```

| Field | Type | Meaning |
|---|---|---|
| `user_id` | string | SOCO user id **as text**, not ObjectId, so it round-trips through JSON |
| `category` | string | A `toCategoryKey()` key — lowercase, trimmed, **spaces preserved, no underscores**. `"Fashion & Apparel"` → `"fashion & apparel"` |
| `raw` | double ≥ 0 | The weighted sum. Unbounded, not comparable between users. **Diagnostics only** |
| `share` | double 0–1 | `raw` ÷ the user's total raw. Sums to 1 per user. **This is what you read** |
| `event_count` | int ≥ 0 | How many qualifying events contributed. Diagnostics |
| `method` | enum | `A_recency_decay` or `B_time_windows` |
| `model_version` | string | Configuration generation, e.g. `1.0.0` |
| `window` | enum | `all` (Method A) or `90d` (Method B) |
| `computed_at` | date | UTC |

### Read `share`, not `raw`

`raw` is an unbounded weighted sum — a heavy user and a light user with identical
tastes have wildly different raws. `share` is the same number normalised across
that user's categories, so 0.4 on Fashion means the same thing for both. `raw`
exists so that when a score moves, someone can explain why.

### The last four fields are not optional

`method`, `model_version`, `window`, `computed_at`. Two methods write into this
one collection. Without these, their documents are indistinguishable, a stale
score cannot be detected, and no comparison between the methods can be
reconstructed after the fact. They are enforced three times over: in the Python
model, in the `$jsonSchema` validator the setup script installs, and by the
unique index below.

### A user may legitimately have no documents here

If a user's total raw is zero, the engine stores **nothing** rather than writing a
uniform share across categories. A uniform distribution is indistinguishable from
a genuine even spread of interest, and would hide that the user is unknown. An
empty result is the signal to fall through to the cold-start ladder — it is not
an error and should not be logged as one.

---

## 2. The indexes

```js
// Unique. The identity of a score.
{ user_id: 1, category: 1, method: 1, model_version: 1 }   // uniq_user_category_method_version

// The read path: filter by user + method, then check staleness.
{ user_id: 1, method: 1, computed_at: -1 }                 // user_method_recency
```

**Why `method` and `model_version` are in the unique key:** both methods compute a
score for every user. If the key were `(user_id, category)` alone, whichever ran
second would silently overwrite the first, and the comparison M1 exists to make
would be impossible. Same for `model_version` — a rerun after a parameter change
becomes a new generation of scores rather than destroying the evidence of the
previous one.

---

## 3. The write credential

The M1 engine needs a **separate** database user that can write `ml_*` and
nothing else. The application credential stays **read-only** and is never used
for these writes — the engine refuses to start rather than fall back to it.

MongoDB privileges are per-collection, so the scoped role names the collections
explicitly. Add a line when a new `ml_` collection appears.

```js
use admin;

db.createRole({
  role: "mlWriter",
  privileges: [
    {
      resource: { db: "<SOCO_DB>", collection: "ml_user_interest_scores" },
      actions: ["find", "insert", "update", "remove", "createIndex", "createCollection"]
    }
    // Add further ml_ collections here as they are introduced
    // (ml_post_scores, ml_refresh_runs, ...).
  ],
  roles: []
});

db.createUser({
  user: "reco_ml",
  pwd: passwordPrompt(),
  roles: [{ role: "mlWriter", db: "admin" }]
});
```

**On Atlas**, where `db.createRole` is not available: create a Custom Role in
*Database Access → Custom Roles* with the same actions scoped to that collection,
then create a database user assigned only to it.

Two connection strings go to the engine:

```
APP_MONGO_URI = <read-only user>?readPreference=secondaryPreferred
ML_MONGO_URI  = <reco_ml user>
```

`readPreference=secondaryPreferred` so the engine's reads never compete with the
application's writes.

**Please verify the scoping actually holds** before this goes near production —
that `reco_ml` can write `ml_user_interest_scores` and *cannot* write `users`,
`posts`, `postevents` or `orders`. The Python side has its own guard that refuses
any collection not prefixed `ml_`, but a guard in the client is a guard that a
future client might not have.

---

## 4. One thing to request separately

An index on `postevents`:

```js
db.postevents.createIndex({ user_id: 1, created_at: -1 });
```

All seven existing indexes on that collection lead with `influencer`, `post` or
`product`, so reading one user's event history currently scans. Not blocking for
demo data; blocking for anything measured against production shape.

---

## 5. What M1 does not touch

- No application collection is written to, ever — not for a migration, not for a
  fixture, not for a demonstration
- `interestScores` is **not** written to, and is **not** read as the source of the
  declared-interest floor. `addInterest` seeds that map with 10 per declared
  category and event tracking increments the same map, so the declared floor and
  accumulated events are fused there and cannot be separated. The floor is read
  from `registerModel.interest`, the array
- `userevents` is not read — it holds zero documents, its TTL index was never
  created, and reading it returns an empty result that looks like a user with no
  activity. Events come from `postevents`
