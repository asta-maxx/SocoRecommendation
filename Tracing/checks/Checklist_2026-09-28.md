# Full checklist run: 28 Sep 2026, dev (laptop)

Every item on the ENG-01 / ENG-02 checklist, run in order. **Result: all pass.**
Two documentation mismatches were found and fixed in the same run (see the end).

## 0. Before you start
| Check | Result |
|---|---|
| Branch | `wave1a/foundations`, clean, in step with `origin` |
| Unit tests | **432 passed**, 1 skipped |
| Database tests (Atlas build cluster) | **31 passed** (cluster awake) |

## 1. ENG-01
| Check | Result |
|---|---|
| Environment, own database, 12 collections (`setup_engine_db.py`) | `dev`; engine `SoCo` on `soco.4b7z1ko`, platform `soco` on `nex-dev.cob9whd` (different clusters); **12 of 12**; platform ping ok; exit 0 |
| Platform login read-only (`check_platform_access.py`) | `SocoReadonly@admin`; write actions **NONE**; users, posts, postevents, orders, follows, products all readable; exit 0 |
| Safety lock | Refused: "the engine database ('soco') is the platform database … (AS-09, SD-06)" |
| No secrets | `.env` ignored by git; no connection string with a password in tracked files (**none found**, after the fix below); production from `.env` refused (SD-08) |

## 2. ENG-02 (throwaway settings copy, throwaway database `reco_demo`)
| Check | Result |
|---|---|
| 12 modules; gatekeepers | 12 module folders; layout tests **16 passed** |
| Jobs mode | `interest` |
| Health, all well | **HTTP 200**, `ok`, `dev`, both databases true |
| Health, engine database unreachable | **HTTP 503**, `unavailable`, `ml: false` |
| Request log | JSON line: `reco.request`, `/health`, status 200, 43.2 ms |
| Setting change | In force after **19 s** (limit 60 s); logged: version 2, by "Checklist", `interest.popularity_window_days`, recorded |
| Change diary | `version 1 -> 2 by Checklist`, `interest.popularity_window_days: 30 -> 45` |
| Broken file | ERROR "settings file rejected; keeping the settings in force", version 2 still in force; health still **200** |
| Change without a new version | Rejected: "values changed but config_version is still '2': raise config_version for every change" |
| Clean up | `reco_demo` dropped; no engine process left running |

## Fixed during this run
1. **Demo – ENG-01, step 4.** Its example addresses carried a fake password (`reader:hidden@…`). The secrets search in step 5 then found them, contradicting "none found". The example now has no password at all. The safety lock still refuses it, and the search is clean.
2. **Demo – ENG-02, step 1.** `ls reco` also shows `__init__.py`, `main.py` and `__pycache__`. The note now says so.

## Not checkable yet
Test and production servers and clusters, production's own read-only login
(DB-02), the private network and address handover (DB-12). All wait on
Aravinth.
