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

## Run 3, after ENG-29 (1 Oct)

Commit `485fe77`: **62 passed, 0 failed** (section 8, ENG-29, lines 8.1–8.9, added; 4.10 now expects four sync sources).

## Run 4, after ENG-08 and the audit fixes (1 Oct)

Commit `42e539b`: **67 passed, 1 failed** of 68.

The one failure is 6.4, the product surface over HTTP. On dev every product is left out (E-07 x143, E-08 x857 per 1,000 read): the two import sellers have no `status`, and the engine counts that as not active until Aravinth answers question 17. So the rail is empty and the request reads the whole 1,000-row window (p95 about 350 ms from the laptop). It is a data question, not a code fault.

## Run 5, after the Windows changes (3 Oct)

Commit `72e8a5f`: **66 passed, 2 failed** of 68.

- 6.4 as before (products on dev wait on question 17).
- 6.3, the feed over HTTP, missed 200 ms: p95 257 ms, every record matched (19 of 19). The laptop's round trip to Atlas was 51 ms that day (22 ms on 1 Oct, when 6.3 passed at 127 ms); a feed request makes about five round trips. No serving code changed between the two runs. The pack's 200 ms check is "on test", next to the database.
