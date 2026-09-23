---
tags: [project, history]
---
# Before Wave 1A: the M1 demo

Before Wave 1A, I built a small demo of **one** piece: the **interest score** (called **M1**).

## What M1 does, in plain words
It works out **what each person is into**. It looks at what they viewed, clicked, bought and so on, and turns that into percentages per category, for example *"40% Fashion, 30% Electronics…"*.

There are two ways of calculating it:
- **Recency decay:** recent actions count more, older ones slowly fade.
- **Time windows:** actions are grouped into "last week", "last month" and "last 3 months", each with its own weight.

## What was already built (still in the repo)
- Both ways of calculating the score.
- A **fallback ladder**: what to show someone new with no history.
- Storing the scores in `ml_user_interest_scores`.
- A demo dashboard.

## What changed when Wave 1A arrived
| Before (demo) | Now (Wave 1A) |
|---|---|
| Only M1 | M1 plus many more pieces |
| The engine's data was meant to live **inside** SOCO's database | The engine has its **own separate database** → [[Engine Database]] |
| One setup | Three setups: dev, test, production → [[Environments]] |
| A live password was accidentally shared | A new login is being made (task DB-02) → [[Secrets and passwords]] |

## How this connects
- M1 is one part of → [[Wave 1A]].
- Its score collection now lives in → [[Engine Database]].
- The first Wave 1A task built on this demo's code → [[ENG-01 - Engine home and databases]].
