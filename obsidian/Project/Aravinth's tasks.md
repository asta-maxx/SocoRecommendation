---
tags: [project, people, tracking]
---
# Aravinth's tasks

Everything Aravinth builds (tasks starting **APP-** and **DB-**), and what my tasks need from him. → [[People]]

> [!important] Statuses are tracked **here**, not in the pack
> The pack in `docs/updated/` is final and never edited, so its Status column stays as it was on 29 Sep. This note holds the real, current state. "Pack says" is what the pack's Status column shows; "What we see" is what SOCO's database actually shows.

*Last checked: 15 Oct 2026, against pack v1.4.*

> [!note] Pack v1.4 (14 Oct)
> **DB-02 is removed**: the engine keeps its current read-only login, which can also read the two new collections v1.4 needs (`returnrequests`, `commissionconfigs`; checked 15 Oct). **APP-16** is now Built. **DB-03, APP-08 and APP-10** were corrected: there is no "Return Requested" status; the return button creates a return-request record, and only the seller's return sets "Returned". None of this asks Aravinth to change anything. (APP-02 is listed under Built, as the pack says, but see its note.)

## What's holding up my work
Ask for these first. When asking, quote both task numbers, e.g. *"DB-12 → ENG-01"*.

| His item | What it is | Pack says | What we see | Holds up |
|---|---|---|---|---|
| **DB-12** | Network: the engine can reach SOCO's database, and SOCO_BE can reach the engine privately | To build | Not done | [[ENG-01 - Engine home and databases]], and the test server setup |
| **APP-12** | Change times (`updated_at`) on SOCO's activity, orders and served lists | Built (reported) | **Not on dev:** 0 of 146 activity rows, 0 of 12 served lists (1 Oct) | ENG-04's 5-minute copy, ENG-10, ENG-23, his DB-16 |
| **APP-15** | SOCO_BE asks the engine for the feed and product lists; creates its serve log | To build | Serve log (`rec_serve_log`) doesn't exist | ENG-23, his APP-21, then go-live (ENG-24) |
| **DB-01** | Leave SOCO's 90-day deletion as it is. The pack says **do this first** | To build | Not confirmed | Copies on test and production must be taken before data turns 90 days old |
| **Question 16** | How a block is stored in `followers` | Open | Collection is empty on dev | [[ENG-08 - Filters]] (block rule guesses today) |
| **Question 17** | Does an account with **no status** count as active? | Open | 2,006 of 2,011 products have sellers with no status | ENG-08; **why the product list is empty on dev** |
| *(for ENG-20)* | The `/dashboard-feed` address and a test login | — | Not received | [[ENG-20 - Speed test]] part 1 |

## Built
| Item | What | Notes |
|---|---|---|
| APP-00 | Check of the parts already built | I verify them |
| APP-01 | One session id per app visit | No Wave 1A model uses it |
| APP-02 | On-screen time on every view | **Not seen on dev:** none of the 17 views in the engine's copy has it (14 Oct). Without it no view qualifies, so the ladder's rung 3 is empty → [[ENG-09 - Fallback ladder]]. I check it in ENG-23 |
| APP-04 | Incognito hides who bought, nothing else | → [[Wave 1A]] |
| APP-05 | The list id carried from the card to the order | |
| APP-06 | Every cart change recorded | |
| APP-07 | A purchase row for every order | |
| APP-10 | Request return button | Already existed; v1.4: it creates a return-request record, and the seller's return sets Returned |
| APP-22 | Basket test | |
| APP-16 | No commission when you buy from your own post (or any of your own accounts) | Built by the platform (v1.4) |
| DB-05 | First list kept on the cart item | |
| DB-03 | Returns: nothing to build | v1.4 corrected: no Return Requested status |

## Still to build
| Item | What | Step | Matters to me because |
|---|---|---|---|
| APP-08 | Every order status change writes a step into the order's history (`tracking_info`) | 2 | ENG-10 and the fraud rules (ENG-21) read that history |
| APP-03 | Session id per view | 2 | Closed, nothing to build (status never updated) |
| APP-21 | Launch tests in the real app: engine down, surface off, blocking, incognito | 5 | The go-live rule (ENG-24) needs it |
| DB-11 | Clear test data before launch | 6 | Kept test accounts go on my test-account list |
| DB-16 | Production move of the old logs into SOCO's main activity log | 6 | Needs my ENG-04 and his APP-12; I copy everything after it |
| DB-08, APP-17, APP-18, APP-19 | Fraud restrictions, review screen, notices, appeals | Once SOCO names the fraud roles | APP-17 needs my ENG-21 |

## Not needed (14)
APP-09, APP-11, APP-13, APP-14, APP-20, APP-24, DB-04, DB-06, DB-07, DB-09, DB-10, DB-13, DB-14, DB-15. Their work moved into my [[ENG-29 - Adapting to the platform as built]], or isn't part of Wave 1A.

## What he waits on from me
| He needs | For his | State |
|---|---|---|
| ENG-01: the engine's server address | DB-12 | Test server being set up (14 Oct); production later |
| ENG-06: the serving door | APP-15 | Works on dev → [[ENG-06 - Serve a recommendation list]] |
| ENG-08: the filters | APP-21 | Built |
| ENG-04: the sync | DB-16 | Built |
| ENG-21: the fraud case API | APP-17 | Not started |

## How this connects
- Who's who → [[People]].
- My side of the same work → [[Task Board]].
- The rules for both → [[The Pack]].
