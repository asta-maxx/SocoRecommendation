---
tags: [concept, database]
---
# Collections

A **collection** is like a **drawer** in a filing cabinet. The database is the cabinet, and each drawer holds one kind of document.

My [[Engine Database]] has **16 drawers** (pack v1.3; the 22 Sep pack had 12). All start with `ml_`, so they're easy to tell apart from SOCO's:

| Collection | Holds (plain words) | Filled by task |
|---|---|---|
| `ml_events` | Copies of SOCO's activity log and served lists, plus the engine's own record of each list it served | ENG-04 |
| `ml_orders` | Copies of SOCO's orders, with each order's status history | ENG-04 |
| `ml_sync_state` | The engine sync's bookmark and how far behind it is, per SOCO collection | ENG-04 |
| `ml_item_state` | Whether each post, account and product can be shown right now | ENG-27 |
| `ml_deletions` | Accounts confirmed deleted, and when their data was removed | ENG-28 |
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

Most are still **empty drawers**. The interest scores came from the demo, and the engine sync fills `ml_events`, `ml_orders` and `ml_sync_state` → [[Engine sync]]. Later tasks fill the rest.

> [!note] `ml_events` and `ml_orders` empty themselves slowly: each copy is deleted **365 days** after the event really happened. SOCO's own log only keeps 90 days.

## How this connects
- They live in → [[Engine Database]].
- They were created in → [[ENG-01 - Engine home and databases]].
- To find things quickly inside a drawer → [[Indexes]].
