# Wave 1A engine plan (Allen)

**Source of truth: `docs/updated/`.** The pack is final and is never edited. This
plan adds nothing to it. It lists Allen's items in the pack's own order, with the
pack's references, and maps each one onto this repo.

| Document | Used for |
|---|---|
| `SOCO-REC_Wave1A_Build_List_App_DB_Engine.xlsx` | Items, steps, dependencies, checks, settings, assumptions |
| `SOCO-REC-DS-017_API_Contract_v2.2.docx` | Endpoints, request/response, events, method choice |
| `SOCO-REC_Service_Design_Agreement_RE-00f_v1.3.docx` | Service shape, modules, config, scores, serving (SD-nn) |
| `SOCO-REC-Fraud-and-Abuse-Policy_v1.0.docx` | Fraud rules, levels, cases, appeals |
| `SOCO-REC-DS-003a_Capture_Register.xlsx` | Event and field codes (E, F, D, X) |

If two documents disagree, follow them in this order: Build List, then DS-017, then
SDA, then Fraud Policy, then Capture Register (Build List, Home sheet).

The **full spec of every item is its row in the Build List**. The summaries below
are for navigation only. When building, work from the row.

Status per item uses the Build List's values: To build, In progress, Waiting,
Built, Testing, Failed, Passed. A pass is saved as `<item ID>_<date>` in the
shared "Wave1A checks" folder (Home sheet, *How to use it*).

---

## 1. Calendar (Build List, Home sheet: *Order of work*, *Working days*)

Working days count from the day the pack was received. This plan takes that as
**Tue 22 Sep** = day 1.

| Step | Within | Date |
|---|---|---|
| Written notice if an item can't be finished inside its step | 5 working days | Mon 28 Sep |
| Step 1: data retention, access, foundations, first app/DB fields | 7 | Wed 30 Sep |
| Step 2: event path, order events, M1 on live data, serving core | 12 | Wed 7 Oct |
| Step 3: retrieval, product ranker, promoter score, app calling the engine | 17 | Wed 14 Oct |
| Step 4: ranking, fraud, opportunity ordering, checks | 22 | Wed 21 Oct |
| Step 5: acceptance checks and monitoring | 27 | Wed 28 Oct |
| Step 6: clear test data, real content in place | before go-live | — |

"Start the next as soon as its items are done: nothing waits for a calendar date."
An item in a later step can start as soon as what it waits on is done.

---

## 2. Allen's items, in step order

Within each step, items are ordered by their *Waits on* column.

### Step 1

| Item | Summary | Waits on | Check (from the row) |
|---|---|---|---|
| ENG-01 | Environments dev/test/prod, each with its own engine DB. All 16 `ml_` collections (v1.3 adds `ml_orders`, `ml_sync_state`, `ml_item_state`, `ml_deletions`); copies kept ≥365 days from the original event time (SD-29). Same private network as SOCO_BE; give Aravinth the address. Secrets in server env only | DB-02 | Runs in all three environments; prod reaches the platform DB read-only |
| ENG-02 | One Python service, API + scheduled jobs (incl. the engine sync). The 12 modules (`sync` replaces `events`). One versioned settings file (the v1.3 Settings sheet: surface modes off/internal/live, sync timings, lists), reloaded at least once a minute, last-good on a broken file, defaults otherwise. Changes logged in `ml_config_changes`. `/health` 200/503. Structured logs | ENG-01 | Setting change applies in a minute and is logged; broken file keeps running; stopped DB → 503 |
| ENG-03 | Platform reader: IDs as 24-character strings, polymorphic actors, the field-name map, 23-category mapping, case-insensitive status, events from the engine's copy of `postevents` only (no event source switch; DB-16 migrates the older collections), native types → E codes (Capture Register sheet 4), served-item identity, undo fields kept, post-page impressions = page visits, ignored fields | ENG-02 | Unit tests read one of each record type, including text-id follows, a businessRegister actor, a product post on a platform feed list, and an order with a status log and a return request |
| ENG-04 | Engine sync (replaces the retired `POST /v1/events`, DS-017 v2.5 §7): backfill of `postevents`, `orders`, `recommendationrequests` into `ml_events`/`ml_orders` keyed on the platform `_id`; incremental read every 5 min by `updated_at` with a 2-min overlap; upsert; checkpoint in `ml_sync_state` after the write; E codes; ≥365 days; lag alert >15 min; daily reconciliation of ids and field values; order status history | ENG-02, DB-02, APP-12 | On test: (a)–(g): reconciliation matches; undo updates the copy; an hour stopped loses/duplicates nothing; same `updated_at` across a page; failure before the checkpoint re-reads; alert fires; retention shown |
| ENG-05 | SHA-256 of `<slot>:<user_id>`, first 8 hex mod 100, split/default from settings, `policy_id` = `cfg<version>.<slot>-<method>` | ENG-02 | Stable across two restarts; split change without deploy; 10,000 ids within 2 points |

