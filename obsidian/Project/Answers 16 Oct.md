---
tags: [project, decisions]
---
# Answers, 16 Oct 2026

On 16 Oct Kala answered my questions and gave feedback on the test results, and SOCO's app team (Aravinth) answered 12 questions from their own code. This note says what they decided, and what changed because of it. The full technical record is `docs/engineering/ANSWERS_2026-10-16.md`. → [[People]], [[The Pack]]

## The big news: eight tasks are Passed
Kala: the checks of **ENG-03, 05, 07, 08, 09, 10, 11 and 29** don't name a place to run, so the run on my laptop counts. They're **Passed**. ENG-01, 04 and 06 still need the test server, and ENG-02 needed one fix first (below, done). → [[Task Board]]

## What changed in the engine
| What | Before | Now | Task |
|---|---|---|---|
| Blocks | Guessed the field names, wrongly | The app's real ones: who blocked, and who was blocked | [[ENG-08 - Filters]] |
| "Is this person active?" | Read a status field the app doesn't use | The app's own rule: active unless moderated (suspended or banned) | [[ENG-08 - Filters]] |
| Engine database down, no old score | Fell back to "popular" | An error at once, so SOCO shows its own feed (rung 3 needs the same database) | [[ENG-09 - Fallback ladder]] |
| Settings rolled back to an older version | Not written in the diary | Written, marked as a rollback | [[ENG-02 - Service skeleton and settings]] |
| Order history | 10 kinds of line | The app's other lines too ("Order placed", "Rejected by buyer", a replacement or exchange), information only | [[ENG-30 - Adapting to the October platform facts]] |
| Category map | Empty | **78 names** matched to the 23; unmatched labels down from **42 to 7** | [[ENG-29 - Adapting to the platform as built]] |
| Reading store records | Whole records | Only the fields needed; never ID, tax or bank details | [[ENG-03 - Reading SOCO's data correctly]] |

## What the 7 unmatched labels are
The two "Menswear catimp…" categories (2,005 products) are **leftover test data** from the app's import tests, so they stay unmatched (Aravinth to delete them on dev). Two products have no category at all. "Nature", "Fishing" and "Shopping" are labels the app itself gives no interest. "Fishing & Marine" is one business, a question for Kala.

## Kala's "why are products hidden?" (F3)
She suspected a bug. It isn't one: almost all of dev's 2,011 products belong to **stores with no status**, which are the test stores above. Only one real store is active, and its 3 products show. → [[ENG-08 - Filters]]

## Decided for later tasks
Kala settled the open questions for the next tasks: what "trending" means (ENG-12), the post types (ENG-14), how followers and account age are counted (ENG-16), the cart on product pages (ENG-17), the fallback for an author with no promoter score (ENG-19), and the commission defaults (ENG-30). → [[Task Board]]

## Still open
| What | With |
|---|---|
| ~~"The 5-action count must equal the interest score's count"~~ | Answered later on 16 Oct: one definition, as built; own-post likes now left out of the score too |
| Three app interests outside the 23 (Watches, Appliances, Tools & Home Improvement), and 4 unmatched labels | Kala |
| Run the two catch-up scripts on dev, so views and change times appear | Aravinth → [[Aravinth's tasks]] |
| Delete the catimp test stores on dev | Aravinth |
| Test-account ids (the app knows them only by email address) | Aravinth |
| Dates for the serve log and the restriction fields | Aravinth |

## How this connects
- The rules all this follows → [[The Pack]].
- Who answered → [[People]], [[Aravinth's tasks]].
- The tasks it moved → [[Task Board]].
