# Engine runs

What each run produced. Numbers, so a later run can be compared against an
earlier one rather than remembered.

Newest first.

---

## Runs 6, 7 and 8 — 11 September, 17:36 · after the category-resolution fix

All three methods re-run once DS-008 §3.2 resolution was implemented. Figures are
identical across the three because only the time treatment differs.

```
recency_decay / recency_decay_h_inf / time_windows
  1884 scores each, 193 of 195 users, ~24s

dropped at read     31   (unresolved category 26, missing timestamp 2, future 3)
dropped at scoring  1188 sub-threshold views
reversals           1 applied, 0 unaged
stale rows removed  8
coherence failures  0
```

### What changed against runs 3–5

| | before | after | why |
|---|---|---|---|
| scores per method | 1892 | 1884 | U08 lost 3 unmappable rows, U06 lost 5 legacy ones |
| users scored | 194 | 193 | U06 now scores nothing at all |
| unresolved category | **0** | **26** | resolution was not running before |
| U02 `event_count` | 20 | **8** | counts what contributed, not what was read |
| stale rows removed | — | 8 | new sweep; the old wrong rows were still in the store |

### Data checks — **14 passed, 0 failed, 4 pending**

Check 8 now covers **37** narrated scores rather than 45. The eight that went are
exactly U06's five and U08's three — the fix showing up in the count.

### Display script — task 16, first run

`show_demo.py --dir reference/demo` ran all nine steps against this store with no
changes to either side.

Step 9's counter table matched the engine's own counters exactly:

```
             script says          engine reports
U02          12 short views       within 1188 sub-threshold
U08           6 no category  \    26 unresolved
U06          20 no category  /
U10           5 bad time          2 missing + 3 future
```

Against runs 3–5 they would not have matched.

---

## Run 5 — 11 September, 16:55 · `time_windows`

| | |
|---|---|
| Profile | demo |
| Anchored at | `2026-09-11T10:28:50.231381+00:00` |
| Windows | 0–7 ×0.5, 8–30 ×0.3, 31–90 ×0.2, nothing beyond (P-10, P-11) |

```
1892 scores, 194 of 195 users, 20.3s
dropped at read     5    · dropped at scoring 1188 sub-threshold views
reversals           1 applied, 0 unaged
coherence failures  0
```

### The comparison between the methods

| User | decay | windows | what it shows |
|---|---|---|---|
| U14 | 41.90 / 38.20 | 24.00 / 16.00 | 9% apart under decay, 50% under windows |
| U18 | 2.59 / 1.19 | 4.00 / **0.00** | the ninety-day cliff — events at 88, 89, 92 days |
| U04 | 118.54 / 16.98 | 54.80 / **0.00** | Electronics is entirely past the cut-off |
| U17 | 35.29 | 16.80 | the reversal cancels exactly under both |

Every figure matches what `ml_demo_meta.expected` predicts in prose.

### Data checks — **14 passed, 0 failed, 4 pending**

Store now holds 5,676 rows across three methods. Two new pendings: checks 5 and 7
declining to grade `time_windows`, for the same reason they decline
`recency_decay_h_inf`. Predicted before the run.

---

## Runs 3 and 4 — 11 September, 16:20 · on the **v2** dataset

Same two methods, re-run after promoting `reference/v2`. The dataset was
re-anchored six hours later; its substance is unchanged (same seed, same 6,361
events, identical `expected_raw`, identical age profile).

```
recency_decay          1892 scores, 194 of 195 users, 24.8s
recency_decay_h_inf    1892 scores, 194 of 195 users, 24.7s

dropped at read     5    (unresolved category 0, missing timestamp 2, future 3)
dropped at scoring  1188 sub-threshold views, 0 views without a duration
reversals           1 applied, 0 unaged
users with no score 1    (U11)
coherence failures  0
```

Figures identical to runs 1 and 2 — as they should be, since the data only moved
its anchor.

### Data checks — **13 passed, 0 failed, 2 pending**

Both previous failures are gone, and neither needed an engine change:

- **Check 8** now adds the declared floor before comparing, per DS-008 §4.1.
  *"45 narrated scores match. U20 at {'Shoes & Footwear': 20.46} plus a floor of 10"*
- **Check 7** now guards on the method, so the decay-off run reports PENDING
  rather than a false "aged from the cancellation"
