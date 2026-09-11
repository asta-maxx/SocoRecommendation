# Task log

The running record of the M1 build, kept against **SOCO-REC-DS-015 v3**, the demo
task list. Twenty-two tasks over four days.

**Rule:** every time something is built, decided, corrected or discovered, it goes
in here. A change that is not recorded is indistinguishable from a change that
never happened.

Newest entries at the top of the log. The status board below is the current
picture; the log is how it got there.

---

## Status board

Owner is from DS-015. **Allen** owns engine code; **Kala** owns the generator,
the checks, the display script and the narration.

| # | Day | Owner | Task | Status |
|---|---|---|---|---|
| 1 | Before | Kala | Confirm the twenty user definitions | ✅ Complete 9 Sep |
| 2 | Before | Kala | Confirm DS-007 v1.1 parameters | ✅ Confirmed — 27 params, 13 implementable for M1 |
| 3 | Before | Allen | Confirm whether anything writes to `UserEvent` | ⛔ **Blocked** — needs the SOCO_BE repo, not in this workspace |
| 4 | Before | Kala | Put the three open questions to Aravinth | ➖ Superseded — conformance descoped, so D-01/D-02 no longer gate anything |
| 5 | 1 | Allen | Score store with the four metadata fields | ✅ Done |
| 6 | 1 | Allen | Source and target collections as configuration | ✅ Done |
| 7 | 1 | Kala + Allen | Agree the event row schema | ✅ Done, and verified against the generated rows |
| 8 | 1 | Kala | Event generator script | ✅ Done by Kala — `demo.zip` |
| 9 | 1 | Kala | Run the seven data checks | ✅ With all three methods: **14 pass, 0 fail, 4 pending** |
| 10 | 2 | Allen | Method one, recency decay | ✅ Done — matches all 20 expected users exactly |
| 11 | 2 | Allen | Purchase reversal | ✅ Done — U16 vs U17 verified |
| 12 | 2 | Allen | Sanity check the decay output | ✅ Done — U04 reorders both ways |
| 13 | 2 | Kala + Allen | Agree the score row field names | ✅ Settled by the v2 manifest — all nine fields pinned |
| 14 | 2 | Kala | Draft the narration | ❌ Kala |
| 15 | 3 | Allen | Method two, time windows | ✅ Done — U14, U18, U04 all behave as the manifest predicts |
| 16 | 3 | Kala | Display script | ✅ Delivered 11 Sep — runs against our store, all nine steps |
| 17 | 3 | Allen | Cold start, rungs 2 and 3 | ✅ Done — U07 rung 2, U11 rung 3, verified live |
| 18 | 3 | Kala + Allen | First dry run | ❌ Not started |
| 19 | 4 | Allen | Conformance check | ➖ **Descoped** by Kala, 10 Sep |
| 20 | 4 | Allen | Method and version stamped on every response | ✅ Done — built with task 17, same response |
| 21 | 4 | Kala + Allen | Second dry run, timed | ❌ Not started |
| 22 | 4 | Kala | Prepare the four anticipated questions | ❌ Kala |

**Allen's engine work is complete.** Tasks 5, 6, 7, 10, 11, 12, 13, 15, 17 and 20
are all done. Task 3 remains blocked on repository access; task 19 is descoped.

**Remaining on the sheet: five.** Kala's 14 and 22, and the two joint dry runs
(18, 21). Task 16 landed on 11 Sep and runs against our store unchanged.

**The one thing blocking a demonstration step:** `categories.js`, contradiction
C5 below. Everything else outstanding is scheduling.

---

## Open contradictions

Things where two documents disagree. Neither is worked around in code; both are
left visible so they get ruled on rather than absorbed.

