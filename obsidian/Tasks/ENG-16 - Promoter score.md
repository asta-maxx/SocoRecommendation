---
tags: [task, step-3]
task: ENG-16
status: Passed
owner: Allen
---
# ENG-16: Promoter score (M8)

> [!note] Status: **Passed** (19 Oct 2026, on the test server)
> Its check passed on the **test server** on 19 Oct 2026 (lines 15.1 to 15.3, 3 of 3). The test server is far from the database and slow, which does not affect this check.

**In one line:** every night, score each person or store who posts (a "promoter") from 0 to 1 on how well their posts do: how many people they reach, how much those people engage, how regularly they post, and how many real, kept sales come through their posts.

## Why this task
The feed's ranking (ENG-19: author's promoter score is 20% of a post's rank) and the hidden opportunity list (ENG-18) both need it. → [[Build Steps]]

> [!example] The idea in one picture
> A league table for each category (food, fashion, pets…). Each promoter is ranked against others in the same category on six things, and the ranks are combined. Someone with little evidence yet is pulled toward the middle until their record builds up, and the score says how sure it is.

## What came before
- [[ENG-10 - Interest score on real data]]: what counts as a proper view (3 seconds).
- [[ENG-04 - Engine sync]]: copies of views, orders and return requests.
- [[ENG-30 - Adapting to the October platform facts]]: reshares lead back to the original; returns; return requests.

## Subtasks, one by one

### Extra: three platform facts first ✅ (ENG-30 points 1, 2, 8)
- **Who promoted an order:** the order says; if not, the post's author.
- **One person:** a person and the stores they own count as one person, so buying through your own store isn't a sale.
- **Return window:** each product's own window (0 if it can't be returned; 7 days if it doesn't say, noted as a fallback), plus 2 days.

### 1. Who is scored ✅
- **What it asks:** active accounts, not suspended, not test or exempt, at least 14 days old, with at least one original post (not a reshare) in 90 days. Stores too. Reshare-only accounts aren't scored.
- **What we did:** exactly that, plus "no proper views in 30 days: not scored" (never scored as zero).

### 2. Sales through their posts ✅
- **What it asks:** a sale through a reshare counts for the original author; buying from yourself counts for nobody; a sale only counts once it's delivered, past its return window plus 2 days, with no return request open, and not returned or cancelled.
- **What we did:** exactly that. On dev, 36 sales came through reshares and went to the original authors.

### 3. Six measures, ranked within the category ✅
- Reach, engagement per view, regular posting, sales value, sales per 1,000 views, and how few orders go wrong. Until there's sales data, only the first three count (40/40/20).

### 4. Two methods ✅
- **Method one:** pulled toward the category's middle until there's enough evidence, with a "how sure" number next to it.
- **Method two:** ranked against promoters of the same category and audience size (under 1,000 followers, 1,000–10,000, over 10,000); a group under 20 uses the whole category, then everyone.

### 5. Confirmed fraud halves the score ✅
- A confirmed case that led to a restriction halves the score; suspended or removed accounts aren't scored. (Cases come from ENG-21, not built yet.)

### 6. Stored nightly, copied monthly ✅
- Written as a batch each night; on the 1st of each month a copy is kept.

### 7. Return requests must be up to date ✅
- If the copy of SOCO's return requests isn't current, the job doesn't run that night (yesterday's scores stay) and it's flagged.

## Result (17 Oct 2026)
- 17 automatic checks pass, including one on a real database covering every case in the pack's check.
- On SOCO's dev data: 108 promoters scored under both methods. All are marked "low confidence" for now, because dev doesn't have many views yet.

## Decided
- **17 Oct 2026:** a promoter with no finished orders gets the middle (0.5) for "how few orders go wrong", not the bottom.
- **17 Oct 2026:** the three sales measures switch on together, once any promoter has a finished order.

## Still to do
| What | Waiting on |
|---|---|
| Fraud cases to read | ENG-21 |
| Restriction fields on accounts | Aravinth (DB-08) |
| The feed's ranking uses it | ENG-19 |
| Run its check on the test server | The test server → [[Environments]] |

## How this connects
- **Built on:** [[ENG-30 - Adapting to the October platform facts]], [[ENG-04 - Engine sync]], [[Nightly batches]]
- **Next:** ENG-19, ordering the feed (now unblocked: M1, M2 and M8 are built).
- **Technical version:** `docs/engineering/ENG-16.md` in the repo.