- **Check 0** confirms all nine contract fields present under both methods
- **Check 9** drift down to 0.01 days, closest event 23.9 hours from a boundary

The two pendings are correct behaviour: checks 5 and 7 derive their expected
values from decay arithmetic and decline to apply them to a decay-off method.

---

## Run 2 — 11 September, 15:57 · `recency_decay_h_inf`

| | |
|---|---|
| Profile | demo |
| Read | `ml_demo_events` (6,361 rows) |
| Wrote | `ml_user_interest_scores_demo` |
| Model version | 1.0.0 |
| Anchored at | `2026-09-11T04:22:58.409339+00:00` (dataset reference date) |
| Decay | **off** — half-life infinite |

```
1892 scores, 194 of 195 users, 20.7s
dropped at read     5   (unresolved category 0, missing timestamp 2, future 3)
dropped at scoring  1188 sub-threshold views, 0 views without a duration
reversals           1 applied, 0 unaged
users with no score 1   (U11 — no events, no declared interests)
coherence failures  0
```

Written under its own method value so the checks do not read it as a wrong
answer to the decay-on question.

## Run 1 — 11 September, 15:56 · `recency_decay`

| | |
|---|---|
| Profile | demo |
| Read | `ml_demo_events` (6,361 rows) |
| Wrote | `ml_user_interest_scores_demo` |
| Model version | 1.0.0 |
| Anchored at | `2026-09-11T04:22:58.409339+00:00` (dataset reference date) |
| Decay | on, half-life 30 days (P-04) |

```
1892 scores, 194 of 195 users, 20.3s
dropped at read     5   (unresolved category 0, missing timestamp 2, future 3)
dropped at scoring  1188 sub-threshold views, 0 views without a duration
reversals           1 applied, 0 unaged
users with no score 1
coherence failures  0
```

### Spot checks

```
U04  decay on    Home & Living 118.54 | Electronics  16.98
U04  decay off   Electronics   190.00 | Home & Living 140.00

U16  raw 50.451544   U17  raw 35.294378
     difference 15.157166 = 20 × 2^(-12/30), the purchase aged from the order
```

### Data checks afterwards

`python reference/run_data_checks.py --dir reference/demo` → **12 pass, 2 fail,
1 pending**.

| | Check | Result |
|---|---|---|
| 0 | Score store matches the manifest contract | PASS — 3784 rows, both methods |
| 1 | Every event resolves to a canonical category | PASS — clean apart from U06 (5) and U08 (3), both deliberate |
| 2 | Every event carries a valid timestamp | PASS — clean apart from U10's 2 missing and 3 future |
| 3 | U04 has 60+ days between old and new activity | PASS — gap 76 days |
| 4 | U12 and U13 shares agree | PASS — both 0.500 |
| 5 | U02 reflects eight views, not twenty | PASS (decay) · PENDING (decay-off, correctly) |
| 6 | U03's tagged categories carry full weight each | PASS both — 39.12 and 50.00 |
| 7 | U16 and U17 differ by exactly the purchase | PASS (decay) · **FAIL (decay-off)** — see C2 |
| 8 | The engine agrees with the generator's arithmetic | **FAIL** — 2 of 45, both by exactly 10.00 — see C1 |
| 9 | U15's bands and U18's cliff sit where the narration puts them | PASS — drift 0.25 days, closest event 17.9h from a boundary |
| 10 | Every referenced order exists | PASS — 205 orders, 1 reversed |
| 11 | Every narrated user is present | PASS — 20 present |

**Neither failure is an engine defect.** Check 8 is the declared floor being
included in `raw` per DS-008 while `expected_raw` excludes it. Check 7's
decay-off failure is the check reusing a decay-on expected value on a method it
does not apply to — check 5 guards against exactly this and check 7 does not.

### Drift warning

Check 9 passed at **0.25 days** of drift. That window closes on its own: if the
demonstration is several days out, regenerate the dataset with `--as-of` set to
the demonstration time, or U18's ninety-day cliff moves and the narration stops
matching the screen.

---

## How to reproduce

```bash
export DATA_PROFILE=demo
python scripts/load_demo_data.py                                  # once
python scripts/run_refresh.py --as-of-dataset                     # decay on
python scripts/run_refresh.py --as-of-dataset --method recency_decay_h_inf
python reference/run_data_checks.py --dir reference/demo
```
