# ENG-12: Candidate sources

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 3 (within 17 working days) |
| **Waits on** | ENG-03, ENG-10 (both Passed) |
| **Needed by** | ENG-13 (quotas), ENG-15 (merge), ENG-19 (ranking) |
| **Status** | **Built** (16 Oct 2026, dev). Becomes Passed when its check runs on test load (the test server) |
| **Spec** | Build List v1.4 ENG-12; Settings sheet "M2 retrieval" (time limit 20 ms per source, 10–40; post age 30 days, fixed; pool 300); SDA v1.7 (stage limits: retrieval 80 ms; a source over its limit is dropped and logged; SD-17: a request never calculates); Kala's answer of 16 Oct (Q4) |

## 1. What the item requires

> Four sources, run in parallel. Each returns item_id, item_type, source and source_score, and has a time limit: 1. Posts in the user's top-5 interest categories (from the interest method assigned to the user, or the fallback rung): 20 ms. 2. Posts by accounts the user follows: 20 ms. 3. Trending in the user's categories, by qualified views over the last 7 days: 20 ms. 4. Platform-wide popular posts, by qualified views over the last 7 days: 20 ms. The user's stored method-two list (ENG-14) is read in parallel, also within 20 ms, and merged in ENG-15. A source that runs over its limit is dropped for that request and logged. Only posts from the last 30 days are used.

*How to check it is done:* "On test load, each source returns within its limit, and drops are logged."

Kala, 16 Oct (Q4): trending is a plain count of qualified views over the last 7 days, not growth; source 3 = source 4 limited to the user's top-5 interest categories (the same as source 1); ties newest first.

## 2. What was built

### A. The post index (prerequisite) — done

The sources must answer in 20 ms and never calculate (SD-17), but trending and popular need each post's 7-day qualified views, and source 1 needs each post's categories matched to the 23. So a job works them out ahead:

- `reco/ranking/post_index.py`: `build_post_index` / `refresh`. One row per post created in the last `retrieval.post_age_days` (30): `post_id, author_id, categories` (one of the 23, via the category map), `created_at, is_repost, original_id` (ENG-30 point 3, added 16 Oct with ENG-13: the post itself, the original for a repost, None for a broken chain), `qualified_views_7d` (people with a qualified view, `dwell_ms ≥ events.qualified_view_seconds × 1000`, in the last 7 days, from `ml_events`, **test accounts' views left out**, ENG-29 item 3). **Seed posts are not indexed** (ENG-30 point 9: test data), so no source offers one.
- Written whole as an ENG-07 batch into **`ml_item_state`** (job `post_index`, method `post_index`); a request reads only the current batch. `ml_item_state` is the engine's "current state of posts, accounts and products" collection (ENG-01, ENG-27); ENG-27 later adds accounts, products and the eligibility fields there.
- Refreshed every `filters.eligibility_refresh_minutes` (15) by the sync loop (`reco/sync/run.sync_forever`), and on demand: `python -m reco.jobs post_index`.
- Platform read: `reco/platform/recent.read_recent_posts` (posts by `timestamp`, else the `_id` time; only the parser's fields).
- Indexes on `ml_item_state` (`reco/store/item_state.ensure_post_index_indexes`): (job_run_id, categories, created_at), (job_run_id, author_id, created_at), (job_run_id, qualified_views_7d, created_at).

### 1–4 and the method-two read — done

`reco/ranking/sources.run_sources(settings, user_id, top_categories, follows, request_id)` runs five reads in parallel, each under `asyncio.wait_for` with `retrieval.source_time_limit_ms` (20). Each returns `SourceItem(item_id, item_type "post", source, source_score)`, at most `retrieval.pool_size` (300).

| Source | Reads | source_score |
|---|---|---|
| `interest` | posts in the user's top-5 categories | the user's share of the post's best category (highest share where a post has several) |
| `follows` | posts by accounts the user follows | how new the post is (its time, as a number) |
| `trending` | posts with qualified views in 7 days, in the top-5 categories | qualified views in 7 days |
| `popular` | posts with qualified views in 7 days, everywhere | qualified views in 7 days |
| `similar` | the user's stored method-two list (ENG-14), current batch | the stored cosine |

Ordering within a source: best score first, ties newer first, then post id. `top_categories(shares)` gives the top 5 by share (the caller takes the shares from the interest profile of the user's assigned method, or the ladder's rung: ENG-13 wires this). Over the limit: the source returns nothing for that request, is listed in `result.dropped`, and a warning is logged with `request_id`, `source` and `limit_ms`. Every run logs each source's size and milliseconds.

**Where the pack is silent (decided 16 Oct 2026):** source_score for interest (the best category share) and follows (newness); trending and popular count people, not view rows (one qualified view per person per post, as ENG-10); posts with no views are not offered by trending or popular; seed posts are never indexed; database errors are not "over the limit": they raise (SD-26, the request answers 503).

## 3. Configuration

No new settings: `retrieval.source_time_limit_ms` (20; 10–40), `retrieval.post_age_days` (30), `retrieval.pool_size` (300), `filters.eligibility_refresh_minutes` (15), `events.qualified_view_seconds` (3), `lists.test_accounts`.

## 4. Tests

`tests/test_sources.py`: top-5 by share; interest by the best share, ties newer first; follows newest first, none without follows; trending = popular limited to the top categories, ties newest first; 30 days only; a source over its limit is dropped and logged with the request id while the others answer; the limit is the setting; the similar list read in parallel; no index yet means empty sources. MongoDB: the post index (recent only, seed left out, a test account's view left out) and every source reading it.

Results, 16 Oct 2026: **10 passed** (9 unit, 1 MongoDB).

**Dev, 16 Oct:** `python -m reco.jobs post_index` succeeded with 0 posts: dev has no post from the last 30 days (its 8 posts are older). Sources timed from the laptop to Atlas: 23–30 ms each, so with the 20 ms limit three were dropped and logged, as the rule says. The check is "on test load", on the test server next to the database.

## 5. Runbook

```bash
python -m reco.jobs post_index        # refresh the index now (the sync loop does it every 15 min)
python -m pytest -q tests/test_sources.py
```

## 6. Open

| What | Waits on |
|---|---|
| The check on test load (each source within 20 ms) | The test server |
| The sources feed ENG-13's pool and ENG-15's shortlist (both built 16 Oct); serving them waits on ranking | ENG-19 |
| Posts in the last 30 days on dev, and views with dwell_ms | Platform data (APP-02 backfill) |

## 7. Files changed

| File | Change |
|---|---|
| `reco/platform/recent.py` | New: recent posts |
| `reco/store/item_state.py` | New: the post index (write, reads, indexes) |
| `reco/ranking/post_index.py` | New: the index job |
| `reco/ranking/sources.py` | New: the five sources; `similar` reads `reco.store.candidates.read_user_candidates` (ENG-14, merged 16 Oct) |
| `reco/jobs/__main__.py`, `reco/sync/run.py` | The `post_index` job; refreshed every 15 min by the sync loop |
| `tests/test_sources.py` | New |
| `scripts/run_checklist.sh` | Section 12 |
