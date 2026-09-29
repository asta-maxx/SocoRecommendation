---
tags: [concept]
---
# Event source switch

SOCO's app already records what people see and tap in some **old logs**: requests, impressions, clicks and feedback. Wave 1A moves all of that into the engine's **new log**, `ml_events` → [[Collections]].

For a while, the app writes to **both**. Then, once they agree, the old logs stop.

## The rule (from the pack)
- There's one **switch date**.
- **Before** it, those events are read from the old logs.
- **From** it onward, they're read from the new log.
- **Never both for the same day,** or everything would be counted twice.

> [!example] Like moving house. Letters before the moving day are at the old address, letters after it at the new one. You collect each letter once, from the right address, and none gets lost.

## Who sets the switch date
ENG-04 compares the old and new logs every day. When they agree for **7 days in a row**, that day becomes the switch date, and Aravinth stops writing the old logs. Until then, everything is read from the old logs.

## One place for everything else too
The same idea applies to all SOCO data: each kind is read from **exactly one place**. Orders come from orders; likes and views from the activity log; follows from follows. That way nothing is ever counted twice.

## How this connects
- Built in → [[ENG-03 - Reading SOCO's data correctly]] (the rule)
- The date comes from → ENG-04 (the new log and the daily comparison)
- The old logs live in → [[Platform Database]]; the new one in → [[Engine Database]]
