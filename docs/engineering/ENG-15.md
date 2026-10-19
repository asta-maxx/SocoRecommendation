# ENG-15: Merge the two retrieval methods

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 3 (within 17 working days) |
| **Waits on** | ENG-13 (Built), ENG-14 (Built) |
| **Needed by** | ENG-19 (feed ranking), ENG-22 (retrieval checks) |
| **Status** | **Passed** (19 Oct 2026): its check passed in the checklist on the **test server** (19 Oct 2026, environment test, commit 6ddc3ce; proofs in `Test Output (test server)/`): lines 14.1 and 14.2, 2 of 2. Built on dev before |
| **Spec** | Build List v1.4 ENG-15; Settings sheet "M2 retrieval" (shortlist cap 200, fixed); ENG-13 (the interleaved order); ENG-08 (filters) |

## 1. What the item requires

> Merge the method-one pool and the method-two list for every user. Both methods run for everyone: this is not a traffic split. Source scores are not comparable across sources: a view count is not a cosine similarity. Before merging, replace each candidate's source_score with its percentile within its own source, from 0 to 1. Only these percentiles are ever compared. Remove duplicates, keeping the higher percentile and recording both source tags. Cut the shortlist to 200 by taking candidates in the ENG-13 interleaved order, not by score, so the quotas survive the cut. Pass it to the ranking layer. Log the pool size per source on each request.

*How to check it is done:* "The shortlist has 200 or fewer items and no duplicates."

## 2. What was built: `reco/ranking/merge.py`

- `percentiles(items)`: within one source's list for this request (ENG-12's output, before quotas): `(below + (equal − 1)/2) / (n − 1)`. The best is 1, the worst 0, ties share the midpoint; one item gives 1. A repost merged into its original keeps the repost's percentile.
- `merge(pool, sources, similar, size)` (no database): two lanes, the method-one pool in ENG-13's interleaved order and the method-two list in rank order, interleaved **in proportion to their sizes** by the same smooth round-robin as ENG-13 (300 to 200 gives 3 to 2; the first five run one, two, one, two, one; a cut at 200 holds 120 and 80). Method one's items keep ENG-13's order exactly, so its quotas survive the cut within 1. A user with only one list gets that list alone.
- **Duplicates:** the first place an item reaches stands. A later copy (in either lane, including copies past the cut) adds its source tag to `sources` and raises `percentile` if higher; it does not take a place. `ShortlistItem(item_id, item_type, sources, percentile, method)`, where `sources[0]` and `method` name the place it holds.
- `eligible_similar`: the method-two list through ENG-08 (one platform read and `eligible_posts`), as ENG-13 filters the pool; a post gone from the platform is excluded and logged (`missing`).
- `shortlist_for_user(settings, user_id, profile, viewer, request_id)`: ENG-12 sources → ENG-13 pool → method-two list filtered → merge → cut to `retrieval.shortlist_size` (200). One log line per request (`reco.retrieval`, message `shortlist`): `request_id`, **`pool_sizes` per source** (interest, follows, trending, popular as taken into the pool; similar after filters), `shortlist_size`, `by_source`, `duplicates`, `excluded_method_two`, `dropped_sources`.

**Where the pack is silent (decided 16 Oct 2026; confirmed by Nisha 16 Oct, built as a setting 17 Oct):** method two has no place in ENG-13's order, so where its items sit in the cut is a choice. In proportion to the two lists' sizes keeps both methods for everyone at every cut; appending it after the pool would lose it entirely at 200. The percentile is over what the source returned for the request, not only what reached the pool.

## 3. Configuration

`retrieval.shortlist_size` (200, fixed); the ENG-12 and ENG-13 settings.

## 4. Tests

`tests/test_merge.py`, 14 tests: percentiles 0 to 1, ties, one item, empty; a view count and a cosine both become 1 at their best; 200 with no duplicates; 120 to 80 in proportion; the cut keeps method one's order and quotas within 1; pool alone; method-two list alone; a duplicate keeps the higher percentile and both tags (including the lower-ranked copy); a merged repost keeps its percentile; pool sizes per source logged with the request id; the cap is the setting; method two filtered (excluded and missing). MongoDB: post index + a stored method-two batch + a real viewer: 200, no duplicates, a blocked author's similar post filtered, both methods present, a post in both lists carrying two tags.

Results, 16 Oct 2026: 14 passed (13 unit, 1 MongoDB); unit suite 692 passed, 1 skipped.

## 5. Runbook

```bash
python -m pytest -q tests/test_merge.py
```

## 6. Open

| What | Waits on |
|---|---|
| Pass the shortlist to ranking (the request path still serves the interim list) | ENG-19 |
| ENG-22's script (shortlist for every test user, quotas, filters, reposts, method two empty under 3 engaged) | ENG-17, ENG-22 |
| Check on the test server | The test server |

## 7. Files changed

| File | Change |
|---|---|
| `reco/ranking/merge.py` | New: percentiles, merge, cut, method two filtered, wiring and the log line |
| `tests/test_merge.py` | New |
| `scripts/run_checklist.sh` | Section 14 |

## Update, 17 Oct 2026: the mix as a setting (Nisha)

- `retrieval.shortlist_method_two_share` (0.4; 0 to 1; not on the pack's Settings sheet): method two's share of the places when both lists are full. 0.4 is the two lists' full sizes (200 of 300 + 200), so a cut at 200 keeps 120 and 80, as before. A list that runs short passes its places to the other (a user with no list gets 200 from the pool). A share of 0 or 1 puts one list first and the other fills what is left.
- **Changed from 16 Oct:** the proportion was each user's two list sizes; it is now the setting. For users with full lists the result is the same.
- `Shortlist.by_method` and the `shortlist` log line's `by_method`: how many of the 200 came from each list, on every request.
- Tests: +4 (the setting, a short list passes its places on, share 0 and 1, the per-list counts logged). Results: 17 unit + 1 MongoDB passed. Checklist 14.1 now expects 17.