| # | Contradiction | Effect now | Needs |
|---|---|---|---|
| C3 | **Reference date vs the clock.** The event contract input says "future" is measured against `reference_date`. Check 9's docstring says the engine ages from its own clock and the dataset should be regenerated with `--as-of` | Engine supports both. Currently anchored to the dataset | Kala: which applies on the day |
| C5 | **`LEGACY_LABEL_MAP` is not available.** It lives in `backend/SOCO_BE/src/constants/categories.js`, which is not in this workspace. The build brief says export it to JSON and load it -- never retype it, which would make a fourth vocabulary | Legacy names are **dropped and counted** rather than merged. Correct per DS-008 §3.2 but incomplete: **U06 cannot demonstrate a merge and currently scores nothing**. Blocks Kala too: show_demo.py cannot read the map either and works around it via the manifest | **Aravinth: `categories.js`.** The same repo answers task 3, so one request covers both |

### Closed

| # | Contradiction | Closed by |
|---|---|---|
| C1 | The declared floor and `raw` | **v2, 11 Sep.** The manifest now carries `raw_includes_declared_floor: true` and check 8 adds the floor before comparing. The engine already followed DS-008 §4.1 — no change needed |
| C2 | Check 7 had no method guard | **v2, 11 Sep.** Check 7 now guards like checks 5, 6 and 8. Its comment: *"a correct windows reversal lands in the same window as its order and cancels exactly there too. Checks 5, 6 and 8 all guard this way; check 7 did not."* |
| C4 | Task 13 says `version`; Kala ruled `model_version` | **v2, 11 Sep.** The manifest's score-store contract now pins `model_version_field: "model_version"` |

---

## Log

### 11 September — task 16 delivered: the display script runs against our store

Kala sent `show_demo.py` (DS-015 task 16). **It ran against our export with no
changes to either side**, which is what the score-row contract in the v2 manifest
was for: it reads the field names from `ml_demo_meta.score_store_contract`
instead of hardcoding them.

It also accepts either input shape — a `mongoexport` file with `{"$date": ...}`
wrappers or a live connection — so the file already sent works directly.

**Nine steps, all producing the right numbers from our data**

| Step | Shows | Our output |
|---|---|---|
| 1 | Opening statement | 5,652 rows, three methods |
| 2 | Raw vs share (U01, U12/U13) | U12 has 10x U13's events; both shares 0.500 |
| 4 | Decay on vs off (U04) | Home & Living leads with decay, Electronics without — the order reverses |
| 5 | Cold start and the floor (U07, U05) | U05's three floors at 10 outrank Electronics' 25 events at 4.52 |
| 6 | Bottom of the ladder (U11) | Falls to popularity over 30 days |
| 7 | Both methods (U14) | 38.20 / 41.90 decay; 16.00 / 24.00 windows |
| 8 | The reversal (U16 vs U17) | Difference 15.16, with the wrong answer shown beside it |
| 9 | What the model refuses to count | Three counters — see below |

Step 3 is folded into step 2 (`--step 3` is kept as an alias). There is no step
10: conformance was withdrawn under DS-018 C-66.

**Step 9 is the one that matters most.** It prints what the engine's counters
*should* say and states that the engine's own must match:

```
U02  sub-threshold views     20 events,  8 counted, 12 short views
U08  unresolved categories   15 events,  9 counted,  6 no category
U10  timestamp failures      20 events, 15 counted,  5 bad time
```

**Ours match exactly.** U08's 6 plus U06's 20 are the 26 unresolved from the last
run; U10's 5 is our 2 missing plus 3 future; U02's 12 are inside our 1,188
sub-threshold total.

Worth recording that **two days ago they would not have matched** — the
unresolved counter read 0 and U08 was scoring those six events. Step 9 would have
been the step that exposed it, on the day.

**C5 is now blocking both sides.** Her own code, at line 222:

> *"A name outside the canonical 23 is not automatically a drop: U06's List 1
> names resolve through LEGACY_LABEL_MAP. This script cannot read that map, so it
> trusts the manifest."*

She worked around it by reading the manifest's `unmappable` list. The engine
cannot do that — the manifest is demo metadata and the engine has to run on live
data too. `categories.js` is needed either way.

### 11 September — three defects reported by Kala, plus a fourth found fixing them

All three were real, all three were mine, and none was a different task. They sat
inside task 10.

**Root cause.** DS-008 section 3.2 has two steps: resolve the supplied string
onto a canonical category, *then* key the map on the result. I implemented the
second and skipped the first, reading DS-012's "no hardcoded category list" as
permission not to resolve. It is guidance about *how* to resolve.