**Status of ENG-01 to ENG-04 (realigned to pack v1.3 on 1 Oct 2026;** see
`Tracing/REALIGNMENT_v1.3.md`**):**

- **ENG-01:** Waiting. Dev part done: 16 of 16 collections, retention on the original event time. Test and production servers and clusters wait on Aravinth (DB-02, DB-12, DB-13).
- **ENG-02:** Built. Module `sync` replaces `events`; `/v1/events` removed; settings to the v1.3 sheet. Re-run on test later.
- **ENG-03:** Built. No event source switch; native fields, actors, item identity; the four named cases pass; every real platform document reads (8,750; 0 failed).
- **ENG-04:** Built on dev as the engine sync. Real backfill done 1 Oct: `postevents` 146, `orders` 8, `recommendationrequests` 12. The incremental read waits on `updated_at` (APP-12; 0 of 146 events had it on 1 Oct); the check (a)–(g) is to be run on test.

**ENG-20 part 1** is in Step 4, but its row says it "needs nothing and should be done this week":
- Measure today's `/dashboard-feed` over ≥1,000 requests (p50/p95/p99), and save the numbers.
- If p95 >120 ms, cut the pool from 300 to 200.

### Step 2

| Item | Summary | Waits on | Check |
|---|---|---|---|
| ENG-07 | 2 AM IST scheduler for M1, M2 method two, M5, M8 (+ monthly copy), M6, fraud. Batch then mark current. `ml_job_runs`. Score-row metadata | ENG-02 | Kill a job halfway: previous batch still served; failure in `ml_job_runs` |
| ENG-08 | Eligibility E-01..E-11, applied before scoring and on the final list; each exclusion logged. E-09 once DB-08 exists | ENG-03, DB-06 | One excluded and one kept item per rule |
| ENG-09 | Interest ladder, rungs 1–5, plus "rung 3 empty" = newest eligible posts. Rung reported on the response and E1. Cold start counted apart from fallback | ENG-03, ENG-07 | Test user per rung gets the right rung |
| ENG-10 | M1 both methods on live data. The ENG-10 weights, floor, reversal, returns, undo, incognito orders ignored, clip at 0, share, `event_count`. Deletes unnamed time-windows rows | ENG-03, ENG-04, ENG-07, APP-12 | All ENG-11 checks pass |
| ENG-06 | `POST /v1/recommendations`: request/response per DS-017 §4, incognito (no E1), E1 fields, 5% exploration, off/live, errors. Until ENG-19/ENG-17: prod surfaces off; on test, eligible posts newest first for APP-15 | ENG-04, ENG-05, ENG-09 | <200 ms on test; one E1 with `served_items` = response; off → 503 |
| ENG-11 | M1 check script, 11 checks | ENG-10, ENG-09, ENG-05 | All 11 pass, output saved |

### Step 3

