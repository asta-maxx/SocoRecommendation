# Checklist run, 1 Oct 2026 (pack v1.3, ENG-01 to ENG-07)

`bash scripts/run_checklist.sh` on the laptop (dev), against Atlas: platform `soco`
(read-only) and the throwaway engine database `reco_demo` (dropped at the end).

| Run | Commit | Result |
|---|---|---|
| 1 | `082a299` | 51 passed, 2 failed: 4.1 and 4.3. Both printed all their tests passing (6 passed; 3 passed); the script expected 5 and 2, set before new tests joined those filters. |
| 2 | `3ea8f96` (expected counts fixed) | **53 passed, 0 failed** |

Sections: 0 (before you start) 4 · 1 ENG-01 6 · 2 ENG-02 9 · 3 ENG-03 5 · 4 ENG-04 11 ·
5 ENG-05 5 · 6 ENG-06 6 · 7 ENG-07 6 · Z clean-up 1.

Not checkable yet: test and production servers and clusters, production's read-only
login (DB-02), the private network (DB-12).
