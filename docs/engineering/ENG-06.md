# ENG-06: POST /v1/recommendations, return a list and record it

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days) |
| **Waits on** | ENG-04 (built), ENG-05 (built), ENG-09 (fallback ladder: built 14 Oct 2026), ENG-29 (adapters: built; item 6, the item adapter, done here) |
| **Needed by** | APP-15 (Aravinth's serving call), ENG-20 (load test), ENG-24 (go-live rule and safety switch) |
| **Status** | **In progress** (1 Oct 2026). Built to the row's own interim clause: the contract, the E1 record (with `slot_methods`, F71, and `scored_not_served`, F72), surface modes, exploration, the error bodies, no retries with a per-request time limit (SD-26) and the item adapter (F10, X-16) are done and tested. Since `11e515e` the list is items that pass ENG-08's rules E-01 to E-12, newest first, re-checked just before it is returned. Since 14 Oct 2026 the feed reports the ENG-09 ladder rung (`fallback_step`; see ENG-09 §2 item 6). Waits on ENG-17 and ENG-19 (ranking, and the 24-hour page dedup). On dev the product surface returns **0 items** (every seller lacks `status`: open question 17), so checklist 6.4 fails there until that is answered. Both surfaces stay **off** in `settings/engine.toml` |
| **Spec** | Build List v1.3 ENG-06 (and ENG-08, ENG-09, ENG-17, ENG-19, ENG-29 item 6; Settings sheet "Serving"); DS-017 v2.5 §2, §3, §4.1–4.6; SDA v1.6 SD-10, SD-26; AS-03, AS-04, AS-05, AS-07; Capture Register E1, F02, F05, F10, F71, F72, F75, X-11, X-16; eligibility E-01 to E-12 (ENG-08) |

---

## 1. What the item requires

The Build List v1.3 row, *What to build*, verbatim:

> Header: Authorization: Bearer <INGEST_TOKEN>. Request: user_id, surface (feed or product; anything else gets 400), page, limit (1 to 50), session_id and context_item_id (required for product). The feed surface is the For You tab only (APP-15).
>
> Response:
> - request_id (UUID v4);
> - policy_id, model_version and config_version;
> - fallback_step (or null);
> - is_exploration;
> - items: item_id, item_type, post_id, product_id, position from 1, and reason_code, which is always null in Wave 1A.
>
> For every list it builds, the engine writes a recommendation_request record to ml_events with:
> - request_id, surface, user_id, session_id and policy_id;
> - server_ts in UTC with milliseconds;
> - candidate_ids (never returned to the app);
> - served_items (item_id, item_type, post_id, product_id and position, exactly as returned);
> - config_version;
> - for each slot, the method intended and the fallback step used;
> - a sample of scored items that were not returned: 10% at random, plus every returned item, plus all items on exploration requests.
>
> Paging: each page is its own request. The ranking layer decides what a page holds (ENG-19).
>
> Mode per surface: off (returns 503), internal (engine lists only for the test accounts listed in the settings, 503 for everyone else, used for checks on production before launch) or live. Both surfaces are live from launch, provided their checks pass (ENG-24).
>
> Exploration: on 5% of feed requests (decided separately from method choice), keep the top 3 positions as ranked and shuffle positions 4 onward among eligible items. is_exploration is true on those lists. It is always false on the product surface.
>
> If a database cannot be read, return an error at once, with no retry.
>
> Until the feed ranking (ENG-19) and product ranker (ENG-17) are built, keep both surfaces off in production. On test, return eligible posts newest first, so Aravinth can test APP-15.
>
> Errors: 400 for bad input, 401 for a bad token, 503 for off or a database fault. The body is {"error": "<code>", "detail": "<text>"}.
>
> Items follow the item adapter in ENG-29.

*Waits on:* ENG-04, ENG-05, ENG-09, ENG-29. *Needed by:* APP-15, ENG-20, ENG-24.

*How to check it is done*:

> A request returns within 200 ms on test, and one request record exists with served_items matching the response. Setting a surface to off returns 503.

The v1.3 change log for this item: *"Internal mode added; item adapter; engine_position and the delivered-list record removed."* (29 Sep 2026).

### 1.1 DS-017 v2.5 section 4, verbatim

**4.1 Request**

| Field | Type | Required | Meaning |
|---|---|---|---|
| user_id | string | Yes | The person the list is for. [Assumed: AS-01, login is required, so it is always present]. If it is ever missing, the default method is used for every slot. |
| surface | string | Yes | feed or product. Any other value is rejected with 400. feed means the For You tab only: the Following, Trending and Local tabs keep their own rules and do not call the service. |
| incognito | boolean | No (removed) | Removed in v2.4. Incognito is purchase privacy only and does not change what is recorded (Section 6.3). SOCO_BE no longer sends it; the service ignores it if sent. |
| context_item_id | string | When surface is product | The product being viewed, or the product in the cart. [Assumed: AS-05] |
| page | integer | Yes | Page number, from 1. Each page is its own request. The service decides what each page holds, and leaves out items it served to that user in the last 24 hours. [Assumed: AS-05] |
| limit | integer | Yes | Number of items wanted, 1 to 50. [Assumed: AS-05] |
| session_id | string | Yes | The app session id (ses_…) from the app's SessionService: kept across restarts, and new after 30 minutes or more away (background or closed). Reported built (build list APP-01). |

**4.2 Response**

| Field | Type | Meaning |
|---|---|---|
| request_id | string | One per list. SOCO_BE keeps it with every item it shows. |
| policy_id | string | The config_version and the method used in each slot the request touched, for example cfg3.interest-2.promoter-1. |
| model_version | string | The version of the methods that produced the list. |
| config_version | string | The configuration version in force for this request. |
| fallback_step | string or null | Which step of the fallback ladder was used, or null if none was needed. |
| is_exploration | boolean | True if this list is in the exploration slice. Flutter copies it onto every impression and never works it out itself. |
| items | array | In display order. Each item has item_id, item_type, post_id, product_id, position (from 1) and reason_code (null in Wave 1A). |

> candidate_ids are never returned. They are written on the service's own E1 record only (F05).

**4.3 Rules for SOCO_BE**

> Show the list exactly as returned: no filtering, re-ordering, trimming or added items, and no pull-to-refresh reshuffle of an engine list. The service applies every eligibility rule itself, re-checks the returned items when it builds each list, and returns exactly limit items unless fewer eligible items exist.
>
> Serve log: for every list request, SOCO_BE writes one row to rec_serve_log with request_id, user_id, surface, page, origin (engine, fallback or cache), outcome (ok, timeout, error, off or skipped), elapsed_ms and the time. The operational fallback rate and the speed seen by SOCO_BE are measured from it (build list ENG-24).
>
> Caching, if SOCO_BE caches lists: only for the same user_id, surface, page, limit and context_item_id, for no longer than 60 seconds, keeping the original request_id, and dropped at once when the user blocks someone or hides an item. No new E1 is written for a reused list, and the serve log records it with origin cache. A cache keyed only by surface or post is not allowed, because one user's list would be served to another and the method split would disappear.
>
> Circuit breaker, if SOCO_BE uses one: after 5 failures in a row it stops calling the service and falls back, sending one test call every 30 seconds, and resumes when one succeeds. Each skipped call is logged with outcome skipped.
>
> Timing: the service answers within 200 ms at p95, measured at SOCO_BE [Assumed: AS-07]. The hard timeout is 250 ms [Assumed: AS-07].
>
> Exploration: on 5% of feed requests the service keeps the top 3 positions as ranked and shuffles the rest among eligible items. Those lists carry is_exploration true. Never on the product surface. The platform's own is_exploration flag on its lists (about 10% of discovery posts) is a different thing and is never set on an engine list.

**4.4 Off and live**

> Each surface has a mode in the service configuration: off, internal or live. There is no shadow mode.
>
> Live: SOCO_BE shows the returned items.
> Off: the service returns 503, and SOCO_BE falls back.
> Internal: only the test accounts listed in the service configuration get the returned items; every other request gets 503, and SOCO_BE falls back. Used for checks on production before launch.
>
> At launch: a surface is set live only if its pre-launch checks pass, otherwise off until they do.
>
> Safety switch: the service owner sets a surface to off at once if, in any one day, the fallback rate is above 10%, p95 is above 250 ms, or errors are above 2% of requests, or an acceptance check fails. It is switched back on when the cause is fixed. These are written rules. No approval is needed.

**4.5 Fallback**

> On timeout, error or off, SOCO_BE serves its own ordering (the platform lists: wave1a_v1 for the feed, prodrec_v1 for product detail and cart), which must pass the same visibility rules the app already applies: blocked authors, hidden, private, deranked or removed posts and out-of-stock products are never shown. It keeps its own request_id (req_…) and policy_id, and writes its served-list record to recommendationrequests with origin fallback, as it does today. Any policy_id that does not start with cfg is a fallback list. Fallback lists produce every event, exactly like engine lists (X-03). The labels on the platform's own product rails follow build list APP-24.

**4.6 Error responses**

| Code | When | What SOCO_BE does |
|---|---|---|
| 200 | List returned. | Shows it. |
| 400 | Invalid surface, limit or page, or missing context_item_id on product. | Logs it and falls back. |
| 401 | Missing or wrong token. | Logs it and falls back. |
| 5xx or timeout | Service fault, database unreadable, or surface off. No retries inside a request (SD-26). | Falls back at once. |

> Error codes and bodies are [Assumed: AS-05]. The body is {"error": "<code>", "detail": "<text>"}.

### 1.2 DS-017 v2.5 section 3, the item-type rule, verbatim

> **Item types.** Wave 1A cards are post or product. The service returns items in the shape the app already uses (the item adapter): on the feed, a post card that shows a product keeps its post id as item_id, with item_type as the app expects; product rails carry product ids. Every served item also carries post_id (or null) and product_id (or null) as separate fields, so a post id is never read as a product id. The same mapping is in the Capture Register (X-16). promotion, promoter and brand are reserved for later waves.

The same section fixes `request_id` for engine lists as *"a UUID v4 string, generated by the service for every list it returns"* (AS-03), positions as *"Counts from 1 … with no gaps, within each request"*, and server time as *"UTC, ISO 8601, with milliseconds"*.

### 1.3 How this was built while ENG-09 and ENG-29 are not (decided 1 Oct 2026)

ENG-06 waits on ENG-09 (the fallback ladder) and ENG-29 (the adapters). Neither
was built when ENG-06 was (ENG-29 and ENG-08 have been since, the same day; the
table says what each replaced). The row itself gives the interim: *"Until the feed ranking (ENG-19)
and product ranker (ENG-17) are built, keep both surfaces off in production. On
test, return eligible posts newest first, so Aravinth can test APP-15."* ENG-06
was built to that clause:

| Part | Interim behaviour | Replaced by |
|---|---|---|
| Feed ordering | Eligible posts, newest first | ENG-19 (ranking layer) |
| Product ordering | Eligible products, newest first, the context product left out. **The pack is silent on a product interim**; this is our choice, matching the feed's and ENG-17's own last fallback step (*"3. eligible products, newest first"*). It must satisfy ENG-17's *"Always excluded: the product being viewed"* | ENG-17 (product ranker) |
| Eligibility | The interim `reco/eligibility/basic.py`, **deleted 1 Oct 2026 (`11e515e`)** and replaced by ENG-08's rules E-01 to E-12 with the final recheck (§2 A) | Done (ENG-08) |
| `fallback_step` | ~~`null` on the response and on every slot~~ Done 14 Oct 2026: on the feed, the interest slot's ladder rung (ENG-09 §2 item 6); product and promoter_score stay `null` | ENG-09 (done) |
| Slots | Each slot records the method it **would** use (ENG-05), with `fallback_step` null | ENG-09, ENG-17, ENG-19 |
| Marker | The E1 carries `ordering: "interim_newest_first"`, so a list built before the rankers exist is never mistaken for a ranked one (and never counted as a result for a method that didn't run, ENG-09) | Removed when the rankers serve |
| Item shape | §2.11: **done** (question 4 answered 1 Oct 2026: F10, X-16) | Done |
| Score in `scored_not_served` | `null`; the interim `rank` is kept beside it (§2.4) | ENG-17, ENG-19 |
| Production | Both surfaces `off` (`settings/engine.toml`) | ENG-24 (go-live rule) |

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–11 are the parts of the row in its order,
and A–C are extras. The endpoint is `reco/api/recommendations.py`
(`recommendations()`, mounted in `reco/main.py`); list building is
`reco/ranking/serving.py`.

Order of checks in the handler: token (401) → body (400) → surface mode (503) →
method assignment → platform reads, eligibility (ENG-08) and the final recheck,
all inside the request's time limit (503 on fault or timeout, §8) → page,
exploration → E1 write (503 on fault) → 200. So a bad body on a surface that is
off still gets 400, and nothing is written for any non-200 answer.

### 1. The serving token (`reco/api/auth.py`): done

- `token_ok(settings, authorization)` accepts only `Authorization: Bearer <INGEST_TOKEN>`. The scheme is case-insensitive; the token is compared with `hmac.compare_digest` (constant time).
- If `INGEST_TOKEN` is not set, every call is refused (401) and an ERROR is logged. A missing token never means "open".
- `INGEST_TOKEN` is kept as the name of the serving token (DS-017 §3 *Authentication*, AS-04). It lives only in the environment (`.env` on dev and test, the server environment on production; SD-08, ENG-01 item 4).
- 401 body: `{"error": "unauthorized", "detail": "missing or wrong bearer token"}`.

### 2. Request checks: done

`_bad_request(body)`:

| Check | Error code (400) |
|---|---|
| Body not JSON, or not a JSON object | `invalid_body` |
| `surface` not `feed` or `product` (e.g. `opportunity`, X-11) | `invalid_surface` |
| `page` not a whole number ≥ 1 (a string `"1"` or a boolean is refused) | `invalid_page` |
| `limit` not a whole number 1–50 | `invalid_limit` |
| `surface` is `product` and `context_item_id` is not a 24-character id | `missing_context_item_id` |

- `user_id`: not checked for shape. A missing or blank `user_id` is recorded as `null` and gets the **default method in every slot** (DS-017 §4.1; `assign()` in `reco/slots/assignment.py`, `from_default: true` on the slot).
- `session_id`: kept if it is a string, otherwise `null`. Not rejected: DS-017 §4.6 lists 400 only for surface, limit, page and context, and APP-15 says *"session_id (as the app already sends it; may be null)"*.
  - **Choice (recorded 1 Oct 2026, audit).** DS-017 §4.1 marks `session_id` *Required: Yes*, but §4.6's list of 400 causes omits it, and the Build List's APP-15 allows null. The pack is silent on what to do when it is missing; we accept the request and store `session_id: null` on the E1. Rule it must satisfy: §4.6 (400 only for surface, limit, page, context) and the row's E1 field list (`session_id` is always present on the record, possibly null).
- `context_item_id` is kept only on `product`; on `feed` it is recorded as `null`.
- `incognito`, if sent, is ignored (DS-017 §4.1).

### 3. The response: done (fallback_step null until ENG-09)

```json
{"request_id": "5743bdd8-15d9-4de1-870e-b93726b5f464", "policy_id": "cfg3.interest-recency_decay.promoter_score-cohort_percentile",
 "model_version": "1.0.0", "config_version": "3", "fallback_step": null, "is_exploration": false,
 "items": [{"item_id": "6a9fd06d…5570", "item_type": "post", "post_id": "6a9fd06d…5570",
            "product_id": null, "position": 1, "reason_code": null}, …]}
```

(Dev, 1 Oct 2026, after the audit fixes; settings `config_version` 3 since ENG-29.)

- **`request_id`:** `uuid.uuid4()` per list (AS-03). Cannot collide with the platform's `req_…` ids.
- **`policy_id`:** `policy_id(*assignments, config_version=…)` (`reco/slots/assignment.py`, ENG-05) gives `cfg<config_version>.<slot>-<method name>` for each slot the surface uses, in the surface's slot order. Slot names are the settings' (`promoter_score`, not `promoter`).
  - **Names, not numbers (decided 1 Oct 2026, commit `ea88d1a`).** DS-017 §4.2's example shows numbers (`cfg3.interest-2.promoter-1`), but the Build List outranks DS-017: ENG-05 fixes *"policy_id, as cfg<version>.<slot>-<method>"*, ENG-26 says *"policy_id records method names, so history stays readable across the swap"*, and SD-15 has *"the method named in policy_id"*. A method number would mean something else after ENG-26 swaps a method into a slot. (`4db835f` briefly used numbers; `ea88d1a` restored names.)
  - The method's **number** (1 or 2) is still on the E1, per slot (`slot_methods[].method_number`, §4).

  | Surface | Slots (`SLOTS_BY_SURFACE`) | Example |
  |---|---|---|
  | feed | `interest` (M1), `promoter_score` (M8) | `cfg2.interest-recency_decay.promoter_score-cohort_percentile` |
  | product | `product_ranking` (M5) | `cfg2.product_ranking-bought_together` |

  Every engine `policy_id` starts with `cfg`; DS-017 §4.5: *"Any policy_id that does not start with cfg is a fallback list."*
- **`model_version`:** `Settings.model_version` (`MODEL_VERSION`, default `1.0.0`).
- **`config_version`:** the settings version in force. The handler takes **one** reading of the settings (`live.current()`) for the whole request, so the mode, the split, exploration and the version on the record are all from the same version.
- **`fallback_step`:** `null` (see §1.3).
- **`items`:** see 11. `reason_code` always `null` (Wave 1A). `candidate_ids` is never in the response (F05; a test asserts it).

### 4. The E1 record (`reco/store/writers.py`): done

`record_served_list(settings, record)` inserts into `ml_events` (through the
`ml_`-only write guard). `read_served_list(settings, request_id)` reads it back
(`{_id: request_id, event_code: "E1"}`).

| Field | Value | Pack |
|---|---|---|
| `_id`, `request_id` | the UUID v4 | row; `_id` makes it unique, one record per list |
| `event_code`, `event_type`, `kind` | `E1`, `recommendation_request`, `served_list` | Capture Register E1 |
| `source` | `engine` | ours: the sync's copies of platform E1s carry `source: "recommendationrequests"` (ENG-04), so the two never mix |
| `surface`, `user_id`, `session_id`, `page`, `limit`, `context_item_id` | as asked (after §2) | row |
| `policy_id`, `model_version`, `config_version` | as on the response | row |
| `server_ts` | UTC `datetime`, millisecond precision as stored by MongoDB | row; DS-017 §3 |
| `created_at` | = `server_ts` | ours: the `retention` expiry on `ml_events` runs from `created_at` (ENG-01, SD-29) |
| `candidate_ids` | every eligible item id read for the list, in order (through the end of the requested page plus one spare page for the recheck's replacements; see 5 and A) | row; F05 |
| `served_items` | **the same list object** as the response's `items` | row: *"exactly as returned"* |
| `slot_methods` | array, one entry per slot the surface touches, in slot order: `{slot, method, fallback_step: null, method_number, bucket, from_default}` | row: *"for each slot, the method intended and the fallback step used"*; Capture Register **F71** (*"array of {slot, method, fallback_step} … Present on every E1, one entry per slot touched"*). The last three keys are ours (how the method was chosen, ENG-05) |
| `fallback_step`, `is_exploration`, `is_fallback` | `null`, as returned, `false` | row; ENG-09 |
| `ordering` | `interim_newest_first` | ours (§1.3) |
| `scored_not_served` | see below; `null` on most requests | row; Capture Register **F72** |

**Fix, 1 Oct 2026 (audit, commit `d1e5427`): field names and the sample follow
the Capture Register.** The record used to carry `slots` (an object keyed by
slot) and `scored_sample` (on every request). F71 names the field `slot_methods`
and makes it an array; F72 names `scored_not_served` and says *"Present on about
10% of E1 rows, and on every exploration row"*. Both were changed to match.

**`scored_not_served`** (`serving.scored_not_served`): drawn per request from
`serving.rng`. On `sample_random_percent` (10) % of requests at random, and on
**every** exploration request, it lists every scored item of the list (all of
`candidate_ids`), each as `{item_id, score, rank, returned}`; on every other
request it is `null`. `score` is `null` until the rankers exist (ENG-17,
ENG-19); `rank` (the item's place in the interim ordering) stands beside it.
`returned` marks the items on the page, so the Build List's *"plus every returned
item"* is met on each sampled row and the passed-over items are the rest (F72:
*"Needed to measure what the engine passed over"*). Test:
`test_scored_not_served_is_on_about_ten_percent_of_requests` (400 requests: the
share with a sample is between 7 % and 25 %, every exploration row has one, and
the `returned` items equal the served ones).

**Written before the response.** If the write fails, the answer is 503
`database_unavailable` ("the served list could not be recorded"), and no list is
returned: no record, no list. Every list SOCO_BE shows from the engine therefore
has its E1.

### 5. Paging: in progress (24-hour dedup waits on ENG-19)

- Page *p* holds positions `(p−1)·limit+1` to `p·limit` of the interim order; positions restart at 1 in each response (DS-017 §3).
- `interim_candidates()` (since `11e515e`) reads the platform newest first, 250 rows first (`_READ_PAGE`) and, if that isn't enough, the rest of the scan window in one read, until it has `(page+1)·limit` eligible items (one spare page, for the recheck's replacements), the collection runs out, or it has read `MAX_SCAN_ROWS` (1,000) rows. A short last page is returned short (DS-017 §4.3: *"exactly limit items unless fewer eligible items exist"*).
  - **Choice (1 Oct 2026):** the scan cap. The pack sets no limit; without one, a surface where nothing is eligible would read the whole collection on every request (the dev product surface today, §4 Tests). Rule it must satisfy: DS-017 §4.3 allows fewer than `limit` when fewer eligible items exist; within the cap, none is missed.
- **Not yet:** *"leaves out items it served to that user in the last 24 hours"* (DS-017 §4.1; ENG-19 *Paging*, `serving.page_dedup_hours = 24`). The row gives page contents to ENG-19: *"The ranking layer decides what a page holds (ENG-19)"*.

### 6. Surface modes (`serving.surface_mode_feed`, `serving.surface_mode_product`): done

| Mode | Behaviour | Body |
|---|---|---|
| `off` | 503 for everyone | `{"error": "surface_off", "detail": "the feed surface is off"}` |
| `internal` | 200 only if `user_id` (lower-cased) matches an entry in `lists.test_accounts` whose `expiry` has not passed (`expiry >= today`); otherwise 503 | `{"error": "surface_internal", "detail": "the feed surface serves test accounts only"}` |
| `live` | 200 | |

- Read from the settings in force on every request, so a change takes effect at the next reload (every 30 s, `RELOAD_SECONDS`; ENG-02) with no restart. Changing it needs a new `config_version`, and the change is logged in `ml_config_changes`.
- Both default to **`off`** in `settings/engine.toml`, as the interim clause requires for production. ENG-24 sets them live.
- SD-10: *"Internal gives engine lists only to the test accounts listed in the configuration, and 503 to everyone else, for checks on production before launch."* Test-account entries carry account id, reason, expiry and who changed it (ENG-29 item 3).

### 7. Exploration: done

- `decide_exploration(surface, percent)`: `true` on `exploration_percent` (5) % of **feed** requests, drawn per request from its own random source (`serving.rng`), separate from the SHA-256 method bucket (row: *"decided separately from method choice"*). Never on `product`.
- `explore(items, keep_top)`: positions 1–3 (`exploration_top_kept`) kept as ordered; positions 4 onward shuffled.
- **Choice (1 Oct 2026):** the pack says shuffle *"among eligible items"*. We shuffle **within the page**, so a page holds the same items with or without exploration and paging stays stable (no item jumps to another page or disappears from both). Rule it must satisfy: top 3 unchanged, positions 4+ reordered, `is_exploration` true on the response, the record and (via Flutter) every impression. ENG-19 re-checks the consecutive-author rule after the shuffle. Reviewed against the pack on 1 Oct 2026 (question 15 in `Tracing/REALIGNMENT_v1.3.md`, "Questions (reviewed 1 Oct 2026)"): it stays a choice within DS-017 §4.3 and Build List ENG-19.
- On an exploration list `scored_not_served` is always present and holds every candidate (4; F72).

### 8. Database errors: done

- A read fails or runs out of time (platform items, the viewer's context, the engine's feedback copy, the recheck) → logged (`database unreadable`, with `request_id`, error truncated to 300 characters), then 503 `database_unavailable` ("a database could not be read").
- Engine write fails or runs out of time → 503 `database_unavailable` ("the served list could not be recorded") (4).
- **No retry** inside the request (SD-26: *"If either database cannot be read, the service returns an error at once so SOCO_BE falls back. No retries inside a request."*). A test asserts the read is called exactly once.
- Connection strings never appear in the log or the body.

**Fix, 1 Oct 2026 (audit, commit `d1e5427`): the driver's own retries are off.**
PyMongo retries a failed read or write once by itself unless told not to. Both
clients (`reco/platform/connection.py`, `reco/store/connection.py`) now open with
`retryReads=False, retryWrites=False` (SD-26, DS-017 §4.6 *"No retries inside a
request"*). Test: `test_the_database_clients_never_retry`.

**Fix, 1 Oct 2026 (same commit): a time limit per request.** Every read and the
E1 write run inside `pymongo.timeout(budget)`; the write gets what is left of it.
`request_budget_seconds()`:

| Case | Budget |
|---|---|
| `REQUEST_BUDGET_MS` set | that value |
| `ENGINE_ENV=dev` (laptop, far from Atlas) | 2 s |
| test, production | `serving.soco_be_timeout_ms` = **250 ms** |

*Choice:* the pack sets no limit for the engine's own work; SD-26 asks only for an
error at once with no retry. 250 ms is SOCO_BE's hard timeout (DS-017 §4.3,
AS-07; APP-15): past it SOCO_BE has already fallen back, so a list finished later
is never shown, and an E1 for it would record a list nobody saw. Test:
`test_the_request_budget_is_soco_be_timeout_off_dev`.

**Connections opened ahead (same commits, `11e515e`, `d1e5427`).** Both pools keep
`minPoolSize` 10 and are warmed at startup (`connection.warm()`: 10 pings in
parallel, sent with the URI's read preference so the members reads actually go
to are warmed, not only the primary). A failure to warm is logged and requests
open connections themselves. PyMongo was raised from 4.10.1 to **4.18.2**
(`requirements.txt`) for concurrent async operations: the viewer's context and
the first page of items are read at the same time.

### 9. Interim ordering: done on dev / ⏳ the real ranking (ENG-17, ENG-19)

`interim_candidates(settings, surface, page, limit, context_item_id, user_id, request_id)`:

- **feed:** `read_newest(settings, "post", …)` → posts sorted `timestamp` desc, then `_id` desc; kept if they pass `eligible_posts` (ENG-08, §A).
- **product:** `read_newest(settings, "product", …)` → products sorted `createdAt` desc, then `_id` desc; kept if they pass `eligible_products` (ENG-08) and are not the `context_item_id`.
- The viewer's context (`viewer_context`, ENG-08) is read **at the same time** as the first page (`asyncio.gather`).

`read_newest` (`reco/platform/fetch.py`) reads only the fields the parsers use
(`_FIELDS` projection) and parses each row with the ENG-03 readers. Products skip
the category lookup (no interim list needs it).

**Fix, 1 Oct 2026 (audit, commit `d1e5427`): no filter at the database.**
`read_newest` used to narrow at the database (`_servable`: posts `visibility:
"public"`, not hidden; products `Activate` and in stock) so fewer rows travelled.
That hid those exclusions from the eligibility log: ENG-08 asks that every
exclusion be logged with `request_id`, `item_id` and the rule. `_servable` was
removed; `read_newest` now runs `find({})`, and every row goes through the rules.
(This also closes the old open item about `visibility: "public"` being matched
exactly at the database while the rule ignores case.)

### 10. Error bodies: done

Every non-200 answer is `{"error": "<code>", "detail": "<text>"}` (DS-017 §4.6, AS-05) via `_error()`:

| HTTP | `error` |
|---|---|
| 400 | `invalid_body`, `invalid_surface`, `invalid_page`, `invalid_limit`, `missing_context_item_id` |
| 401 | `unauthorized` |
| 503 | `surface_off`, `surface_internal`, `database_unavailable` |

The codes themselves are ours; the pack fixes the statuses and the body shape (AS-05: *"the error codes … are as written in the API contract"*, which names none).

### 11. Item adapter: done (question 4 answered 1 Oct 2026)

`Candidate.card(position)` (`reco/ranking/serving.py`, `_post_card`, `_product_card`):

| Card | `item_id` | `item_type` | `post_id` | `product_id` |
|---|---|---|---|---|
| Plain post (feed) | post id | `post` | post id | `null` |
| Post showing a product (feed) | post id | **`product`** | post id | the post's first product (`PostRecord.product_ids[0]`) |
| Product (product rail) | product id | `product` | `null` | product id |

This meets X-16 and F75: *"a post card showing a product keeps its post id as
item_id … every item also carries post_id and product_id as separate fields, so a
post id is never read as a product id."*

**Fix, 1 Oct 2026 (commit `6c3ef46`): `item_type` for a post card showing a
product is `product`.** DS-017 §3 leaves it *"as the app expects"*. The Capture
Register's F10 note (28 Sep) answers it: *"On platform feed lists, item_type
product with a post id is a post card showing a product: read post_id = item_id
(X-16)"*, and the real feed clicks on dev write it that way. So the card is
`item_type: "product"`, `item_id` = `post_id` = the post id, `product_id` = the
product. Question 4 is answered (`Tracing/REALIGNMENT_v1.3.md`, "Questions
(reviewed 1 Oct 2026)"); it was earlier returned as `post`. The final recheck
(§A) tells such a card apart from a product card by its `post_id`. Tested in
`test_a_feed_list_is_recorded_exactly_as_returned`.

### A. Extra: eligibility is ENG-08's rules E-01 to E-12, with the final recheck: done (since 1 Oct 2026, `11e515e`)

The interim filter `reco/eligibility/basic.py` (public, not hidden, not removed;
product active and in stock) was **deleted** when ENG-08 was built. Serving now
calls ENG-08 (`reco/eligibility/rules.py`, pure rules; `reco/eligibility/apply.py`,
applying them to real items):

| Step | Function | What it does |
|---|---|---|
| Viewer | `viewer_context(settings, user_id)` | own accounts, follows, blocks (either way), mutes and dismissals, date of birth; empty for a missing `user_id` |
| Filter | `eligible_posts` / `eligible_products` | E-01 to E-12 on each row read; each exclusion logged (`reco.eligibility`, `"excluded"`, with `request_id`, `item_id`, `item_type`, `rule`) |
| Final recheck | `page_after_recheck` → `recheck` | just before the list is returned, the page's items are re-read on the platform and re-checked; any that now fail are replaced by the next eligible items from the spare page (DS-017 §4.3: *"re-checks the returned items when it builds each list"*) |

The rules themselves, their sources and choices are ENG-08's to document. What
matters here: every exclusion now has a log line (no database pre-filter, §9),
and an item that changed between the read and the answer is not served.

**Real data, dev, 1 Oct 2026** (the demo rehearsal below): the feed returns
**3** posts; the other **5** posts are excluded by **E-05** (private authors the
test viewer does not follow). The product surface returns **0** items: each
request scans its cap of 1,000 products and excludes all of them, about 857 by
**E-08** (the seller is not active) and about 143 by **E-07** (not sellable). The
E-08 cause: the two import sellers (2,006 of 2,011 products) have no `status`,
and a missing status is read as not active (open question 17 in
`Tracing/REALIGNMENT_v1.3.md`, for Aravinth or the backend code).

### B. Extra: `scripts/try_recommendations.py`: done

Calls a running engine over HTTP 20 times (the first warms the connections and is
not timed), prints status, item count, `policy_id`, the first three items (last
6 characters and type), the p95 and median, then reads each of the 19 timed
requests' E1 and checks `served_items == items`. Exit 0 only if all match and p95
≤ 200 ms. On `product` with no id given, the newest eligible product is the
context. Prints ids only, never the token or a URI.

### C. Extra: checklist section 6 (`scripts/run_checklist.sh`): done

| Line | Check | Expects |
|---|---|---|
| 6.1 | contract tests (no database) | `14 passed` (**stale**: the file now has 17 such tests, so this line needs `17 passed`; see §6) |
| 6.2 | constructed-data tests | `2 passed` |
| 6.3 | feed over HTTP (port 8192, throwaway `reco_demo`, settings copy with both surfaces live) | `19 of 19` |
| 6.4 | product over HTTP | `19 of 19` (fails on dev since 1 Oct: 0 eligible products, p95 over 200 ms; question 17) |
| 6.5 | wrong token | `HTTP401` |
| 6.6 | feed set off by editing the copy and raising `config_version`, no restart | `HTTP503` |

---

## 3. Configuration reference

No new settings: all were added with ENG-02 from the Settings sheet. Used here (`[serving]` in `settings/engine.toml`):

| Setting | Value | Range | Use |
|---|---|---|---|
| `surface_mode_feed` | `off` | off, internal, live | 6 |
| `surface_mode_product` | `off` | off, internal, live | 6 |
| `exploration_percent` | 5 | fixed (since 1 Oct: the sheet's "Stays at 5% for Wave 1A") | 7 |
| `exploration_top_kept` | 3 | fixed | 7 |
| `sample_random_percent` | 10 | fixed (since 1 Oct; sheet range 1–100, fixed for Wave 1A) | 4 (`scored_not_served`) |
| `soco_be_timeout_ms` | 250 | 100–400 | 8: the request's time limit on test and production |
| `service_p95_target_ms` | 200 | fixed | the check; `try_recommendations.py` uses 200 directly |
| `page_dedup_hours` | 24 | fixed (since 1 Oct; sheet range 1–72) | not yet used (ENG-19) |
| `[lists] test_accounts` | `[]` | entries `{account_id, reason, expiry, changed_by}` | internal mode |
| `[slots.*]` | ENG-05 | | `policy_id`, slot records |

The "fixed" rows above were locked in `reco/config/tunables.py` on 1 Oct 2026
(audit, commit `2b585af`): the Settings sheet says a value changes only where its
*When it changes* column allows, and these rows say *Fixed for Wave 1A* even where
a range is given. A settings file with another value is rejected.

Environment: `INGEST_TOKEN` (the serving token; required, never in a file that is
shared), `MODEL_VERSION` (default `1.0.0`), **`REQUEST_BUDGET_MS`** (new, 1 Oct;
optional: overrides the per-request time limit, §2.8; unset = 2 s on dev, 250 ms
on test and production).

---

## 4. Tests

`tests/test_recommendations.py`, **19 tests** (16 before the 1 Oct audit fixes). The handler is called directly with a
constructed Starlette request; the checklist covers HTTP.

**Without a database (17):** candidates are made up and records kept in a list.

| Test | Covers |
|---|---|
| `test_a_missing_or_wrong_token_is_401` | 1, 10 |
| `test_bad_input_is_400` ×6 | `opportunity`, limit 0, limit 51, page 0, page `"1"`, product with no context; nothing recorded |
| `test_a_surface_that_is_off_returns_503` | 6; nothing recorded |
| `test_internal_serves_only_test_accounts` | 6: listed account 200, other 503, expired entry 503 |
| `test_the_response_shape` | 3: exact keys, `policy_id` form, page 2 holds items 6–10 at positions 1–5, `reason_code` null, no `candidate_ids` |
| `test_exploration_keeps_the_top_three_and_never_on_product` | 7: top 3 kept, rest shuffled; product never explores; `scored_not_served` holds every item on exploration |
| `test_the_record_holds_what_the_pack_lists` | 4: every field, `_id = request_id`, `served_items == items`, candidates through page 2, `slot_methods` one entry per slot with `{slot, method, fallback_step}` (F71), `scored_not_served` null when the draw misses |
| `test_scored_not_served_is_on_about_ten_percent_of_requests` | 4 (new, 1 Oct): F72 on ~10 % of 400 requests plus every exploration row; `returned` items = served items |
| `test_the_database_clients_never_retry` | 8 (new, 1 Oct): both clients have `retry_reads` and `retry_writes` false (SD-26) |
| `test_a_database_fault_is_503_at_once` | 8: one call, no retry |
| `test_no_record_no_list` | 4, 8 |
| `test_the_request_budget_is_soco_be_timeout_off_dev` | 8 (new, 1 Oct): 250 ms on test, 2 s on dev, `REQUEST_BUDGET_MS` wins |

**On constructed platform data (2, `-m mongo`):**

| Test | Covers |
|---|---|
| `test_a_feed_list_is_recorded_exactly_as_returned` | 9, A, 11: hidden, private and removed posts left out, an under-review post served (E-12); newest first; a post showing a product is `item_type: "product"` with `item_id` = `post_id` and its `product_id` (F10, X-16), and that product must be sellable (E-07); a plain post is `post`; one E1, matching; timed (< 1000 ms in the test: the 200 ms is measured on test) |
| `test_a_product_list_leaves_out_the_context_product` | 9, A, 11: out-of-stock, inactive, and no variant stock left (E-07) left out; the context product left out; `post_id` null; `policy_id` ends `.product_ranking-attribute_similarity` or `.product_ranking-bought_together` |

```bash
.venv/bin/python -m pytest -q tests/test_recommendations.py -m "not mongo"
TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q tests/test_recommendations.py -m mongo
```

(Since `d1e5427` each test run gets its own throwaway databases, `reco_test_<pid>`,
dropped at the end, unless `TEST_MONGO_DB` names one.)

**Result, 1 Oct 2026, after the audit fixes (`d1e5427`, `2b585af`, `964f4ec`):**

- `-m "not mongo"`: **17 passed**.
- `-m mongo` (Atlas build cluster, per-run database, dropped afterwards): **2 passed**; the timed feed request took 150 ms (laptop → Atlas, now with the full eligibility rules and the recheck).
- Full suite: **634 passed, 1 skipped**.

**Earlier result, 1 Oct 2026, before the audit fixes:**

- `-m "not mongo"`: **14 passed**.
- `-m mongo` (Atlas build cluster, `TEST_MONGO_DB=reco_test_eng06`, dropped afterwards): **2 passed**; the timed feed request took 57 ms.
- Whole unit suite (`-m "not mongo"`): **530 passed, 1 skipped**.

All three re-run after commit `ea88d1a` (method names in `policy_id`).

**Over HTTP, 1 Oct 2026** (laptop → Atlas; dev platform data: 8 posts, 2,011
products; settings copy with both surfaces live; throwaway engine database;
`scripts/try_recommendations.py`, 19 timed requests each):

| Run | Surface | Items | p95 | Median | Records matching |
|---|---|---|---|---|---|
| After `4db835f` | feed | 8 | 69 ms | 66 ms | 19 of 19 |
| After `4db835f` | product | 10 | 104 ms | 87 ms | 19 of 19 |
| After `ea88d1a` (demo rehearsal, port 8196, `reco_demo_eng06`, dropped afterwards) | feed | 8 | 69 ms | 62 ms | 19 of 19 |
| After `ea88d1a` (same) | product | 10 | 93 ms | 82 ms | 19 of 19 |
| **After the audit fixes, `964f4ec`** (demo rehearsal, port 8196, `reco_demo_eng06`, dropped afterwards; ENG-08's rules in force) | feed | **3** | 129 ms | 120 ms | 19 of 19 |
| **Same** | product | **0** | **354 ms (over 200)** | 334 ms | 19 of 19 |

**What changed in the last two rows (1 Oct 2026).** The feed now returns 3 posts:
E-05 excludes the other 5 (private authors the test viewer does not follow), each
with an `"excluded"` log line. The product surface returns no items: every one of
the 1,000 products scanned is excluded (about 857 by E-08, 143 by E-07; §A), so
each request reads the whole scan window and takes about 350 ms, and the script
exits 1 (`p95 … OVER 200 ms`). The cause is data, open question 17 (sellers with
no `status`); until it is answered checklist 6.4 fails on dev. On test and
production the 250 ms limit (§2.8) would turn such a request into a 503. Latency
grew from ~65 ms to ~125 ms on the feed because each list now also reads the
viewer's context, the authors and the final recheck. In this run the `policy_id`s
were `cfg3.…` (settings version 3 since ENG-29), and the feed was set `off` by
raising `config_version` to 4: reload logged within 30 s, then 503 `surface_off`,
while product stayed 200.

In the earlier rehearsal the `policy_id`s were `cfg2.interest-recency_decay.promoter_score-cohort_percentile`
(feed) and `cfg2.product_ranking-bought_together` (product), for the test user
`64f1c0ffee0000000000abcd`. `surface: "opportunity"` → 400
`invalid_surface`; wrong token → 401; feed set `off` by raising `config_version`
to 3 → reload logged within 30 s → 503 `surface_off`, while product stayed 200.

The 200 ms check is formally for the **test** server (*"A request returns within
200 ms on test"*); these laptop numbers include the link to Atlas. The whole
checklist script was not re-run for this note.

---

## 5. Runbook

**Turn a surface on or off (no restart).** In the settings file in force, set
`surface_mode_feed` / `surface_mode_product`, raise `config_version`, set
`changed_by`, save. Within 30 s the log shows `settings changed` with
`changed_keys: ["serving.surface_mode_feed"]`, and `ml_config_changes` records
it. A change without a new `config_version` is rejected and the old mode stays.

**Internal mode for production checks (SD-10).** Add the account to `[lists]`:

```toml
test_accounts = [
  { account_id = "<24-char id>", reason = "APP-21 checks", expiry = 2026-12-31, changed_by = "Allen" },
]
```

then set the surface to `internal` and raise `config_version`. Expired entries stop being served on the day after `expiry`.

**Try it against a running engine.**

```bash
INGEST_TOKEN=… ML_MONGO_DB=<engine db> .venv/bin/python scripts/try_recommendations.py http://127.0.0.1:8100 feed
INGEST_TOKEN=… ML_MONGO_DB=<engine db> .venv/bin/python scripts/try_recommendations.py http://127.0.0.1:8100 product [product id]
```

**Find the record for a list.** `ml_events` `{_id: "<request_id>", event_code: "E1"}`, or `read_served_list()`. The engine's own lists have `source: "engine"`; copies of platform lists (ENG-04) have `source: "recommendationrequests"`.

**Troubleshooting**

| Symptom | Cause | Fix |
|---|---|---|
| Every call 401, ERROR `INGEST_TOKEN is not set` | No token in the environment | Set `INGEST_TOKEN` and restart |
| 503 `surface_off` | The surface's mode is `off` (the default) | Expected in production until ENG-24; on dev/test set it live in a settings copy |
| 503 `surface_internal` | Mode `internal` and the user isn't a current test account | Add or extend the entry in `lists.test_accounts` |
| 503 `database_unavailable` | A database is unreachable, a read or the E1 write failed, or the request ran past its time limit (250 ms on test/production, 2 s on dev; §2.8) | Check `/health`; the `database unreadable` log line carries the `request_id` and the error (a timeout shows as `NetworkTimeout`/`ExecutionTimeout`) |
| Feed returns fewer than `limit` items | Fewer eligible posts exist (dev, 1 Oct: 3 of 8; E-05 excludes 5) | Expected: *"exactly limit items unless fewer eligible items exist"*. The `"excluded"` lines on `reco.eligibility` (same `request_id`) name the rule for each item left out |
| Product returns 0 items and takes ~350 ms on dev | Every product is excluded (E-08: sellers with no `status`), so the whole 1,000-row scan is read | Open question 17; nothing to fix in the engine until it is answered |

---

## 6. Open

| Open item | Waits on |
|---|---|
| Eligibility from `ml_item_state` instead of direct platform reads | ENG-27 (ENG-08 reads the platform until then) |
| Products on dev: every seller lacks `status`, so E-08 excludes every product; checklist 6.4 fails on dev | Open question 17 (Aravinth or the backend code: does a missing status mean active?) |
| `fallback_step` and each slot's fallback step from the ladder | ENG-09 |
| A model `score` in `scored_not_served` (null today) | ENG-17, ENG-19 |
| Feed ranking, variety, and the exploration shuffle's author re-check | ENG-19 |
| Product ranking (M5), cart surface context | ENG-17 |
| Leave out items served to the user in the last 24 hours on later pages | ENG-19 (`page_dedup_hours`) |
| The check on the **test** server (200 ms there, with the 250 ms limit; record matching) | The test server and its constructed data (ENG-01, ENG-29 item 8) |
| Surfaces live in production | ENG-24 go-live rule (ENG-11, ENG-22, ENG-23, APP-21, ENG-20) |
| Hand the serving token to Aravinth privately (DS-017 §9 step 1) | The servers |

Closed on 1 Oct 2026: the full eligibility rules with the exclusion log and the
final recheck (ENG-08, `11e515e`); `item_type` for a post card showing a product
(question 4, `6c3ef46`); `visibility` matched exactly at the database (the
database pre-filter was removed, `d1e5427`).

---

## 7. Files changed (commits `4db835f` and `ea88d1a`, 1 Oct 2026)

| File | Change |
|---|---|
| `reco/api/recommendations.py` | New: the endpoint, request checks, modes, E1 record, error bodies |
| `reco/ranking/serving.py` | New: `Candidate`, `interim_candidates`, `decide_exploration`, `explore`, `scored_sample` |
| `reco/eligibility/basic.py` | New: interim `post_is_eligible`, `product_is_eligible` |
| `reco/platform/fetch.py` | `read_newest` (serving reads, newest first, narrowed at the database) |
| `reco/store/writers.py` | `record_served_list`, `read_served_list` |
| `reco/slots/assignment.py` | `method_number`; `policy_id` takes several slots (`4db835f`) and names each method (`ea88d1a`: Build List ENG-05/ENG-26, SD-15); default method for a missing `user_id` (DS-017 §4.1) |
| `reco/main.py` | Mounts the router |
| `scripts/try_recommendations.py` | New (§2 B) |
| `scripts/show_served_list.py` | New: reads one served-list record back and compares it with a saved response (demo step 4) |
| `scripts/run_checklist.sh` | Section 6 (§2 C) |
| `scripts/setup_engine_db.py` | Docstring: "sixteen" collections |
| `tests/test_recommendations.py` | New, 16 tests; product `policy_id` assertion on method names (`ea88d1a`) |
| `tests/test_assignment.py` | `policy_id` form, missing `user_id` |

Since then, on 1 Oct 2026:

| Commit | File | Change |
|---|---|---|
| `11e515e` | `reco/eligibility/basic.py` | **Deleted**: replaced by ENG-08 |
| `11e515e` | `reco/eligibility/rules.py`, `reco/eligibility/apply.py` | New (ENG-08): E-01 to E-12, viewer context, exclusion log, recheck |
| `11e515e` | `reco/ranking/serving.py` | `interim_candidates` uses ENG-08 and reads the viewer at the same time; one spare page; `MAX_SCAN_ROWS`; `page_after_recheck` |
| `11e515e` | `reco/platform/connection.py`, `reco/store/connection.py`, `requirements.txt` | `minPoolSize` 10; PyMongo 4.10.1 → 4.18.2 |
| `6c3ef46` | `reco/ranking/serving.py` | `_post_card`: `item_type` `product` for a post card showing a product (F10, X-16) |
| `d1e5427` | `reco/api/recommendations.py` | `slot_methods` (F71), `scored_not_served` (F72), `request_budget_seconds` and `pymongo.timeout` around the reads and the write |
| `d1e5427` | `reco/config/__init__.py` | `request_budget_ms` (`REQUEST_BUDGET_MS`) |
| `d1e5427` | `reco/platform/connection.py`, `reco/store/connection.py`, `reco/main.py` | `retryReads=False`, `retryWrites=False`; `warm()` at startup |
| `d1e5427` | `reco/platform/fetch.py` | `_servable` removed: no filter at the database |
| `d1e5427` | `tests/test_recommendations.py`, `tests/conftest.py` | 3 new tests; per-run test databases |
| `2b585af` | `reco/config/tunables.py` | `exploration_percent`, `sample_random_percent`, `page_dedup_hours` fixed for Wave 1A |

## 8. Demo

The live demo script, in plain language, is the Obsidian note
`obsidian/Demos/Demo - ENG-06.md`.