| Item | Summary | Waits on | Check |
|---|---|---|---|
| ENG-12 | Four candidate sources in parallel, 20 ms each, plus the stored method-two list; overruns dropped and logged; posts ≤30 days | ENG-03, ENG-10 | Each source within its limit on test load; drops logged |
| ENG-14 | Nightly post vectors, user profiles, top 200 → `ml_user_candidates` | ENG-07, ENG-10 | Job finishes; one user's list read in ≤20 ms |
| ENG-13 | Pool of 300 at 40/30/20/10, round-robin, shortfall passed on, repost = original, dedupe, filters | ENG-12, ENG-08 | ≤300, quotas within 1, no duplicates |
| ENG-15 | Percentile within source, merge, keep higher, cut to 200 in interleaved order | ENG-13, ENG-14 | ≤200, no duplicates |
| ENG-16 | M8 both methods, per the row: eligibility, components, weights (0.40/0.40/0.20 at launch), shrinkage 20 + confidence, cohort percentile, empty-denominator and no-peer rules, trust ×0.5, monthly copy | ENG-03, ENG-07, ENG-10, DB-09 | Every eligible promoter scored, both methods, with confidence; confirmed-case promoter scores half |
| ENG-17 | M5 both methods: attribute similarity; bought-together adjusted lift ("intent" on carts until APP-22); 3-step fallback; exclusions; nightly | ENG-03, ENG-05, ENG-07, ENG-08 | Both serve on test; lift matches hand calculation for 3 pairs |

### Step 4

| Item | Summary | Waits on | Check |
|---|---|---|---|
| ENG-19 | Feed ranking 0.35/0.15/0.20/0.20/0.10, tie-breaks, variety + relax order, exploration re-check, 24 h paging | ENG-15, ENG-16, ENG-10 | Order follows the formula; variety holds; commission changes nothing |
| ENG-18 | M6 nightly → `ml_opportunity_scores`, no endpoint | ENG-16, ENG-07 | Rows for every eligible promoter; no API returns them |
| ENG-21 | Fraud R01–R12, hashed fingerprints, evidence keys, levels, strikes, queue of 20, case API (ADMIN_TOKEN, role headers, 403/409), retention, calibration. Also the Fraud Policy | ENG-03, ENG-07, DB-09 | One hit per rule on test accounts; levels move as described; API serves the admin screen |
| ENG-22 | Retrieval + M5 check script, 11 checks | ENG-15, ENG-17 | All pass, output saved |
| ENG-20 | Part 2: load test; p95 ≤200 ms; stages 80/80/40; if missed, cut the pool first | ENG-06 | Part 1 saved; part 2 p95 ≤200 ms |

### Step 5

| Item | Summary | Waits on | Check |
|---|---|---|---|
| ENG-25 | 13 weekly measures → `ml_measurements` | ENG-04, ENG-07 | First run writes all 13 |
| ENG-23 | Acceptance queries A1–A8 on test | APP-15, APP-12, ENG-19, ENG-17 | All 8 pass |
| ENG-24 | Go-live rule, safety switch, weekly report | ENG-06, ENG-11, ENG-22, ENG-23, APP-21 | Each surface live or off per the rule; first weekly report after one week |

### Step 6 and after

- **Step 6:** DB-11 (Aravinth) clears test data. Allen sets each surface live or off per ENG-24.
- **ENG-26:** method comparison every two weeks, once a slot has ≥4 weeks live and ≥2,000 impressions per method.

---

## 3. What Allen needs from Aravinth (Build List, *Waits on the other team*)

| Aravinth's item | Unblocks |
|---|---|
| DB-02 read-only login | ENG-01 |
| DB-06 blocks collection | ENG-08 |
| APP-12 event route | ENG-10, ENG-23 |
| DB-09 exemption list | ENG-16, ENG-21 |
| APP-15 serving call | ENG-23 |
| APP-21 acceptance tests | ENG-24 |

Also from the documents:

