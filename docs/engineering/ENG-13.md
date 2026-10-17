# ENG-13: Retrieval method one, quotas

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 3 (within 17 working days) |
| **Waits on** | ENG-12 (Built), ENG-08 (Passed) |
| **Needed by** | ENG-15 (merge), ENG-22 (checks 2 to 4) |
| **Status** | **Built** (16 Oct 2026, dev). Its check is code and tests, so it becomes Passed when the checklist runs on the test server |
| **Spec** | Build List v1.4 ENG-13; Settings sheet "M2 retrieval" (pool size 300, 100–2,000; source shares 40/30/20/10, fixed); ENG-30 point 3 and Settings "Repost chain limit" (10, fixed); ENG-08 (E-01 to E-12) |

## 1. What the item requires

> Build a pool of 300 candidates: 40% from interest categories; 30% from follows; 20% from trending; 10% from recent platform-wide popular posts. Interleave the sources round-robin in those proportions. If a source runs short, its share passes to the next source in that order. Remove duplicates. A repost counts as its original. Apply the filters (ENG-08) before and after. Every candidate keeps its source tag.

*How to check it is done:* "The pool size is 300 or fewer, quotas are within 1 item, and there are no duplicates."

## 2. What was built

### The pool: `reco/ranking/quotas.py`

