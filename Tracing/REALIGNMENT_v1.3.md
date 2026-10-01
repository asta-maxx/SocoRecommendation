# Realignment to pack v1.3 (received 1 Oct 2026)

ENG-01 to ENG-04 were built (24–29 Sep) to the **22 September** pack. On 28 Sep
(v1.2) and 29 Sep (v1.3), Kala reissued every document:

- Build List **v1.3**
- API Contract (DS-017) **v2.5**
- Service Design Agreement **v1.6**
- Fraud Policy **v1.3**
- Capture Register **29 Sep**

v1.3's Home sheet says *"ENG-01 to ENG-04 are built and unchanged; the
adaptations that touch them are in ENG-29"*. That refers to the **v1.2 text** of
those items. The repo held the 22 Sep version, so ENG-01 to ENG-04 are realigned
here to the v1.3 rows.

## What changed, in one paragraph

**The engine no longer receives events.**
- `POST /v1/events` is retired (DS-017 §7; X-02).
- Instead, the **engine sync** (new ENG-04) copies `postevents`, `orders` and `recommendationrequests` from the platform database with the read-only login.
- It does a **backfill**, then reads every 5 min by `updated_at`, with a checkpoint and a 2-min overlap.
- It **upserts** copies keyed on the platform `_id` into `ml_events` and `ml_orders`, and keeps them ≥365 days under the engine's own expiry.
- It **alerts** when more than 15 min behind, and **reconciles** ids and field values daily.

**There is no event source switch** (ENG-03): the platform migrates its older
collections into `postevents` (DB-16).

**Incognito is purchase privacy only.** Everything is recorded, and incognito
orders count for the buyer (X-09).

**Many platform items are now "Not needed".** The engine adapts instead (ENG-29):
- a category map to the 23;
- status and return maps;
- exemption and test-account lists in its own settings;
- blocks read from `followers`;
- order history from `tracking_info`;
- an item adapter (`post_id`, `product_id` on every served item);
- `rec_serve_log`.

**New items:** ENG-27 (full re-read for eligibility), ENG-28 (confirmed account
deletion), ENG-29 (the adapters).

## Impact on the built items

| Item | v1.3 asks | Action |
|---|---|---|
| ENG-01 | 16 collections (adds `ml_orders`, `ml_sync_state`, `ml_item_state`, `ml_deletions`); copies ≥365 days under the engine's own expiry (SD-29) | Add the four; retention as a TTL on the original event time |
| ENG-02 | Module `events` → `sync`; no event endpoint; settings file = the v1.3 Settings sheet (engine sync, eligibility refresh, category map, status maps, exemptions, test accounts, off/internal/live) | Rename; remove `/v1/events`; update tunables and `settings/engine.toml` |
| ENG-03 | No source switch; polymorphic actors (`user_model`/`userModel`); `updated_at`, `variant_id`, `checkout_id`, `dwell_ms`, `compliance.status`, `categoryPathIds`; served-item identity; undo fields kept; post-page impressions are page visits; check adds a businessRegister actor, a product post on a feed list, and an order with history and a return request | Remove the switch and legacy readers; extend the records; new tests |
| ENG-04 | The engine sync (9 points) | Replace the endpoint with the sync, tested on constructed data |

## Platform data seen on 1 Oct (dev platform, read-only)

| Needed | Present |
|---|---|
| `postevents.updated_at` (the sync key) | **0 / 146** |
| `postevents` dwell_ms, undone_at, is_self, user_model, surface, position, event_id | 96 / 146 |
| `orders.updated_at` | 3 / 8 |
| `orders.tracking_info` | 8 / 8 |
| `recommendationrequests.updated_at` | 0 / 12 |
| `rec_serve_log` | missing |
| `followers` (blocks) | empty |
| `products.categoryPathIds` | 0 / 2,011 |

The sync's **backfill** works on today's data. The incremental read needs
`updated_at` (APP-12, "reported built"), which isn't in this database yet.

**Urgent:** DB-01 keeps the platform's 90-day expiry. The backfill must copy
events before their oldest rows reach 90 days.

## Questions (reviewed 1 Oct 2026)

Every question was checked against `docs/updated` (Build List v1.3 first, then
DS-017 v2.5, SDA v1.6, Fraud Policy v1.3, Capture Register 29 Sep) and against
SOCO's own data. Fifteen are answered; two are open.