**The signal I ignored.** The unresolved-category counter has read **0** on every
run since it was built — against a dataset that deliberately contains three
unmappable categories. A counter built to count drops, reporting zero, was the
build saying it was not working. I reported that zero as a clean result four
times.

**The test that made it worse.** `test_u06_scores_legacy_spellings_as_supplied`
asserted all five legacy names were present and carried a docstring explaining
why that was correct. It codified the defect and then the green suite was cited
as evidence things were right.

#### Defect 1 — unmappable categories were scored, not dropped

U08's three seller-created categories were taking 43% of the profile.
`Casual Sneakers`, `Jackets`, `Sunglasses` have no path to the canonical 23.

**Fixed.** U08 is now `Home & Living 18.95, share 1.000`, one row — her target
exactly. Six events dropped and counted.

#### Defect 2 — no category mapping at all

**Partly fixed, and blocked on an input.** Resolution now runs: no legacy
spelling reaches the store, so `Fashion` and `fashion` are no longer two rows.

But the merge cannot happen without `LEGACY_LABEL_MAP`, which lives in
`backend/SOCO_BE/src/constants/categories.js` — a repo not in this workspace.
Without it, U06's five names are **dropped and counted** rather than merged:
correct per DS-008 section 3.2, and incomplete. U06 currently scores nothing and
falls to the ladder.

`test_u06_merges_once_the_legacy_map_is_loaded` is written and **skips** with a
message naming the missing export. `resolve_expected()` in the expected-value
suite sums across names that merge, so the moment the map lands both assert the
targets — 30.40 and 18.68 — without a test changing.

#### Defect 3 — event_count was inconsistent

It counted every event in the category, including the sub-threshold views the
scorer had just discarded. **Fixed** — `event_count` now comes from what
contributed. U02 reads **8**, not 20.

#### Defect 4 — stale rows, found while fixing the others

The refresh upserts and never removed a category a user stopped scoring in. After
the resolution fix, U08's three dropped categories were **still in the store**,
with shares normalised over a denominator that no longer existed, so the set no
longer summed to 1.

One sweep at the end of each refresh removes rows the run did not rewrite, keyed
on `computed_at`. First attempt was a per-user delete; that added 195 round trips
and the run timed out against Atlas.

This was latent regardless of the category bug: any category leaving a profile —
an event ageing past Method B's cut-off — would have left a stale row behind.

#### Built

- `reco/domain/categories.py` — `to_category_key()`, `CategoryVocabulary`,
  `resolve_all()`. The vocabulary is **loaded**, never written down; a test
  parses the module's AST and fails if a category name reaches executable code.
- `scripts/export_categories.py` — exports `categories.js` to JSON. Falls back to
  `post_picker_categories.txt` (the canonical 23, no map) and marks the result
  `legacy_map_loaded: false`, which the engine warns about on every startup.
- `ReadStats.unmapped_category_values` and `unmapped_examples` — category values
  dropped, counted separately from whole events, with the strings recorded.

#### Result

```
recency_decay  1884 scores, 193 of 195 users
dropped at read 31 (unresolved category 26, missing timestamp 2, future 3)
stale rows removed 8
```

The unresolved-category counter now reads **26**, not 0.

**Data checks: 14 passed, 0 failed, 4 pending.** Check 8 covers 37 narrated
scores rather than 45 — the eight that vanished are U06's five and U08's three,
which is the fix showing up in the count.

**Tests:** 345 passing, 1 skipped. 28 new, including the resolver, the stale
sweep, and rewrites of the two tests that had locked in the defect.

**Needed from Aravinth or Kala:** `categories.js` exported to JSON, for
`LEGACY_LABEL_MAP`. Until then U06 cannot demonstrate a merge.

### 11 September — task 15: Method two, time windows

**All of Allen's engine work is now complete.**

**Refactored first.** MB7 requires the floor to be added by a *shared code path*,
so a difference in outcome between the methods is attributable to time treatment
alone. Two copies of the qualified-view gate would drift and quietly break that
claim.

`methods/common.py` now holds everything both methods share — the view gate, the
weight lookup, full weight to each category, reversal aging, the declared floor.
Each method supplies one function:

