---
tags: [task, step-3]
task: ENG-12
status: Built
owner: Allen
---
# ENG-12: Candidate sources

> [!note] Status: **Built** (16 Oct 2026, on my laptop)
> The four sources (and the read of the "similar posts" list) work and are tested. The pack's check is timed "on test load", so it becomes **Passed** on the test server.

**In one line:** for each person, quickly gather posts worth considering for their feed from five places: their favourite categories, people they follow, what's trending in their categories, what's popular everywhere, and posts similar to ones they liked.

## Why this task
It's the first step of M2, finding posts for the feed. The quotas (ENG-13), the merge (ENG-15) and the feed's ranking (ENG-19) all start from these candidates. → [[Build Steps]]

> [!example] The idea in one picture
> A shop assistant filling a basket of things to show you: some from aisles you love, some from brands you follow, some of this week's bestsellers in your aisles, a few of the shop's overall bestsellers. Each aisle gets 20 milliseconds; an aisle that's too slow is skipped this time (and noted), so you're never kept waiting.

## What came before
- [[ENG-10 - Interest score on real data]] gives each person's favourite categories; the top 5 feed source 1. → [[Two methods per slot]]
- [[ENG-04 - Engine sync]] copies the views that make something "trending" or "popular". → [[Engine sync]]

## Subtasks, one by one

### A. Extra: a ready-made list of recent posts ✅
- **What we did:** every 15 minutes the engine makes a list of the last 30 days' posts, each with its categories (one of the 23) and how many people properly viewed it (3 seconds or more) in the last 7 days. Test accounts' views don't count; seed posts (test data) aren't on it.
- **Why it matters:** each source has only 20 ms, far too little to count views across everything. With the list ready, a source just reads it.
- **Status:** done. → [[Nightly batches]]

### 1. Your top-5 categories ✅
- **What it asks:** posts in the person's 5 favourite categories.
- **What we did:** posts from the last 30 days in those categories, best match first (by how much the person likes the post's category).
- **Status:** done.

### 2. People you follow ✅
- **What it asks:** posts by accounts the person follows.
- **What we did:** their recent posts, newest first.
- **Status:** done.

### 3. Trending in your categories ✅
- **What it asks:** trending in the person's categories, by proper views over 7 days.
- **What we did:** as Kala said: the most viewed posts of the last 7 days, but only in the person's top 5 categories; ties go to the newer post.
- **Status:** done.

### 4. Popular everywhere ✅
- **What it asks:** the most viewed posts of the last 7 days, across all of SOCO.
- **Status:** done.

### 5. The "similar posts" list ✅ (read)
- **What it asks:** read the person's stored list of similar posts at the same time.
- **What we did:** read in parallel; the list itself is [[ENG-14 - Similar posts]], built 16 Oct; the source now reads it directly.

### 6. Too slow? Skip it, and note it ✅
- **What it asks:** a source over its 20 ms is dropped for that request and logged.
- **What we did:** exactly that; the others still answer.
- **Status:** done. From my laptop each source takes 23 to 30 ms (the internet trip to the database), so three were skipped and logged in a trial, as they should be. On the test server, next to the database, they should fit.

## Result (16 Oct 2026)
- 10 automatic checks pass (one on a real database).
- On dev the list of recent posts is empty: none of dev's 8 posts is from the last 30 days.

## Decided
- **16 Oct 2026:** a post's "interest" score is how much the person likes its best category; "follows" ranks newest first; trending and popular count people, not view records.

## Still to do
| What | Waiting on |
|---|---|
| Put the sources together into the pool of 300 | [[ENG-13 - Quotas]] |
| The 20 ms check on the test server | The test server → [[Environments]] |

## How this connects
- **Before it:** [[ENG-30 - Adapting to the October platform facts]]
- **Built on:** [[ENG-10 - Interest score on real data]], [[ENG-04 - Engine sync]], [[Nightly batches]], [[Settings file]]
- **Next:** [[ENG-13 - Quotas]]. It builds the pool of 300 from these sources: 40% interests, 30% follows, 20% trending, 10% popular.
- **Technical version:** `docs/engineering/ENG-12.md` in the repo.