### Still open (only these need asking)

| # | Question | Who can answer | Until then |
|---|---|---|---|
| 16 | **Blocks in `followers` (ENG-08 E-01, X-19):** which fields hold the blocker, the blocked account and the status? Can either side be a `businessregisters` id? The collection is empty on dev and has only the `_id` index. | Aravinth, or the backend code (the block endpoint / followers model) | The engine assumes `{userId: blocker, followerId: blocked, status: "blocked"}` |
| 17 | **Missing `status` (ENG-08 E-08):** the two import sellers (2,006 of 2,011 products), 2 users and 4 businesses have no `status`. Does a missing status mean active? | Aravinth, or the backend code (account model defaults) | Treated as not active, so no product on dev can be served |

### Answered

| # | Question | Answer | From |
|---|---|---|---|
| 1 | DB-02 row missing from the Build List | Its content is on the "Waits on the other team" sheet (the read list); the login exists and works | Build List, Waits sheet |
| 2 | `user_sessions` for fraud R12 | The current read-only login reads it (7 rows: `deviceId`, `ipAddress`, `userId`); keep it on the final login | Dev database |
| 3 | `rec_serve_log` has no `updated_at` | It is written once per list request (DS-017 4.3), so it needs none: the sync reads new rows by `_id` (done) | DS-017 4.3, ENG-29 item 7 |
| 4 | `item_type` for a post card showing a product | `product`, with the post id as `item_id` and `post_id`, and the product as `product_id` (done in ENG-06) | Capture Register F10, X-16; real feed clicks on dev |
| 5 | Test accounts and fraud | Left out of fraud entirely; exemptions are flagged, never actioned | Build List ENG-29 item 3, X-21 (Build List outranks the Fraud Policy) |
| 6 | Follows: `follows` or postevents follow rows | Business follows come from `follows` (followingReference businessRegister) | Build List ENG-10 |
| 7 | ENG-08 ↔ ENG-27 circle | ENG-08 reads the platform directly until ENG-27's state exists; no block | Build List ENG-08, ENG-27 |
| 8 | "API contract v2.4" references | The pack's own documents are v2.5; nothing to do | — |
| 9 | ENG-23 "on the test environment" | The engine's test environment with constructed data (`soco_engine_test`, done) | Build List ENG-29 item 8 |
| 10 | Migrated postevents `_id` / `updated_at` | Not needed: the backfill runs after the migration (DB-16 step 4) and keys on `_id`; it doesn't need `updated_at` | Build List DB-16, ENG-04 |
| 11 | Seen items: `seen_ids` or impressions | Paging leaves out items *served* in the last 24 hours, from the engine's records; `seen_ids` is for measurement | Build List ENG-19, X-05 |
| 12 | Where "older seller categories" live | `businessregisters.category` (free text) and the category tree; the daily check covers both | ENG-29 item 1; dev database |
| 13 | policy_id names vs numbers | Method names | Build List ENG-05, ENG-26, SD-15 (outrank DS-017's example) |
| 14 | ENG-06 interim on product | Eligible products newest first, until ENG-17; a choice within ENG-06's interim clause | Build List ENG-06 |
| 15 | Exploration shuffle | Within the page, so paging stays stable; ENG-19 re-checks the author rule after shuffling | DS-017 4.3, Build List ENG-19 |

## Built after the realignment (1 Oct)

| Item | State | Commit |
|---|---|---|
| ENG-04 | Rebuilt as the engine sync; real backfill into dev `SoCo` (postevents 146, orders 8, recommendationrequests 12) | 6c4299c |
| ENG-05 | Built: SHA-256 buckets, policy_id per DS-017 4.2 | 4ec8f30, 4db835f |
| ENG-06 | In progress: endpoint, E1 record, modes, exploration, sample, errors; interim newest-first lists until ENG-08/09/17/19/29 | 4db835f |
| ENG-07 | Built: batches marked current only when complete, ml_job_runs, 2 AM IST scheduler; M1 runs as batches | 008390a |
| ENG-29 | Built on dev: tracking stages, status spellings, account lists, daily category check, rec_serve_log in the sync, constructed test data (`soco_engine_test`) | f7c82f3 |

> The dev engine copy stays current only while `python -m reco.jobs sync_loop` runs (on the laptop for now; on the servers once ENG-01's remainder is done).

