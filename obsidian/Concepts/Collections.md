---
tags: [concept, database]
---
# Collections

A **collection** is like a **drawer** in a filing cabinet. The database is the cabinet, and each drawer holds one kind of document.

My [[Engine Database]] has **12 drawers**. All start with `ml_`, so they're easy to tell apart from SOCO's:

| Collection | Holds (plain words) | Filled by task |
|---|---|---|
| `ml_events` | Everything users did that the app told me about | ENG-04 |
| `ml_user_interest_scores` | What each person is into (from the demo) | ENG-10 |
| `ml_product_scores` | "You might also like" product lists | ENG-17 |
| `ml_promoter_scores` | How good each promoter is | ENG-16 |
| `ml_promoter_scores_monthly` | A monthly copy of the above, for history | ENG-16 |
| `ml_opportunity_scores` | Which products suit which promoter | ENG-18 |
| `ml_user_candidates` | A shortlist of posts similar to what each person likes | ENG-14 |
| `ml_fraud_flags` | Suspicious activity spotted | ENG-21 |
| `ml_fraud_cases` | Cases for a person to review | ENG-21 |
| `ml_job_runs` | A log of every nightly job | ENG-07 |
| `ml_config_changes` | A log of every settings change | ENG-02 |
| `ml_measurements` | Weekly reports | ENG-24 / ENG-25 |

Right now they're **empty drawers**, apart from the interest scores. Later tasks fill them.

## How this connects
- They live in → [[Engine Database]].
- They were created in → [[ENG-01 - Engine home and databases]].
- To find things quickly inside a drawer → [[Indexes]].
