# ENG-19: Launch ranking layer for the feed

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 4 (within 22 working days) |
| **Waits on** | ENG-15 (Built), ENG-16 (Built), ENG-10 (Passed) |
| **Needed by** | ENG-23 (final acceptance queries) |
| **Status** | **Built** (17 Oct 2026, dev). Becomes Passed when its check runs on the test server |
| **Spec** | Build List v1.4 ENG-19; Settings "Ranking" (weights 0.35/0.15/0.20/0.20/0.10, freshness half-life 3 days, variety, engagement shrinkage 50 views) and "Serving" (page de-duplication 24 hours, exploration 5% top 3 kept, ranking stage 80 ms); Kala's answer of 16 Oct (Q8: an author with no promoter score) |

## 1. What the item requires

The row in full is in `Tracing/pack_text/` (ENG-19): score each shortlisted post on five components (interest match, retrieval percentile, author promoter score, freshness, engagement quality), commission never a term; ties newer then post id; variety while filling the page (2 in a row per author, 3 per author per page, ceil(0.4 × limit) per category, never below 2), relaxed in order category → per-author → consecutive, logged; then exploration (ENG-06) and the filters (ENG-08); after the shuffle re-check the consecutive rule; paging: page 1 the top, later pages leave out what was served in the last 24 hours; the product surface uses the M5 list with the same paging rule.

*How to check it is done:* "On test data, the order follows the formula, variety rules hold, and changing a product's commission changes nothing."

## 2. What was built: `reco/ranking/feed.py`