- **SD-03:** hosting is Aravinth's part (SDA §1). ENG-01 deploys onto it.
- **DB-12:** network access, once Allen gives the address.
- **DB-13:** the test environment, which every check needs (AS-20).

Allen owes Aravinth:

- **ENG-01:** the private address, for DB-12.
- **ENG-04:** nothing to hand over since v1.3 (`POST /v1/events` is retired; APP-12 is the platform side of the engine read). `INGEST_TOKEN` is now the serving token for `POST /v1/recommendations`, handed over with ENG-06.
- **ENG-06:** `/v1/recommendations` on test, for APP-15.
- **ENG-21:** the case API, for APP-17.

---

## 4. Mapping the repo onto the pack

### Modules: the 12 in SD-05, and only those

`api`, `config`, `slots`, `store`, `platform`, `eligibility`, `ranking`,
`fallback`, `events`, `jobs`, `fraud`, `monitoring`.

- Only `platform` reads the platform DB, with the read-only credential.
- Only `store` writes, and only to the engine's own DB (SD-06).

| Existing | Goes to | Change the pack requires |
|---|---|---|
| `reco/methods/*` | `slots` | Register methods by name; settings pick them (SD-12). ENG-10 weights, undo, returns, business follows, −5 feedback, clip at 0 (range −20..50, Settings sheet) |
| `reco/read_path.py` | `fallback` | ENG-09 ladder incl. "rung 3 empty"; rung on the response and E1 |
| `reco/refresh.py` | `jobs` | Batch then mark current (SD-20); `ml_job_runs` (SD-21); row metadata (SD-19) |
| `reco/data/readers.py`, `ids.py` | `platform` | ENG-03 rules |
| `reco/data/writers.py`, `mongo.py` | `store` | Engine's own DB (AS-09, SD-06); `.env.example` note saying `ml_` shares the app DB no longer applies |
| `reco/config.py` | `config` | One versioned settings file holding every Settings-sheet value (SD-07). Secrets in env only (SD-08). Reload, log, last-good (SD-09). Modes off/live (SD-10) |
| `reco/domain/*` | owning modules (`api`, `events`, `slots`, `store`) | Contract models rewritten to DS-017 v2.2; score rows to SD-19 |
| `reco/api/health.py` | `api` | 200 when both DBs readable, else 503 (SD-28) |
| `reco/api/profiles.py` | — | Not in DS-017 §2 ("anything not stated here is not part of the contract"). Remove from the service |
| `Method.RECENCY_DECAY_NO_DECAY` | — | Not in the pack. Remove |
| `DATA_PROFILE` demo switch | `config` | Kept: ENG-10 says to switch from the demo collection by setting |

Superseded documents (`SERVICE_CONTRACT.md`, `EVENT_CONTRACT.md`,
`OPEN_QUESTIONS.md`, `docs/*.html/pdf`, `reference/`) are left in place untouched
and are not built to (Home sheet, *Which document wins*).

### Left open by the pack

These are implementation details only. Each must satisfy the reference given.

- **Settings file format:** SD-07/SD-09 require one versioned file, reloaded ≥ once a minute.
- **Scheduler mechanism:** ENG-07 requires daily at 2 AM IST, and the time is a setting (SD-22).
- **How each candidate source meets 20 ms:** ENG-12, within SD-17 (no model calculation in a request).

---

## 5. Questions for Kala (K-03: in writing, quoting the item ID)

- **ENG-05 / DS-017 §4.2:** the `policy_id` example is `cfg3.interest-2.promoter-1`, but the slot name is `promoter_score`. What is the exact segment?
- **ENG-19:** paging dedupe reads request records, but incognito writes none (ENG-06). Should repeats be served to incognito users on later pages?
- **DS-017 §4.1:** `user_id` is required, yet a missing one means "default method". Should the service return 400 or serve?
- **DS-003a Read me:** it says 65 fields, but the Fields sheet runs F01–F73.
- **Home sheet, *Working days*:** does 2 Oct count as a working day?
