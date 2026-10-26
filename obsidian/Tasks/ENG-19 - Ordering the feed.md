---
tags: [task, step-4]
task: ENG-19
status: Passed
owner: Allen
---
# ENG-19: Ordering the feed

> [!note] Status: **Passed** (19 Oct 2026, on the test server)
> Its check passed on the **test server** on 19 Oct 2026 (lines 17.1 and 17.2, 2 of 2). The test server is far from the database and slow, which does not affect this check.

**In one line:** put each person's feed in order: take their shortlist of 200 posts, give every post a score from what they like, how good the author is, how new the post is and how much people engage with it, then fill the page so it isn't all one person or one topic.

## Why this task
This is where the models meet the feed. Until now the feed showed the newest posts; now it uses M1 (what you like), M2 (finding posts) and M8 (promoter score) together. → [[Build Steps]]

> [!example] The idea in one picture
> A playlist: songs are scored on your taste, the artist, how new they are and how much others liked them. Then the playlist is shuffled just enough that no artist plays three times in a row and no genre takes over.

## What came before
- [[ENG-15 - Merge the shortlist]]: the 200 posts to choose from.
- [[ENG-16 - Promoter score]]: how good each author is.
- [[ENG-10 - Interest score on real data]]: what each person likes.

## Subtasks, one by one

### 1. The score ✅
- **What it asks:** five parts, each 0 to 1: how much you like the post's category (35%), how well it was found (15%), the author's promoter score (20%), how new it is (20%, halving every 3 days), and how much people engage with it per view (10%, steadied toward the average until a post has had about 50 views).
- **What we did:** exactly that. An author with no promoter score gets the middle of their category's scores (Kala's rule). Commission is never part of it.

### 2. Variety on the page ✅
- **What it asks:** no more than 2 posts in a row from the same person, at most 3 per person on a page, at most 40% from one category; if the page can't be filled, loosen the rules in that order.
- **What we did:** exactly that, and every loosening is logged.

### 3. Exploration can't undo variety ✅
- After the small random shuffle (5% of feeds), the "no 3 in a row" rule is checked again.

### 4. Page 2 and later ✅
- **What it asks:** anything you were shown in the last 24 hours doesn't come back on later pages.
- **What we did:** exactly that, on the feed and on the product rail.

## Result (17 Oct 2026)
- 17 automatic checks pass, including the pack's: the order follows the formula, the variety rules hold, and changing a product's commission changes nothing.

## Decided
- **17 Oct 2026:** if there aren't enough posts to fill a page (for example, a brand-new setup), the rest of the page is filled with the newest eligible posts, so the feed is never empty.
- **17 Oct 2026:** for the "40% per category" rule, a post counts under the category you like most among its tags.

## Still to do
| What | Waiting on |
|---|---|
| Run its check on the test server (and the speed there) | The test server → [[Environments]] |

## How this connects
- **Built on:** [[ENG-15 - Merge the shortlist]], [[ENG-16 - Promoter score]], [[ENG-10 - Interest score on real data]], [[ENG-06 - Serve a recommendation list]]
- **Next:** the go-live checks (ENG-20, ENG-22, ENG-23, ENG-24).
- **Technical version:** `docs/engineering/ENG-19.md` in the repo.
