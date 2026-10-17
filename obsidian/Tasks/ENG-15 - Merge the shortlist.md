---
tags: [task, step-3]
task: ENG-15
status: Built
owner: Allen
---
# ENG-15: Merge the shortlist

> [!note] Status: **Built** (16 Oct 2026, on my laptop)
> Works and is tested, including on a real database. Becomes **Passed** when the checklist runs on the test server. With it, all four M2 tasks are built.

**In one line:** for each person, combine the pool of 300 ([[ENG-13 - Quotas]]) with their similar posts ([[ENG-14 - Similar posts]]) into one shortlist of up to 200, which the feed's ranking will order.

## Why this task
It's the last step of M2. The ranking of the feed (ENG-19) starts from this shortlist. → [[Build Steps]]

> [!example] The idea in one picture
> Two judges score in different units: one counts views, the other measures likeness. To compare them fairly, each score is turned into "how this post ranks within its own judge's list", from 0 (last) to 1 (first). Then the two lists are dealt out together, about 3 cards from the pool for every 2 similar ones, until 200.

## Subtasks, one by one

### 1. Both methods for everyone ✅
- **What it asks:** everyone gets both lists merged; it's not a split between groups.
- **What we did:** every shortlist mixes the two, unless a person has only one of them.

### 2. Comparable scores ✅
- **What it asks:** turn each score into its place within its own source, 0 to 1; compare only those.
- **What we did:** exactly that; the best post of every source scores 1.

### 3. No duplicates; keep the better score and both tags ✅
- **What we did:** a post offered by both keeps one place, the higher of its two scores, and both labels (e.g. "interest" and "similar").

### 4. Cut to 200 by order, not by score ✅
- **What it asks:** take posts in the pool's order so the 40/30/20/10 shares survive the cut.
- **What we did:** the pool keeps its order. The similar posts are dealt in alongside, in proportion to the two lists' sizes: about 120 from the pool and 80 similar. The pack doesn't say where the similar posts go, so that's my choice, and it's question 8 for Nisha.

### 5. Similar posts checked by the filters too ✅
- **What we did:** a blocked, hidden or deleted post on someone's similar list is taken out, like in the pool.

### 6. Log the pool size per source on each request ✅

## Result (16 Oct 2026)
- 14 automatic checks pass (one on a real database: 200, no duplicates, a blocked author's post kept out, both methods present).
- All 692 automatic checks pass.

## Decided
- **16 Oct 2026:** similar posts are mixed in about 2 for every 3. **Confirmed by Nisha**; on 17 Oct the mix became a setting (0.4 of the places for similar posts), and every request logs how many of the 200 came from each list.

## Still to do
| What | Waiting on |
|---|---|
| Hand the shortlist to the feed's ranking | ENG-19 |
| Run its check on the test server | The test server → [[Environments]] |

## How this connects
- **Built on:** [[ENG-12 - Candidate sources]], [[ENG-13 - Quotas]], [[ENG-14 - Similar posts]], [[ENG-08 - Filters]]
- **Next:** ENG-19, ordering the feed (needs the promoter score, ENG-16, first).
- **Technical version:** `docs/engineering/ENG-15.md` in the repo.