- **`score_posts`** (pure): for each shortlisted post, `interest` = the viewer's M1 share for the post's best category (from the profile of the viewer's assigned interest method or its fallback rung); `retrieval` = the post's ENG-15 percentile as a percentile within the shortlist; `promoter` = the author's M8 score from the current batch of the viewer's assigned promoter method; `freshness` = 0.5 ^ (age days / 3); `engagement_quality` = (engagements + 50 × shortlist average rate) / (qualified views + 50), as a percentile within the shortlist. Score = Σ `ranking.weights` × part. Ties: newer, then post id.
- **Author with no score (Kala Q8)** (`promoter_part`): their own score; else the average of the medians of the post's categories; else the platform median; else 0.5. The medians are written by the M8 job with each batch (`reco.store.promoter.write_medians`, `ml_measurements` measure `promoter_medians`, one document per method, valid only for the current batch).
- **`fill_page`** (pure): each place to the best-ranked post that keeps the rules in force; if the page cannot be filled, relax `category_cap`, then `per_author_cap`, then `consecutive_author`, and log which (`variety relaxed to fill the page`). The rest follow in rank order as spares for the ENG-08 recheck.
- **`keep_consecutive_rule`**: after the exploration shuffle, a third post in a row by one author is swapped with the nearest later post by another author.
- **`feed_candidates`**: viewer context → `merge.shortlist_for_user` (ENG-12 to ENG-15) → one platform read of the shortlisted posts (author, categories, time, card) → the index rows (views, engagements) → the authors' scores and the medians → score → leave out what was served (page 2+) → fill the page → `Built(page_start=0)`. Logs `feed ranked` with shortlist size, scored, topped up, left out as served, relaxed rules, and promoter sources.
- **Engagement in the post index (ENG-12)**: `qualified_views` (people with a qualified view over the index's 30 days) and `engagements` (likes, saves, shares, comments, not undone), both without the author's own actions, test accounts or business actors (`reco/ranking/post_index.py`; `item_state.read_posts_by_ids`).
- **Paging, both surfaces**: `writers.read_served_item_ids(user, surface, since)` reads the user's E1 records of the last `serving.page_dedup_hours` (24); the feed leaves them out before filling the page; the product surface's M5 list goes through `serving.leave_out_served`. `Built.page_start = 0` tells `page_after_recheck` the list is already paged. Positions start at 1 in each response.
- **Request path** (`reco/api/recommendations.py`): the feed reads the interest profile first, then calls `feed_candidates` with the viewer's promoter method; after exploration, `keep_consecutive_rule`. The E1 records `ordering: eng19_feed_ranking` and the ranking detail; `scored_not_served` now carries each item's ENG-19 score.

**Commission never enters:** nothing in `reco/ranking/feed.py` reads commission (`score_posts` has no such input); the MongoDB test changes a product's `commissionconfigs` row and gets the same order.

**Where the pack is silent (decided 17 Oct 2026):**
- A post's category for the category cap is the one its interest match used (the viewer's highest share among its categories); a post with none of the 23 has no cap.
- An author with no score: M8 stores only scored promoters, so their own main category is unknown; Kala's ladder starts at the post's categories.
- A shortlist shorter than the page plus one spare page (no post index yet, a user with nothing to retrieve) is **topped up with ENG-06's eligible posts, newest first**, after the ranked ones (they carry no score), so the feed is never empty for want of candidates. Counted as `topped_up`.
- Engagement quality's average is the shortlist's own (Σ engagements ÷ Σ views); with no views at all, every post is at the same 0.5.
- A group of one has percentile 1 (the best of one).
- The interest profile is read before the shortlist (the sources need its top-5 categories), so the feed's two engine reads run one after the other.

## 3. Configuration

No new settings: `ranking.*`, `serving.page_dedup_hours` (24), `serving.exploration_*`, `slots.interest`, `slots.promoter_score`.

## 4. Tests

`tests/test_feed_ranking.py`, 17: the weighted sum by hand for two posts; interest the highest share; freshness halves every 3 days; engagement shrinkage (one view at 100% no longer beats 1,000 at 60%); Kala's ladder (own, category median, average of medians, platform, 0.5); ties; commission is no input; two in a row; three per author; the category cap ceil(0.4 × limit), never below 2; relaxation order and the page always full; a short shortlist; the shuffle fix; page 2 leaves out page 1 (product surface's rule too); the feed ranks the shortlist by the formula (by hand: 0.793 and 0.695) and tops up after it; page two leaves out what was served. MongoDB: posts, views, a promoter batch and the post index: a full page of 10, never 3 in a row by one author, at most 3 per author unless relaxed, the spares in score order; a product's commission changed → the same order and scores; page 2 shares nothing with page 1. `tests/test_recommendations.py`: its stub now stands in for the feed ranking (no assertion changed).

Results, 17 Oct 2026: 17 passed (16 unit, 1 MongoDB).

## 5. Runbook

```bash
python -m pytest -q tests/test_feed_ranking.py
python -m reco.jobs post_index      # the index now carries views and engagements
python -m reco.jobs promoter        # now also writes the category medians
```

## 6. Open

| What | Waits on |
|---|---|
| The check on the test server (ranking stage within 80 ms there) | The test server |
| The feed's speed end to end (ENG-20 part 2) | The test server |
| Reason codes stay null in Wave 1A (ENG-06) | — |

## 7. Files changed

| File | Change |
|---|---|
| `reco/ranking/feed.py` | New: the formula, variety, the shuffle fix, the request |
| `reco/ranking/serving.py` | `Candidate.score`, `Candidate.author_id`; `Built.page_start`; `leave_out_served` |
| `reco/api/recommendations.py` | The feed served by ENG-19; paging on both surfaces; the shuffle fix |
| `reco/ranking/post_index.py`, `reco/store/item_state.py` | Views and engagements per post; `read_posts_by_ids` |
| `reco/store/promoter.py`, `reco/slots/promoter/job.py` | `read_promoter_scores`, the medians written with each batch |
| `reco/store/writers.py` | `read_served_item_ids` |
| `tests/test_feed_ranking.py` | New |
| `tests/test_recommendations.py` | The stub for the feed ranking |
| `scripts/run_checklist.sh`, `scripts/make_proofs.py` | Section 17; the ranking proof folder |
