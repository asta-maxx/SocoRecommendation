# ENG-04: POST /v1/events, receive and store events

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | ENG-02 (built) |
| **Needed by** | **APP-12** (Aravinth's event route), ENG-06, ENG-10, ENG-25 |
| **Status** | **Built** (29 Sep 2026). The check passed on dev (`Tracing/checks/ENG-04_2026-09-29.md`). Becomes Passed when re-run on test. `INGEST_TOKEN` still to be generated for real and handed to Aravinth |
| **Spec** | Build List ENG-04; DS-017 §3, §4.6, §6.1, §7; X-02, X-08; Capture Register F66–F68 |

---

## 1. What the item requires

From the Build List row:

1. Accept `{"events": [...]}`, at most 100 per call, with `Authorization: Bearer <INGEST_TOKEN>`.
2. Generate `INGEST_TOKEN` and give it to Aravinth privately.
3. Reject an event (each check applies only to events that carry the field) if it has:
   - a position of 0 (impressions and clicks);
   - a surface other than feed or product (requests);
   - an item_type other than post or product (impressions and clicks);
   - no `request_id` on `recommendation_request`, `_impression` or `_click`. It may be empty on add_to_cart, order_placed, social_interaction and content_feedback; order_state_changed has none.
4. Remove duplicates by `event_id`.
5. Store in `ml_events`: unique `event_id`, indexes on (user_id, time) and `request_id`, no expiry shorter than 365 days.
6. Reply 200 with `{"accepted": n, "duplicates": n, "rejected": [{"event_id", "reason"}]}`.
7. A daily reconciliation job for the four pairs:
   - counts within 1%;
   - share of rows carrying request_id, item_id and time within 1%;
   - a 100-event sample matched one to one on user, item and time to the second, agreeing on request_id, position and item_type.

   After 7 days in a row, record the switch date, tell Aravinth to stop writing the old collections, and use the date in the ENG-03 rule.

The Wave 1A event names: `recommendation_request`, `recommendation_impression`,
`recommendation_click`, `add_to_cart`, `order_placed`, `order_state_changed`,
`social_interaction`, `content_feedback`. Every event carries `event_id`,
`event_name` and `user_id`.

**Check:** "Send the same batch twice: the second reply shows all duplicates. An
event with position 0 is rejected with a reason."

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–7 are the Build List's parts, and A–B are extras.

### 1. The endpoint, the batch and the token: done

`reco/api/events.py`, `POST /v1/events`:

| Response | When |
|---|---|
| **200** | `{"accepted", "duplicates", "rejected"}`. A bad event never fails the call; it's listed under `rejected` and the rest are stored |
| **400** | `{"error": "invalid_body" \| "too_many_events", "detail"}` when the body isn't `{"events": [...]}`, isn't JSON, or has more than **100** events (DS-017 §7, AS-05) |
| **401** | `{"error": "unauthorized", "detail"}` for a missing or wrong bearer token |
| **503** | `{"error": "engine_database_unavailable", "detail"}` if `ml_events` can't be written. SOCO_BE retries with the same event_ids, so nothing is lost or doubled |

Error bodies follow DS-017 §4.6. The token is `Settings.ingest_token`, read from
`INGEST_TOKEN`, `repr=False`, compared in constant time (`hmac.compare_digest`).
With no token configured, every call is refused and an error is logged.

### 2. `INGEST_TOKEN`: built; handover still to do

`scripts/generate_ingest_token.py` prints a new 32-byte URL-safe random token and
writes it nowhere. To put it into use:
- **dev:** add `INGEST_TOKEN=<token>` to `.env`, which is gitignored;
- **test and production:** set it in the server environment (SD-08);
- **Aravinth:** hand it over **privately**, never in a file, email or group chat.

**Not done yet:** the real token hasn't been generated or handed over. That's
Allen's action.

### 3. The rejection rules, exactly as written: done

`reco/events/ingest.py`, `reason_to_reject(event)`. Each event is rejected, with
its reason in the reply, only for:
- a missing `event_id`, `event_name` or `user_id`, or a non-string `event_id`;
- an `event_name` that isn't one of the 8;
- `position == 0`;
- a `surface` not in {feed, product};
- an `item_type` not in {post, product};
- `request_id` missing, null or blank on the three request/impression/click events.

Each check runs only if the event carries that field. Nothing else is rejected:
the pack lists no other rule. Formats such as UUID v4 and 24-hex ids are the
sender's contract (DS-017 §3); the acceptance queries in ENG-23 (e.g. A3, "no
position below 1") measure them.

### 4. Duplicates removed by `event_id`: done

- **Within a batch:** a repeated `event_id` counts as a duplicate and is stored once.
- **Across batches:** the unique `event_id` index on `ml_events` (ENG-01) makes the database refuse a repeat. `writers.insert_events` uses `insert_many(ordered=False)` and counts duplicate-key errors (code 11000) as duplicates. Any other write error is raised, giving a 503.

### 5. Stored in `ml_events`: done

- **As sent:** each event is stored exactly as sent, plus `received_at`.
- **`server_ts`:** stored as a date when it's a readable time, so the (user_id, server_ts) index and the ENG-03 day windows work.
- **`client_ts`:** kept exactly as sent (DS-017 §3).
- **Indexes:** the three, with no expiry, created in ENG-01 (`ensure_engine_collections`).

### 6. The reply: done

`{"accepted": n, "duplicates": n, "rejected": [{"event_id": ..., "reason": ...}]}`.
Each call is also logged as a `reco.events` line: `events received`, with the three counts.

### 7. Daily reconciliation, and the switch date: done

`reco/events/reconcile.py`, run by the job `python -m reco.jobs reconcile_events`,
which reconciles **yesterday (UTC)**. ENG-07 schedules it nightly.

For each pair (new `ml_events` name vs old collection, read through the ENG-03
parsers, which serve both):
1. **Counts:** `|new − old| ≤ 1%` of the larger.
2. **Complete-row share:** the share of rows with `request_id`, an item and a time, compared within 1 percentage point. The item is `item_id` for impressions and clicks, `target_id` for feedback, and none for requests, which carry no item.
3. **Sample:** up to 100 new rows, in a shuffle seeded by the day, so a re-run draws the same sample. Each is matched **one to one** to an unused old row on user, item and time truncated to the second. Every matched pair must agree on `request_id`, `position` and `item_type` wherever the records have those fields.

**Storing results and fixing the date:**
- The day's result goes to `ml_measurements`, with `measure: "event_reconciliation"`, one document per day, and a re-run replaces it.
- **7 days in a row** that each hold, meaning **all four pairs** pass and the day had events, fix **that 7th day** as the switch date. It's stored once in `ml_measurements` (`measure: "event_source_switch"`, with the evidence days) and never moved afterwards.
- A WARNING log line says: *"tell Aravinth to stop writing the old collections"* (recommendationrequests, recommendationimpressions, recommendationclicks, recommendationengagements, contentfeedbacks).
- `reconcile.switch_date(settings)` returns the date for the ENG-03 rule (`fetch.read_switched`).

**Choices where the pack is silent:**
- UTC days.
- A pair with no rows on either side passes, but a day with no rows in any pair isn't evidence: it doesn't count, and it breaks the run.
- Counts are compared within 1% of the larger.
- Requests are matched on user and time.
- The results and the date are stored in `ml_measurements`.

### A. Extra: `scripts/show_events.py`: done

A read-only view of `ml_events`: counts by event name, the newest events (name,
time, `event_id` only), and the switch date. It works with `ML_MONGO_DB=` for
throwaway databases.

### B. Extra: checklist section 5: done

`scripts/run_checklist.sh` now runs ENG-04's tests and the live check: first send,
same batch again, position 0, and no token. It uses port 8192, a throwaway token
and `reco_demo`.

---

## 3. Configuration reference

| Variable | Meaning | Default |
|---|---|---|
| `INGEST_TOKEN` | Bearer token for `POST /v1/events` (and, AS-04, `/v1/recommendations`) | empty: every call refused |

No new settings-file values. The batch limit (100) and forward timeout (2 s) are
already in `settings/engine.toml` (`events.forward_batch_max`,
`events.forward_timeout_seconds`), as values SOCO_BE follows.

---

## 4. Tests

- **`tests/test_events_ingest.py` (44 tests):**
  - the 8 names;
  - every rejection rule and its reason;
  - checks applying only to events that carry the field;
  - batch shape and the 100 limit;
  - stored as sent, with `server_ts` as a date and `client_ts` untouched;
  - the token: right, wrong, missing, none configured;
  - the reply counting within-batch duplicates;
  - **the Build List check** with the store faked, **and against a real `ml_events` with its unique index**.
- **`tests/test_events_reconcile.py` (14 tests):**
  - each of the three tests, passing and failing;
  - time to the second;
  - one-to-one matching;
  - a repeatable 100-sample;
  - requests without an item;
  - empty pairs;
  - against a database: **7 matching days fix the switch date on the 7th and never move it**, a failing day breaks the run, and days with no events don't count.

**Result on 29 Sep 2026:** 529 unit tests passed (1 skipped) and 37 database tests passed.

**Live check (dev, `reco_demo`, throwaway token):**
- first send `{"accepted":3,"duplicates":0,"rejected":[{…"reason":"position 0 is not allowed: positions count from 1"}]}`;
- same batch again `{"accepted":0,"duplicates":3,…}`;
- no token **401**;
- `ml_events` held exactly 3 events.

---

## 5. Runbook

```bash
.venv/bin/python scripts/generate_ingest_token.py        # a new token; put it in .env (dev) / server env
.venv/bin/python -m reco.jobs reconcile_events           # reconcile yesterday (UTC)
.venv/bin/python scripts/show_events.py                  # what's in ml_events; the switch date
curl -X POST http://127.0.0.1:8100/v1/events -H "Authorization: Bearer $INGEST_TOKEN" \
     -H "Content-Type: application/json" --data @batch.json
```

---

## 6. Open

| Open item | Needs |
|---|---|
| Generate the real `INGEST_TOKEN`, put it in dev `.env`, hand it to Aravinth privately | Allen |
| APP-12: SOCO_BE forwards events here, still writing the old collections too | Aravinth |
| Schedule `reconcile_events` nightly | ENG-07 |
| **`contentfeedbacks` doesn't exist.** The content-feedback pair then has old = 0; once feedback flows into `ml_events`, its counts differ and no day holds, so **the switch date can't be fixed** until feedback is written to both | Aravinth to confirm where E13 is written |
| **Time to the second:** the old `/feed/*` rows and the new events must carry the **same** `server_ts` to the second, or the sample test fails. SOCO_BE should stamp once and write the same value to both | Aravinth, for APP-12 |
| Re-run the check on **test**; then mark Passed | The test server |

---

## 7. Files changed

| File | Change |
|---|---|
| `reco/api/events.py` | New: the route, token check, error bodies |
| `reco/events/ingest.py` | New: rules, duplicates, storing, reply |
| `reco/events/reconcile.py` | New: daily reconciliation, switch date |
| `reco/store/writers.py` | `insert_events`, `read_events`, `record_reconciliation`, `read_reconciliations`, `record_switch_date`, `read_switch_date` |
| `reco/config/__init__.py` | `ingest_token` (`INGEST_TOKEN`) |
| `reco/jobs/__main__.py` | Job `reconcile_events` |
| `reco/main.py` | Registers the route |
| `scripts/generate_ingest_token.py`, `scripts/show_events.py` | New |
| `scripts/run_checklist.sh` | Section 5 (ENG-04) |
| `.env.example` | `INGEST_TOKEN` |
| `tests/test_events_ingest.py`, `tests/test_events_reconcile.py` | New |

## 8. Demo

`obsidian/Demos/Demo - ENG-04.md`.

**Whole checklist:** `bash scripts/run_checklist.sh`.
