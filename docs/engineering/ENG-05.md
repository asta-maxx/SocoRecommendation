# ENG-05: Choose each user's method, the same way every time

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days of starting) |
| **Waits on** | ENG-02 (built: the settings module and its reload) |
| **Needed by** | ENG-06, ENG-11, ENG-17 (Build List). Also read by ENG-10 and ENG-16 (both methods computed, the assigned one served), ENG-19 (the viewer's interest and promoter methods), ENG-24 (users per method per slot) and ENG-26 (the comparison) |
| **Status** | **Built** (1 Oct 2026, on dev/laptop). Parts 1–4 built, with the three checks of the row passing. Becomes Passed when re-run on **test** (Definitions: every check runs on test) |
| **Spec** | Build List v1.3 ENG-05 (and the Settings sheet rows "Method choice"; the "Not built" row "A platform experiment model"; ENG-26 "Promoting a winner"); DS-017 v2.5 §4.1 (`user_id`), §4.2 (`policy_id`), §5; SDA v1.6 SD-12, SD-13, SD-15, SD-16; AS-01 |

---

## 1. What the item requires

From the Build List v1.3 row, *What to build*:

> Three slots each carry two methods:
> - interest: recency decay or time windows.
> - product_ranking: attribute similarity or bought together.
> - promoter_score: method one or method two.
>
> For each slot:
> 1. Take SHA-256 of '<slot name>:<user_id>'. The first 8 hex characters, taken mod 100, give the user's bucket (0 to 99).
> 2. A bucket below the slot's split gets method two. Everyone else gets method one.
> 3. Split, method one, method two and the default method are settings. The split starts at 50 in all three slots, and the default is method one.
> 4. If the settings are missing, everyone gets the default and the fault is logged.
>
> Never use the language's built-in hash. Never use a session or device id. Record the method used in policy_id, as cfg<version>.<slot>-<method>.

*How to check it is done*:

> The same user gets the same method across two restarts. Changing a split changes assignment with no deploy. Over 10,000 test ids, the split is within 2 points.

DS-017 v2.5 §5, *How the method is chosen*, which the row follows:

> Three slots carry two methods at launch. A user is assigned to a method per slot, the same way on every request, after every restart.
>
> | Rule | Contract |
> |---|---|
> | Identifier | The user_id of the person the list is for. Never a session id or device id. |
> | Hash | SHA-256 of slot name and user_id joined by a colon, for example interest:65f1…. The first 8 hex characters, read as a number and taken mod 100, give the user's bucket (0 to 99). A bucket below the split value gets method two. Everyone else gets method one. The language's built-in hash is never used. |
> | Independent slots | The slot name is part of the hash, so a user's method in one slot does not decide their method in another. The exploration slice is decided separately. |
> | Configuration | Per slot: method one, method two, split (0 to 50) and default method, in the versioned configuration file. Read on each request or reloaded at least once a minute. Every change is logged with time, old value, new value and who made it. |
> | Launch values | Split 50 in all three slots. Method one is the default. |
> | Missing configuration | Every user gets the default method, the fault is logged, and the request still succeeds. |
> | Missing score | The fallback ladder applies. The service still records the intended method and the fallback step used. |
> | Both computed | The daily refresh computes both methods for every user. Serving reads the row for the assigned method. |
> | Old scores | Time-windows scores written earlier without a method name are deleted and recomputed. |

DS-017 v2.5 §4.2, the `policy_id` line of the response:

> policy_id | string | The config_version and the method used in each slot the request touched, for example cfg3.interest-2.promoter-1.

DS-017 v2.5 §4.1, `user_id`:

> The person the list is for. [Assumed: AS-01, login is required, so it is always present]. If it is ever missing, the default method is used for every slot.

The last three rows of §5 (missing score, both computed, old scores) belong to
the fallback ladder (ENG-09) and the nightly refreshes (ENG-07, ENG-10, ENG-16,
ENG-17), not to this item. The Build List's "Not built" sheet confirms that no
separate experiment model is built: *"Engine method choice (ENG-05) and its logs
cover Wave 1A."*

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–4 are the Build List's parts; A–C are extras.
Everything is in `reco/slots/assignment.py` unless stated. It needs no database.

```python
bucket(slot, user_id) -> int                              # 0-99
assign(slot, user_id, tunables=None) -> Assignment        # one slot
assign_all(user_id, tunables=None) -> dict[str, Assignment]   # all three, one reading of the settings
method_number(assignment) -> int                          # 1 or 2 (recorded on the E1, not in policy_id)
policy_id(*assignments, config_version=None) -> str       # "cfg2.interest-recency_decay.promoter_score-shrinkage"
```

`Assignment` is a frozen dataclass: `slot`, `method` (the method's name, e.g.
`recency_decay`), `which` (`"method_one"` or `"method_two"`), `bucket`,
`config_version`, and `from_default` (true when the default was used because
settings or `user_id` were missing).

`SLOT_NAMES = ("interest", "product_ranking", "promoter_score")` is taken from the
fields of the settings model `Slots`, so the slot list is written down once.
`assign` refuses any other slot name with `ValueError` (SD-13: these three are the
only two-method slots).

### 1. The bucket: SHA-256 of `<slot>:<user_id>`, first 8 hex, mod 100: built

```python
digest = hashlib.sha256(f"{slot}:{user_id}".encode("utf-8")).hexdigest()
return int(digest[:8], 16) % 100
```

- **Exactly the row's and DS-017 §5's rule**, with the colon join and UTF-8 bytes.
- **Never Python's `hash()`.** It is salted per process (`PYTHONHASHSEED`), so it changes on every restart: two runs of `hash("interest:64f1c0ffee0000000000abcd") % 100` gave 23 and 56 on 1 Oct. SHA-256 is the same on every machine and every start.
- **Only `user_id`.** No session or device id enters the hash (DS-017 §5, *Identifier*), so a user keeps their method across sessions, phones and restarts.
- **Independent slots.** The slot name is in the hashed text, so the three buckets of one user are unrelated (DS-017 §5, *Independent slots*). `test_each_slot_hashes_separately` checks that over 500 ids the interest and product_ranking buckets agree for fewer than 50 (chance is 1 in 100).
- **Exploration is not decided here.** The 5% exploration slice (SD-16) is drawn separately in ENG-06.

### 2. Below the split gets method two: built

```python
which = "method_two" if user_bucket < settings.split else "method_one"
```

- The split is the **share on method two** (ENG-26: *"The split is always the share on method two"*). Split 50 → buckets 0–49 on method two; split 0 → nobody on method two.
- `Assignment.method` carries the **name** from the settings, so callers (the rankers, ENG-06's record) never map numbers to names themselves.
- **The settings are read at the moment of use.** `assign` reads `live.current()`, the settings in force, on every call, unless the caller passes one reading (`tunables`). `assign_all` and ENG-06 read once per request, so all slots of one list use one version. A changed split therefore applies to the next request after the reload: within 30 seconds in the API (ENG-02 `reload_loop`), at the next start for a job. No code change or deploy (the row's check).

### 3. Split, method one, method two and the default are settings: built

The settings model is `Slot` / `Slots` in `reco/config/tunables.py` (built with
ENG-02, commit `9b281a7`); the values are in `settings/engine.toml`:

```toml
[slots.interest]
method_one = "recency_decay"
method_two = "time_windows"
split = 50
default_method = "method_one"

[slots.product_ranking]
method_one = "attribute_similarity"
method_two = "bought_together"
split = 50
default_method = "method_one"

[slots.promoter_score]
method_one = "shrinkage"
method_two = "cohort_percentile"
split = 50
default_method = "method_one"
```

| Setting | Value | Rule | Source |
|---|---|---|---|
| `split` | 50 in all three | integer 0–50; a value outside is refused and the last good file stays in force (ENG-02) | Settings sheet "Split per slot (share on method two)": *"50 for interest, product_ranking and promoter_score … 0 to 50 … Changed only by the ENG-26 rule."* |
| `default_method` | `method_one` | fixed: the model only accepts `"method_one"` | Settings sheet "Default method per slot": *"method one … Fixed for Wave 1A."* |
| `method_one`, `method_two` | names | non-empty | Build List ENG-05; SD-12 *"Methods are registered by name, and the configuration picks them by name."* |

- **The promoter_score names are ours.** The Build List and DS-017 §5 call M8's methods "method one" and "method two". We named them after what ENG-16 describes: method one pulls the weighted sum toward the category average (`shrinkage`), method two is a percentile within a cohort (`cohort_percentile`). Because `policy_id` names the method (subtask A), these two names appear in every feed list's `policy_id`; if the pack names M8's methods differently, the settings and the label change together.
- **Every change is logged** in `ml_config_changes` with time, old value, new value and who (ENG-02 item 4; DS-017 §5, *Configuration*). A split change must raise `config_version`, or the file is refused.
- Checked 1 Oct: a copy with `split = 60` is refused: `slots.interest.split: Input should be less than or equal to 50` (and the same for the other two).

### 4. Missing settings: everyone gets the default, and the fault is logged: built

```python
settings = _slot_settings(slot, tunables)        # None if tunables.slots.<slot> is absent or not a Slot
if settings is None:
    logger.error("slot settings missing; using the default method", extra={"slot": slot})
    fallback = getattr(Slots(), slot)             # the Settings sheet's own values
    which = fallback.default_method               # method_one
    return Assignment(..., from_default=True)
```

- The request still succeeds (DS-017 §5, *Missing configuration*): `assign` never raises for missing settings.
- The ERROR line goes to logger `reco.slots`, as structured JSON (ENG-02 item 6), with the slot.
- `from_default=True` is carried into ENG-06's served-list record (`slots.<slot>.from_default`), so lists built this way can be found later.

**A slot left out of the file** (`reco/config/live.py`, `_slots_as_written`, commit
`ea88d1a`). Without it, the settings model would fill a missing `[slots.<slot>]`
section with the Settings sheet's values, split 50, and nobody would know. Now
`read_file` checks which slot sections the file actually contains. For each one
left out it sets that slot's split to **0**, so everyone is on method one (the
default, which is fixed), and logs an ERROR on `reco.settings`:

```
settings file has no [slots.interest]: everyone gets the default method there
```

with `missing_slots` in the structured fields. The slots that are present keep
their values. Assignments in such a slot go through the normal rule (split 0), so
their `from_default` is false; the log line is the record of the fault.

How each case fits with ENG-02's settings handling:

| Situation | What happens | Logged |
|---|---|---|
| The slot's settings cannot be read at all (no `slots`, or not a `Slot`) | Everyone gets method one | Yes, ERROR `slot settings missing` |
| The file is broken or breaks a rule | ENG-02 keeps the last good version; the split in force stays in force | Yes, ERROR `settings file rejected` |
| No good version exists at all | ENG-02 uses the Settings sheet's values: split 50 | Yes (ENG-02) |
| A `[slots.<slot>]` section is **left out** of an otherwise valid file | That slot's split becomes 0: everyone on method one; the other slots keep their values | Yes, ERROR `settings file has no [slots.<slot>]` (since `ea88d1a`) |

### A. Extra: `policy_id` names the method in each slot: built

```python
policy_id(interest, promoter_score)   # "cfg2.interest-recency_decay.promoter_score-shrinkage"
policy_id(product_ranking)            # "cfg2.product_ranking-attribute_similarity"
```

- **Form** (decided 1 Oct 2026): `cfg<config_version>` then, for each slot the request touched, `.<slot>-<method name>`. The name is the one in the settings in force (`Assignment.method`).
- **Which slots:** ENG-06 passes the slots each surface uses: the feed touches `interest` and `promoter_score` (ENG-19), the product surface `product_ranking` (ENG-17).
- **The version** is the request's `config_version` (ENG-06 passes it explicitly); otherwise the first assignment's.
- **`cfg` prefix:** DS-017 §4.5: *"Any policy_id that does not start with cfg is a fallback list."* Every engine list starts with `cfg`.
- **The method number** (`method_number`, 1 or 2) is not in `policy_id`. ENG-06 records it on the served-list record with the name and the bucket (`slots.<slot>.method`, `method_number`, `bucket`, `from_default`).

Why names, and how the pack's texts were reconciled:

| Text | Says | We do |
|---|---|---|
| Build List ENG-05 | `cfg<version>.<slot>-<method>` | the same shape |
| Build List ENG-26, *Promoting a winner* | *"policy_id records method names, so history stays readable across the swap"* | names |
| SDA SD-15 | *"the method named in policy_id"* | names |
| DS-017 §4.2 example | `cfg3.interest-2.promoter-1`: method as a **number**, slot as `promoter` | not followed: the Build List comes first in the pack's order |
| Settings / Slots | the slot is `promoter_score` | `promoter_score`, not `promoter` |

ENG-26 promotes a winner by swapping the names (`method_one` ← the winner, then
split 10, then 0). With numbers, "2" would mean a different method before and
after the swap; with names, every `policy_id` says what actually ran.

History of this decision (1 Oct 2026): built first (`4ec8f30`) as one slot with
the method name (`cfg2.interest-recency_decay`); changed with ENG-06 (`4db835f`) to
DS-017's numbered form for several slots (`cfg2.interest-1.promoter_score-2`);
changed back to names (`ea88d1a`) once the ENG-26 line and SD-15 were found, keeping
the several-slot form. Kala is asked to correct the DS-017 example
(`Tracing/REALIGNMENT_v1.3.md`, question 13).

### B. Extra: a missing `user_id` gets the default in every slot: built

```python
if not str(user_id or "").strip():
    which = settings.default_method                # method_one
    return Assignment(..., from_default=True)
```

DS-017 §4.1: *"If it is ever missing, the default method is used for every
slot."* AS-01 says login is required, so it should not happen. Without this rule,
an empty `user_id` would hash `"interest:"` to one fixed bucket and put every such
request on whichever method that bucket gives. ENG-06 passes a missing or blank
`user_id` through as `""`, so such a request is served on method one in every slot
and its record shows `from_default: true` per slot. No ERROR line is logged for
this case (the pack asks for none).

### C. Extra: `scripts/show_assignment.py`: built

Prints the assignment under a settings file, with no database. It reads the file
through `live.read_file`, exactly as the service does, from `SETTINGS_FILE` or
`settings/engine.toml`.

```bash
.venv/bin/python scripts/show_assignment.py                            # 10,000 fixed test ids, share per slot
.venv/bin/python scripts/show_assignment.py 64f1c0ffee0000000000abcd   # one user: bucket, method, policy_id per slot
SETTINGS_FILE=/tmp/copy.toml .venv/bin/python scripts/show_assignment.py
```

The 10,000 test ids are `sha1("test-user-<n>")[:24]`, fixed, so two runs print the
same numbers. Each slot's line ends `(within 2 points)` or `(OUTSIDE 2 points)`.
A rejected file prints the fault and exits 1.

Output on 1 Oct 2026, the real settings (`config_version` 2):

```
settings settings/engine.toml: config_version 2
  interest         split 50  method two 50.21%  (within 2 points)
  product_ranking  split 50  method two 49.72%  (within 2 points)
  promoter_score   split 50  method two 50.59%  (within 2 points)
```

A throwaway copy with `split = 20` in all three slots and `config_version` 3:

```
settings /tmp/soco-demo-eng05.toml: config_version 3
  interest         split 20  method two 19.55%  (within 2 points)
  product_ranking  split 20  method two 20.19%  (within 2 points)
  promoter_score   split 20  method two 20.01%  (within 2 points)
```

One user, before and after (product_ranking bucket 28 moves to method one at split
20; promoter_score bucket 19 stays on method two). Re-run 1 Oct after `ea88d1a`:

```
settings settings/engine.toml: config_version 2
  64f1c0ffee0000000000abcd  interest         bucket 90  method_one recency_decay          cfg2.interest-recency_decay
  64f1c0ffee0000000000abcd  product_ranking  bucket 28  method_two bought_together        cfg2.product_ranking-bought_together
  64f1c0ffee0000000000abcd  promoter_score   bucket 19  method_two cohort_percentile      cfg2.promoter_score-cohort_percentile
settings /tmp/soco-demo-eng05.toml: config_version 3
  64f1c0ffee0000000000abcd  interest         bucket 90  method_one recency_decay          cfg3.interest-recency_decay
  64f1c0ffee0000000000abcd  product_ranking  bucket 28  method_one attribute_similarity   cfg3.product_ranking-attribute_similarity
  64f1c0ffee0000000000abcd  promoter_score   bucket 19  method_two cohort_percentile      cfg3.promoter_score-cohort_percentile
```

A copy with `[slots.interest]` removed:

```
settings file has no [slots.interest]: everyone gets the default method there
settings /tmp/soco-demo-eng05-noslot.toml: config_version 2
  interest         split  0  method two  0.00%  (within 2 points)
  product_ranking  split 50  method two 49.72%  (within 2 points)
  promoter_score   split 50  method two 50.59%  (within 2 points)
```

---

## 3. Configuration reference

No new settings or environment variables. ENG-05 reads the `[slots.*]` sections
described in §2 part 3, which ENG-02 created from the Settings sheet.
`show_assignment.py` honours `SETTINGS_FILE` (ENG-02).

## 4. Environments

No change. Assignment is pure computation on the settings in force; it reads and
writes no database, so it behaves identically on dev, test and production. The
same user gets the same method in every environment with the same settings.

---

## 5. Tests

`tests/test_assignment.py`, 15 tests, no database:

| Test | Covers |
|---|---|
| `test_the_bucket_is_sha256_of_slot_and_user_first_8_hex_mod_100` | Part 1, recomputed independently |
| `test_each_slot_hashes_separately` | Independent slots (DS-017 §5) |
| `test_below_the_split_is_method_two` | Part 2, and the names come from the settings |
| `test_same_method_across_restarts` | **Check 1:** two fresh Python processes (new `hash()` salt each) give the same methods as this one, for 50 ids × 3 slots |
| `test_a_split_change_moves_users_with_no_deploy` | **Check 2:** a new version with split 10 put in force; fewer users on method two at once, all carrying the new `config_version` |
| `test_ten_thousand_ids_land_within_two_points[50, 25, 10, 0]` | **Check 3:** 10,000 random ids per run, each slot within 2 points (4 tests) |
| `test_missing_settings_give_everyone_the_default_and_log_it` | Part 4: default and the ERROR line |
| `test_a_slot_left_out_of_the_file_gives_everyone_the_default` | Part 4: a copy of the real file without `[slots.interest]` gives split 0 there (200 ids all on method one), the other slots keep 50, and the ERROR names `slots.interest` |
| `test_policy_id_names_the_method_per_slot` | Extra A: `cfg<v>.product_ranking-attribute_similarity`, and two slots in order with their names |
| `test_an_unknown_slot_is_refused` | Only the three slots |
| `test_the_defaults_start_at_fifty_with_method_one_default` | Part 3 launch values |
| `test_a_missing_user_id_gets_the_default_in_every_slot` | Extra B |

```bash
.venv/bin/python -m pytest -q tests/test_assignment.py -p no:cacheprovider
```

Result on 1 Oct 2026, after `ea88d1a`: **15 passed**, 0 failed, 0 skipped (0.48 s).
`scripts/show_assignment.py` on the real settings: all three slots within 2 points
(50.21%, 49.72%, 50.59%); on a split-20 copy: 19.55%, 20.19%, 20.01%.

ENG-06's tests (`tests/test_recommendations.py`) also check the `policy_id` on
real responses: `cfg<config_version>.interest-…` with `.promoter_score-` on the
feed, ending `.product_ranking-attribute_similarity` or
`.product_ranking-bought_together` on the product surface.

### Checklist section 5

`scripts/run_checklist.sh` §5 runs the row's checks:

| Line | Command | Expects |
|---|---|---|
| 5.1 | `pytest tests/test_assignment.py -k restarts` | `1 passed` |
| 5.2 | `… -k no_deploy` | `1 passed` |
| 5.3 | `… -k ten_thousand` | `4 passed` |
| 5.4 | `… -k 'missing or left_out'`: missing settings, a slot left out, a missing `user_id` | `3 passed` |
| 5.5 | `scripts/show_assignment.py \| grep -c 'within 2 points'` | `3` |

Run by hand on 1 Oct 2026, after `ea88d1a`: all five lines pass (5.4: `3 passed, 12 deselected`;
5.5: 3 slots within 2 points).

---

## 6. Runbook

**See one user's methods** (any environment, no database):

```bash
.venv/bin/python scripts/show_assignment.py <user_id> [<user_id> …]
```

**Check the split on the settings in force:** run the script with no ids; every
slot should say `within 2 points`.

**Change a split** (only under the ENG-26 rule, Settings sheet):

1. Edit `split` in the slot's section of `settings/engine.toml` (0–50).
2. Raise `config_version` and set `changed_by`. Without a new version the file is refused (ENG-02).
3. Before saving the real file, try the copy: `SETTINGS_FILE=<copy> .venv/bin/python scripts/show_assignment.py`.
4. Save. The API applies it within 30 seconds; the change is recorded in `ml_config_changes` (`scripts/show_config_changes.py`). New lists' `policy_id` start with the new `cfg<version>`.

**Promote a winner** (ENG-26): set `method_one` to the winner's name and
`method_two` to the loser's, split 10 for one cycle, then 0. Each step is a new
`config_version`.

**Look for lists served on the default:** in `ml_events`, served-list records
with `slots.<slot>.from_default: true`; in the logs, `reco.slots` ERROR lines
`slot settings missing`.

---

## 7. Open

| Open item | Needs |
|---|---|
| Re-run the three checks on the **test** server and save the result as `ENG-05_<date>` | The test server (ENG-01) |
| Correct the DS-017 §4.2 example to the Build List's form (method names; `promoter_score`, not `promoter`). We follow the Build List | Kala (question 13 in `Tracing/REALIGNMENT_v1.3.md`) |
| Weekly users-per-method-per-slot count | ENG-24 |
| The comparison and promotion of a winner | ENG-26, after launch |

---

## 8. Files changed

| File | Change |
|---|---|
| `reco/slots/assignment.py` | New (`4ec8f30`): `bucket`, `assign`, `assign_all`, `Assignment`, `SLOT_NAMES`. `4db835f`: `method_number`; `policy_id` takes several slots (method numbers); a missing `user_id` gets the default. `ea88d1a`: `policy_id` names the method |
| `reco/config/live.py` | `ea88d1a`: `_slots_as_written`: a slot left out of the file gets split 0 and an ERROR on `reco.settings` |
| `reco/config/tunables.py` | Unchanged here: `Slot` / `Slots` came with ENG-02 (`9b281a7`) |
| `settings/engine.toml` | Unchanged here: `[slots.*]` came with ENG-02 |
| `scripts/show_assignment.py` | New (`4ec8f30`) |
| `tests/test_assignment.py` | New (`4ec8f30`, 13 tests); `4db835f`: `policy_id` per slot, missing `user_id` (14 tests); `ea88d1a`: `policy_id` with names, slot left out of the file (15 tests) |
| `scripts/run_checklist.sh` | §5, lines 5.1–5.5; `ea88d1a`: 5.4 covers `missing or left_out`, expects `3 passed` |
| `tests/test_recommendations.py` | `ea88d1a`: the product `policy_id` ends with a method name |
| `reco/api/recommendations.py` | ENG-06: calls `assign` per slot the surface touches, puts `policy_id` on the response and the record, and the per-slot method on the record |

## 9. Demo

The live demo script, in plain language, is the Obsidian note
`obsidian/Demos/Demo - ENG-05.md`. It needs no database.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks
with those of every other finished item (§5, lines 5.1–5.5).
