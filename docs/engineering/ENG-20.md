# ENG-20: Measure speed, before and after

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 4 (within 22 working days). Part 1 is due at once: the row says it "needs nothing and should be done this week" |
| **Waits on** | Part 1: nothing in the pack. In practice, SOCO_BE's `/dashboard-feed` URL and a test user's token from Aravinth. Part 2: ENG-06 (serving; in progress) and the test server (ENG-01) |
| **Needed by** | ENG-24 (go-live rule), and the pool size setting (ENG-13) |
| **Status** | **In progress** (13 Oct 2026). Part 1's script is built and tested against a local stand-in; the real measurement waits on the URL and token. Part 2 not started |
| **Spec** | Build List v1.3 ENG-20; Settings sheet, M2 retrieval "Pool size"; DS-017 v2.5 §4.3 (timing: 200 ms p95 at SOCO_BE, 250 ms hard timeout); SDA v1.6 stage limits (retrieval 80 ms, ranking 80 ms, network and serialisation 40 ms); AS-07 |

---

## 1. What the item requires

From the Build List v1.3 row, *What to build*:

> 1. Now: measure today's /dashboard-feed call end to end over at least 1,000 requests, as p50, p95 and p99. Save the numbers (see the Home sheet). If p95 is over 120 ms, cut the pool from 300 to 200 yourself.
> 2. Once serving works: load-test POST /v1/recommendations at realistic volume.
>
> Targets:
> - 200 ms at p95, measured at SOCO_BE;
> - stage limits: retrieval 80 ms, ranking 80 ms, network and serialisation 40 ms.
>
> If the target is missed, cut the pool size (300) first.

*Waits on:* ENG-06 ("Part 1 needs nothing and should be done this week. Part 2 needs serving (ENG-06).")

*How to check it is done:* "Part 1 numbers are saved. Part 2 has p95 of 200 ms or less at test volume."

Settings sheet, Pool size: 300, range 100 to 2,000. "Cut to 200 if today's feed p95 is over 120 ms, or if the engine's p95 goes over 200 ms (ENG-20). Raise only if the engine's p95 stays under 150 ms for 4 weeks." AS-07: "A 200 ms p95 is achievable, with a 250 ms timeout. Today's feed time is measured in ENG-20. The pool size is cut first, then the ranking is simplified."

Home sheet: save each check's result as `<item ID>_<date>` in the shared folder "Wave1A checks" (Sanjai to create it).

## 2. What was built, subtask by subtask

### 1. Time today's `/dashboard-feed` (part 1) — 🔨 script built; real run waits on access

`scripts/time_dashboard_feed.py` (standard library only).

- Reads `SOCO_FEED_URL` (the full URL, query string included), optional `SOCO_FEED_TOKEN` (sent as `Authorization: Bearer`), `SOCO_FEED_METHOD` (GET by default) and `SOCO_FEED_BODY` (JSON, for POST). None of these are printed or saved.
- Refuses fewer than 1,000 requests (exit 2), per the row.
- Sends 10 untimed warm-up calls, then the timed calls **one after another**, so each time is one call on its own, not a queue. Timer: `time.perf_counter()` around request and full body read; 10 s timeout per call.
- Only 2xx answers are timed. Anything else (including a network failure, status 0) is counted by status and reported. If fewer than 1,000 calls answered 2xx, nothing is saved (exit 2).
- p50, p95, p99 use the **nearest-rank** percentile (the pack names no method; nearest-rank never reports a time that no call took). Also min and max.
- Writes `Tracing/checks/ENG-20_<date>.md`: the path called (not the host), the machine it was measured from, request and error counts, the five numbers, and the verdict against 120 ms.
- Exit 0: saved, p95 ≤ 120 ms (pool stays 300). Exit 1: saved, p95 > 120 ms (cut the pool).

**Where the pack is silent:** it says "end to end" but not from where. The record names the machine it ran from, because a laptop's network adds time a server beside SOCO_BE wouldn't. The best reading is from a client of SOCO_BE (the app's point of view); a laptop run is an upper bound.

### 2. Cut the pool if p95 > 120 ms — ⏳ waits on part 1's number

If the run exits 1, change `pool_size = 300` to `200` in `settings/engine.toml` with a new version number and `changed_by`. `pool_size` is tunable (100 to 2,000), so the change is accepted live and recorded in `ml_config_changes` (ENG-02). The script never edits the settings itself: every settings change carries a person's name.

### 3. Load test `POST /v1/recommendations` (part 2) — ⏳ waits on ENG-06 and the test server

Target 200 ms p95 measured at SOCO_BE, at realistic volume, on test. Stage limits 80/80/40 ms. Not started. On the laptop over HTTP to Atlas, ENG-08 measured feed p95 127 ms (1 Oct), and checklist line 6.3 missed 200 ms on 3 Oct over a slower link; neither is the official test.

## 3. Configuration reference

| Setting / variable | Value | Notes |
|---|---|---|
| `pool_size` (settings) | 300 | 100 to 2,000; cut to 200 per part 1 or part 2 |
| `SOCO_FEED_URL` | (env, not stored) | SOCO_BE's `/dashboard-feed` URL |
| `SOCO_FEED_TOKEN` | (env, not stored) | A test user's bearer token |
| `SOCO_FEED_METHOD`, `SOCO_FEED_BODY` | GET, none | Only if the call is a POST |

## 4. Tests

13 Oct 2026, laptop (Windows, Python 3 from the system; `.venv` not yet created on this laptop): run against a local stand-in server (2–10 ms per answer):

- 1,000 timed requests: p50 22 ms, p95 35 ms, p99 38 ms, 0 errors; record written; exit 0. The stand-in record was deleted (it isn't SOCO's feed).
- Token string absent from the record (0 matches).
- No URL: exit 2. 999 requests: exit 2.
- Percentile on 1..1000: p50 500, p95 950, p99 990 (nearest rank).

No real `/dashboard-feed` measurement has been taken.

## 5. Runbook

```bash
SOCO_FEED_URL='https://<SOCO_BE host>/dashboard-feed?<the app's usual query>' \
SOCO_FEED_TOKEN='<test user token>' \
python3 scripts/time_dashboard_feed.py 1000
```

Then copy `Tracing/checks/ENG-20_<date>.md` to the shared "Wave1A checks" folder. If it exited 1, cut `pool_size` to 200 (part 2 above).

## 6. Open

| What | Waiting on |
|---|---|
| SOCO_BE's `/dashboard-feed` URL, method and query, and a test user's token | Aravinth (ENG-20 → SOCO_BE) |
| Run part 1 and save the numbers | The above |
| The shared "Wave1A checks" folder | Sanjai |
| Part 2 load test | ENG-06 (and its ENG-09, ENG-17, ENG-19), the test server (ENG-01) |

## 7. Files changed

| File | Change |
|---|---|
| `scripts/time_dashboard_feed.py` | New: part 1's timing script |
| `docs/engineering/ENG-20.md` | New |