- `quotas(size, shares)`: size × share by largest remainder, summing to the size exactly (120, 90, 60, 30 for 300). Shares from `retrieval.source_shares`, size from `retrieval.pool_size`.
- `interleave(lists, size, shares)` (no database): smooth weighted round-robin. The next place goes to the source furthest behind its quota (`(taken + 0.5) / quota` lowest; ties in source order). The first ten places run interest, follows, trending, interest, follows, popular, interest, trending, follows, interest, and **every prefix keeps the proportions within 1** (ENG-15 cuts by this order). Each source keeps its own order (ENG-12's).
- **Short source:** its unused places pass to the next source in the order interest → follows → trending → popular that still has items. After popular it **wraps to interest** (the pack names no source after popular; decided 16 Oct 2026, sent to Kala/Nisha as Q7). The interleave then runs again. Places freed in a later pass (a source losing a shared post to another) go to the first source with items left, so the pool always takes every unique eligible item up to 300. The reported `quotas` are the places after passing; a source with nothing left has its quota set to what it filled.
- **Duplicates:** judged by `SourceItem.key`, the original's id for a repost. The first source to reach an item keeps it; the others skip it and take their next, so a duplicate never costs a source a place. `pool.duplicates` counts the skips.
- **Reposts:** a repost in the pool is replaced by its original (`item_id` = the original), keeping the repost's source tag and score; `pool.reposts_merged` maps original → repost. (ENG-22 check 4: "Reposts are merged into their original.")
- `build_pool(settings, sources, viewer, request_id)`: one platform read of every offered post and every original, then ENG-08's `eligible_posts` once.
  - **Filters before:** each source's own items (reposts as themselves) must pass, so the quotas are worked out on eligible items.
  - **Filters after:** the pool, with reposts replaced by their originals, must pass. An original that fails (it can be older than 30 days, hidden, or by a blocked author) is taken out with every item that leads to it, and the pool is built again without it, so it stays full.
  - A post the platform no longer has is excluded and logged with rule `missing`. Every other exclusion is logged by ENG-08 with its rule.
  - One log line per request: pool size, taken and quotas per source, duplicates, reposts merged, excluded before and after.
- `pool_for_user(settings, user_id, profile, viewer, request_id)`: the wiring. The top-5 categories come from the `Profile` of the user's assigned interest method or its fallback rung (`get_profile`); follows from ENG-08's `viewer_context`. Returns ENG-12's `SourceResult` (its `similar` list goes to ENG-15) and the `Pool`.

### Reposts led to their original (ENG-30 point 3, built here because ENG-13 needs it)

- `reco/platform/records.PostRecord.repost_of`: `repostDetails.originalPostId` (read in `fetch._FIELDS["post"]`).
- `reco/platform/reposts.py`: `original_of(post_id, known, max_steps)` walks the chain to the first post with `isRepost` false. No original when: `isRepost` true without a link (`missing_link`), the link names a post that is not there (`missing_post`), a loop (`loop`), more than `commerce.repost_chain_max_steps` (10) steps (`too_long`). `resolve_originals(settings, posts)` reads missing parents **one level at a time** (at most 10 reads however many posts), logs each break as a warning with `post_id` and `reason`, and returns the originals, a count by outcome, and the posts read.
- The post index (ENG-12) stores `original_id` on every row: the post itself, the original for a repost, or None when the chain breaks. **Decided 16 Oct 2026:** a repost with a broken chain is offered as itself (the pack's "credits nobody" is about M8's sales); a repost of a seed post is not indexed; a recent repost brings its original in even when the original is older than 30 days (the repost is what made it recent).
- New setting `commerce.repost_chain_max_steps` (10, fixed for Wave 1A; the sheet's range 5–50).

## 3. Configuration

`retrieval.pool_size` (300; 100–2,000), `retrieval.source_shares` (0.4/0.3/0.2/0.1, fixed), `commerce.repost_chain_max_steps` (10, new), and ENG-12's and ENG-08's settings.

## 4. Tests

`tests/test_quotas.py`, 24 tests:

- quotas 120/90/60/30 and exact sums; shares and pool size from the settings;
- a full pool is 300 in the proportions, each item tagged with its own source; every prefix within 1; each source in its own order;
- a short source passes to the next; the share moves on again when the next is short too; popular wraps to interest; everyone short gives a smaller pool; no sources give an empty pool; overlapping short sources still use every unique post (regression found by the database test);
- duplicates removed and never cost a place; a repost counts as its original and is replaced by it with the tag kept;
- filters before (a source short after the filter passes its share on); filters after (a hidden original brought by a repost is removed and the pool rebuilt); a post gone from the platform excluded and logged;
- chains: to the original; missing link, missing post, loop; the 10-step limit; one read per level, breaks logged; the parser reads `repostDetails.originalPostId`;
- MongoDB: index → sources → pool for a real viewer: ≤ 300, quotas within 1, no duplicates, a blocked author filtered before, a hidden original filtered after.

`tests/test_sources.py` MongoDB test: a recent repost of a 40-day-old post is indexed with `original_id` = the old post.

Results, 16 Oct 2026: 24 passed (23 unit, 1 MongoDB); `test_sources` 10 passed; unit suite 679 passed, 1 skipped.

## 5. Runbook

```bash
python -m pytest -q tests/test_quotas.py
python -m reco.jobs post_index      # the index now carries original_id
```

## 6. Open

| What | Waits on |
|---|---|
| The check on the test server (checklist 13.x) | The test server |
| Serving: ENG-15 merges the pool with the similar list (built 16 Oct); ENG-19 ranks | ENG-19 |
| Filters read the platform for every offered post (up to ~1,200) per request; ENG-27 moves them onto `ml_item_state` | ENG-27 |

## 7. Files changed

| File | Change |
|---|---|
| `reco/ranking/quotas.py` | New: quotas, interleave, filters before and after, wiring |
| `reco/platform/reposts.py` | New: the repost chain (ENG-30 point 3) |
| `reco/platform/records.py`, `reco/platform/fetch.py` | `PostRecord.repost_of` from `repostDetails.originalPostId` |
| `reco/config/tunables.py` | `commerce.repost_chain_max_steps` (10) |
| `reco/ranking/post_index.py`, `reco/store/item_state.py` | `original_id` on each index row |
| `reco/ranking/sources.py` | `SourceItem.original_id` and `.key` |
| `tests/test_quotas.py` | New |
| `tests/test_sources.py` | A repost in the database test |
| `scripts/run_checklist.sh` | Section 13 |

## Update, 17 Oct 2026

Nisha confirmed Q7 (16 Oct): popular's unused share passes round to interest, then follows, then trending, subject to available posts and the filters. Built that way on 16 Oct; no change.