```
time_factor(age_days, category) -> float
```

Method A returns `2 ** (-age / H)`. Method B returns the weight of the window the
age falls into, or 0 beyond the last boundary. That is the entire difference
between them, and now it is the entire difference in the code too.

Method A's expected-value suite passed unchanged after the refactor.

**Built** — `methods/interest_windows.py`. Three disjoint windows from P-10 and
P-11: 0–7 days ×0.5, 8–30 ×0.3, 31–90 ×0.2, and nothing beyond 90. Boundaries are
inclusive upper bounds, matching how the data checks band the same events, so
both agree where U18's cliff falls.

**Run over all users**

```
time_windows  1892 scores, 194 of 195 users, 20.3s, 0 coherence failures
```

**The comparison, on the narrated users**

| User | Method A (decay) | Method B (windows) |
|---|---|---|
| U14 | Fashion 41.90 / Electronics 38.20 — 9% apart | 24.00 / 16.00 — 50% apart |
| U18 | Home & Living 2.59 / Beauty 1.19 | 4.00 / **0.00** — Beauty past the cliff |
| U04 | Home & Living 118.54 / Electronics 16.98 | 54.80 / **0.00** — Electronics all past 90 days |
| U17 | 35.29 — reversal cancels | 16.80 — reversal cancels |

Every one matches what `ml_demo_meta.expected` predicted in prose.

**Data checks: 14 passed, 0 failed, 4 pending.** The two new pendings are checks
5 and 7 declining to grade `time_windows`, for the same reason they decline
`recency_decay_h_inf` — their expected values are derived from decay arithmetic.
Predicted before the run, and correct.

**Tests:** 315 passing (39 new). Including MB3's negative control: a five-day-old
click is worth 2.50, not the 5.00 that nested windows would produce, and MB8's
U15 hand calculation — six recent, four medium, two long, summed on paper and
asserted.

### 11 September — tasks 17 and 20: the fallback ladder and the stamp

Built together because they are the same response shape — adding fields to it
twice would have been wasted work.

**Built**

- `reco/domain/profile.py` — `Profile` and `Rung`. A profile is never a bare list
  of categories: it always names the rung, whether it is personalised, and the
  method and version that produced it.
- `reco/read_path.py` — the ladder, first match wins.
- `reco/data/readers.py` — `read_category_popularity()` for rung 3, counted over
  the P-27 window. Counts events rather than weighted score: rung 3 answers
  "what is the platform interested in", and weighting by purchase value would
  answer what sells instead.
- `reco/api/profiles.py` — `GET /profile/{user_id}`. Always 200; there is no
  404 for an unknown user, because the ladder's whole purpose is that nobody is
  served nothing.
- `scripts/show_ladder.py` — walks the ladder for named users.

**Verified live**

```
U04   RUNG 1   personalised score              Home & Living 0.875
U07   RUNG 2   declared interests, no activity  6 categories at 0.167
U11   RUNG 3   platform popularity              Fashion & Apparel 0.129 (n=231)
```

Through the HTTP endpoint as well as the library.

**One real bug found and fixed.** U07 first came out as **rung 1**, because the
refresh writes a floor-only score for anyone who declared interests and has done
nothing — so a row existed, and the read path served it as personalised.

Rung 1's condition is "has activity **and** a fresh score", not "has a row in the
store". Keying it on the row's existence made **rung 2 unreachable entirely** —
and rung 2 is the common case at launch, not the exception. The read path now
checks whether any event contributed (`sum(event_count) == 0`), and two tests
hold it.

**Also corrected:** rung 2's description said "not personalised" while its
`personalised` flag was true. It is specific to the user — they chose those
categories — it just has no behaviour behind it yet. The wording now says that.

**Tests:** 276 passing (26 new for the ladder).

**Still to do on the ladder:** rungs 4 and 5 are implemented as fall-throughs to
rung 3 with distinct logging, per the spec. They are exercised by tests but not
by demo data, since no demo score is stale and the store is reachable.

### 11 September — `reference/v2` received: all checks now pass

