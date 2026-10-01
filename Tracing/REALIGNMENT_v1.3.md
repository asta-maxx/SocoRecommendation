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

## Questions for Kala (in writing, quoting the item)

1. **DB-02:** its row is missing from the v1.3 Build List sheet (68 rows; the Home sheet says 69). It's still referenced by ENG-01, ENG-04, DB-12 and the Waits sheet, and the old check ("old login no longer connects; cannot write") has no home.
2. **ENG-21 / DB-02:** fraud rule R12 reads `user_sessions` (device, IP), but `user_sessions` isn't on DB-02's read-only list.
3. **ENG-04 / ENG-29:** `rec_serve_log` (F80) has no `updated_at`, yet ENG-29 says it's synced "the same way as recommendationrequests".
4. **ENG-29 / X-16 / F10:** what exact `item_type` is returned for a post card that shows a product ("as the app expects")?
5. **ENG-21 / X-21 vs Fraud §11:** are test accounts left out of fraud entirely (X-21, ENG-29), or flagged but not actioned (Fraud §11)?
6. **ENG-10 / sheet 4:** are follows counted from `follows` or from `postevents` follow rows? Both are named.
7. **ENG-08 ↔ ENG-27:** ENG-08 (Step 2) applies filters on ENG-27's state, while ENG-27 (Step 3) waits on ENG-08.
8. **Version references:** several places cite "API contract v2.4"; the pack is v2.5.
9. **ENG-23:** "Run each query on the test environment", while the Definitions say there is no platform test environment.
10. **DB-16:** do migrated `postevents` rows keep their `_id` and get an `updated_at`? The sync keys on both.
11. **X-05 vs ENG-03:** seen items come from `seen_ids` (X-05), or from the engine's own copy of impressions (ENG-03)?
12. **ENG-29 #1:** where are the "older seller categories" stored? Only `categories` is readable.
13. **ENG-05 / DS-017 4.2:** DS-017's example `cfg3.interest-2.promoter-1` numbers the methods and shortens the slot name, while Build List ENG-05/ENG-26 ("policy_id records method names, so history stays readable across the swap") and SD-15 name them. We follow the Build List: `cfg2.interest-recency_decay.promoter_score-shrinkage`. Please correct the DS-017 example.
14. **ENG-06:** it waits on ENG-09 and ENG-29, which aren't built. We built it to its own interim clause ("on test, return eligible posts newest first"; both surfaces off in production). For the product surface the clause is silent: we return eligible products newest first, without the context product. Is that the intended interim?
15. **ENG-06 exploration:** "shuffle positions 4 onward among eligible items". We shuffle within the page, so page 2 never repeats page 1. Or should items be drawn from beyond the page?

## Built after the realignment (1 Oct)

| Item | State | Commit |
|---|---|---|
| ENG-04 | Rebuilt as the engine sync; real backfill into dev `SoCo` (postevents 146, orders 8, recommendationrequests 12) | 6c4299c |
| ENG-05 | Built: SHA-256 buckets, policy_id per DS-017 4.2 | 4ec8f30, 4db835f |
| ENG-06 | In progress: endpoint, E1 record, modes, exploration, sample, errors; interim newest-first lists until ENG-08/09/17/19/29 | 4db835f |
| ENG-07 | Built: batches marked current only when complete, ml_job_runs, 2 AM IST scheduler; M1 runs as batches | 008390a |

> The dev engine copy stays current only while `python -m reco.jobs sync_loop` runs (on the laptop for now; on the servers once ENG-01's remainder is done).
