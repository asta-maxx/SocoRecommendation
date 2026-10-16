---
tags: [task, step-3]
task: ENG-13
status: Built
owner: Allen
---
# ENG-13: Quotas (the pool of 300)

> [!note] Status: **Built** (16 Oct 2026, on my laptop)
> The pool works and is tested, including on a real database. It becomes **Passed** when the checklist runs on the test server.

**In one line:** from the sources' posts, make one pool of up to 300 for each person: 40% from their favourite categories, 30% from people they follow, 20% trending, 10% popular, taken in turns, with no post twice.

## Why this task
The sources ([[ENG-12 - Candidate sources]]) each offer up to 300 posts. This task decides how many each one gets, in what order, and makes sure nothing hidden, blocked or repeated gets in. The merge ([[ENG-15 - Merge the shortlist]]) cuts this pool to 200 by its order, so the order matters. → [[Build Steps]]

> [!example] The idea in one picture
> Four queues at a counter, served in turns: four from the first queue for every three from the second, two from the third and one from the fourth. If a queue empties, its turns go to the next queue. Anyone already served doesn't get served again, and a reshared post counts as the original post.

## What came before
- [[ENG-12 - Candidate sources]] offers the posts, each tagged with its source.
- [[ENG-08 - Filters]] says what may never be shown (blocked, hidden, private, and so on).

## Subtasks, one by one

### 1. 300 places in the proportions ✅
- **What it asks:** 40% interests, 30% follows, 20% trending, 10% popular.
- **What we did:** 120, 90, 60 and 30 places, from the [[Settings file]].

### 2. Taken in turns ✅
- **What it asks:** interleave the sources round-robin in those proportions.
- **What we did:** each next place goes to the source furthest behind its share. Even the first 10 or 50 posts keep the proportions, so a cut anywhere keeps them.

### 3. A short source passes its places on ✅
- **What it asks:** if a source runs short, its share goes to the next one in order.
- **What we did:** exactly that. After "popular" (the last), the places go back round to "interests". The pack doesn't say who comes after popular, so that's my choice, and it's question 7 for Nisha.

### 4. No duplicates; a repost counts as its original ✅
- **What it asks:** remove duplicates; a reshared post is the same as the post it reshares.
- **What we did:** the first source to reach a post keeps it, and the others take their next one, so a duplicate never wastes a place. A reshared post is replaced by its original, and keeps the tag of the source that found it.

### 5. Filters before and after ✅
- **What it asks:** apply the filters (ENG-08) before and after.
- **What we did:** before, every offered post is checked, so the quotas count only showable posts. After, the originals that reshared posts bring in are checked too (an original can be hidden even if the reshare isn't); if one fails it's taken out and the pool is rebuilt, so it stays full. Every exclusion is logged with its reason.

### 6. Every candidate keeps its source tag ✅

### Extra: following a reshare back to the original ✅ (ENG-30 point 3)
- **What it asks:** a reshare of a reshare… is followed back to the first post, at most 10 steps; a loop or a broken link stops it and is logged.
- **What we did:** built here because the pool needs it. The list of recent posts now stores each post's original. Later the promoter score (ENG-16) and fraud (ENG-21) use the same rule. → [[ENG-30 - Adapting to the October platform facts]]

## Result (16 Oct 2026)
- 24 automatic checks pass (one on a real database: 300 or fewer, quotas within 1, no duplicates, a blocked author kept out before and a hidden original kept out after).
- That database check found a bug when several sources offer the same posts and all run short; fixed, and a check added so it can't come back.

## Decided
- **16 Oct 2026:** after "popular" runs short, its places wrap round to "interests" (to confirm with Nisha, Q7).
- **16 Oct 2026:** a reshare whose chain is broken is offered as itself; a recent reshare brings its original in even if the original is older than 30 days.

## Still to do
| What | Waiting on |
|---|---|
| Confirm the wrap-round | Nisha (Q7) |
| Run its check on the test server | The test server → [[Environments]] |

## How this connects
- **Built on:** [[ENG-12 - Candidate sources]], [[ENG-08 - Filters]], [[ENG-30 - Adapting to the October platform facts]]
- **Next:** [[ENG-15 - Merge the shortlist]]. It adds the similar posts ([[ENG-14 - Similar posts]]) and cuts to 200.
- **Technical version:** `docs/engineering/ENG-13.md` in the repo.