Kala sent a second version of the dataset and the checks. **Both defects reported
yesterday were accepted and fixed**, and the score-store contract was widened
from four fields to the nine the engine already writes.

**What changed**

| | v1 | v2 |
|---|---|---|
| Contract fields | `user_id, category, method, raw` | all nine, including `share`, `event_count`, `model_version`, `window`, `computed_at` |
| Floor | undeclared; check 8 compared against behavioural raw | `raw_includes_declared_floor: true`, and check 8 adds the floor |
| Check 7 | no method guard | guards like checks 5, 6 and 8 |
| `model_version` | not mentioned | `model_version_field: "model_version"` |
| Reference date | 04:22:58 | 10:28:50 — regenerated, 6 hours later |

**The dataset itself is unchanged in substance.** Same seed (20260909), same
6,361 events, same 205 orders, identical `expected_raw`, and the age profile of
every event is identical to six decimal places — it was re-anchored, not
rebuilt.

**No engine change was needed.** Everything the engine already wrote matched the
widened contract. Method A's expected-value suite passed against the re-anchored
data before anything was reloaded.

**Actions taken**

- Promoted v2 over `reference/` (v1 kept as `*.v1.py.bak`)
- Reloaded the three `ml_demo_*` collections
- Re-ran both passes — 1,892 scores each, 0 coherence failures
- Re-exported 3,784 rows

**Result: 13 passed, 0 failed, 2 pending.** Both pendings are correct: check 5
and check 7 derive their expected values from decay arithmetic and now decline to
apply them to the decay-off method.

Check 9 drift is down to **0.01 days**, closest event 23.9 hours from a boundary.

### 11 September — task 10, 11, 12: Method A built, run and verified

**Built**

- `reco/methods/context.py` — `ScoringContext`, the whole of what a method may
  see. Frozen. Carries tunables, declared interests, order creation times, the
  reference instant, and whether decay applies.
- `reco/methods/interest_decay.py` — `score(events, ctx)`. Pure: no database, no
  I/O, no mutation. Also the exact incremental path,
  `raw_new = raw_old × 2^(-delta/H) + new events`.
- `reco/refresh.py` — reads the sources once, scores every user, normalises to
  shares, writes each user's whole map in one call. Returns a run record.
- `reco/data/readers.py` — bulk readers, so 195 users is one scan rather than
  195. `postevents` has no `{user_id, created_at}` index, so per-user queries
  would each scan the whole collection.
- `scripts/load_demo_data.py` — **a gap no numbered task covered.** The generator
  emits JSON; the engine reads collections. Nothing bridged the two.
- `scripts/run_refresh.py` — the CLI, with `--as-of-dataset`.

**Run against the demo profile**

```
ml_demo_events 6361 · ml_demo_users 195 · ml_demo_orders 205   loaded
recency_decay          1892 scores, 194 of 195 users, 20.3s
recency_decay_h_inf    1892 scores, 194 of 195 users, 20.7s
```

Dropped at read: 2 missing timestamps, 3 future, 0 unresolved categories.
Dropped at scoring: 1188 sub-threshold views, 0 views without a duration.
Reversals: 1 applied, 0 unaged. **Coherence failures: 0.**

**Verified**

- All 20 narrated users match `expected_raw` to within 5e-6 (task 10)
- U16 50.451544 vs U17 35.294378 — differ by exactly 20 × 2^(-12/30) (task 11)
- U04 with decay: Home & Living 118.54 > Electronics 16.98.
  Without decay: Electronics 190.00 > Home & Living 140.00 (task 12)
- Export written to `export/ml_user_interest_scores_demo.json`, 3784 rows

**Tests:** 250 passing.

### 11 September — seven corrections found in the reference folder

Reading `reference/` showed that Method A would have failed on contact. All seven
are now fixed and each has a test.

| | Was | Is | Why it mattered |
|---|---|---|---|
| 1 | method `A_recency_decay` | `recency_decay` | The checks match the name verbatim; a different spelling leaves checks 5–8 PENDING for ever and reads as a contract mismatch, not a defect |
| 2 | categories forced lowercase | any string | Real data is title case and deliberately carries `home & decor`, `Casual Sneakers`. Would have refused nearly every score |
| 3 | event types `view`, `click` | `product_view`, `product_click`, … | The generator spells them long; `postevents` spells them a third way |
| 4 | future judged against `now()` | against a reference date | U10's rows sit just ahead of it; running a day late would start counting them |
| 5 | orders read `created_at` / `order_status` | `placed_at` / `status` | The one reversal would never have been aged |
| 6 | users read `interest` | `declared_interests` | Every declared floor would silently have been zero |
| 7 | `ml_demo_posts` in the profile | removed | It does not exist; the generator writes three collections |

### 11 September — decay-off given its own method value

Nisha flagged that both runs under one name makes check 8 compare decay-off rows
against decay-on expectations. Correct.

`recency_decay_h_inf` is now a third method value, and the refresh maps
method → (module, window, decay on/off), so the two **cannot** be written under
one name.

**Closed contradiction:** "half life set to infinity" is not expressible as P-04 —
its permitted range is 7–180 and DS-007 calls that a hard bound. Decay-off is
therefore `decay_enabled`, an engine switch explicitly **not** a DS-007
parameter. With it off the half-life is `math.inf`, which makes every decay
factor exactly 1 — one formula, no second code path to drift.

### 10 September — Kala's rulings

| Item | Ruling |
|---|---|
| Conformance | **Out of scope.** Task 19 drops; the weight-table question and extracting `updateUserInterests` fall with it |
| Uniqueness key | Keep `model_version`: `user_id + category + method + model_version` |
| Field name | `model_version`, not `version` |
| `categories` | Plural, an array — the generator uses it |
| Event row | Five unconditional + two conditional. Matches the generator exactly |
| Reversal | `purchase_reversal` at weight −20 carrying the original `order_id` |
| Demo score collection | `ml_user_interest_scores_demo` |
| DS-007 | v1.1 is the authority. 27 parameters |
| Home & Living | **Four keys, three merges.** `home & decor`, `kitchen & dining`, `bedding & bath` are genuine; `home_&_living` is a spelling repair |
| Cold-start ladder | Keep the rung 4/5 fall-through |

### 10 September — tasks 5, 6, 7

- **Task 5:** `ml_user_interest_scores`, unique index on
  `(user_id, category, method, model_version)`, plus `(user_id, method,
  computed_at)`. Four metadata fields non-nullable in the Pydantic model *and* in
  a `$jsonSchema` validator. `writers.py` is the only module that writes, behind
  one guard that refuses any non-`ml_` collection.
- **Task 6:** `DATA_PROFILE` moves events, posts, users, orders and the score
  target together. An AST test fails the build if a collection name appears as a
  literal outside `config.py`.
- **Task 7:** `EVENT_CONTRACT.md` plus `domain/event_contract.py`, so the schema
  is enforced rather than merely agreed.

### 10 September — three defects found while building

- **Atlas credentials reached a pytest traceback.** Both URIs are now
  `repr=False` with a test enforcing it. **The exposed password still needs
  rotating.**
- **Database names are case-sensitive**, and a wrong case returns nothing without
  raising. Startup check added.
- **The engine was pointed at a `registers` collection that does not exist.** The
  `interest` array is on `users`. Would have made every declared floor zero.

---

## Environment notes

- Two Atlas clusters. `cob9whd` is SOCO's, read-only, database `soco`.
  `4b7z1ko` is the build cluster, database `SoCo`. **In production the `ml_`
  collections must live in the same database as the app data** (Q14).
- `4b7z1ko` paused itself on 11 Sep and refused TLS handshakes for about two
  hours. Symptom: TCP connects, then `TLSV1_ALERT_INTERNAL_ERROR`. Resume it in
  Atlas.
- The `ml_` write credential is still `atlasAdmin` — unscoped, and the opposite
  of what task 5 requires. Open with Aravinth.

## Still open with Aravinth

1. The `ml_`-scoped write credential
2. `db.postevents.createIndex({ user_id: 1, created_at: -1 })`
3. Confirm `registerModel` is backed by the `users` collection
4. Is `GET /getInterst` still called
5. Has `migrate-interest-scores.js` been run
