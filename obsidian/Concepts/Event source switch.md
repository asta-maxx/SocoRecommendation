---
tags: [concept, retired]
---
# Event source switch

> [!warning] Retired in pack v1.3 (29 Sep 2026, received 1 Oct). There is no event source switch any more. This note stays so old links still lead somewhere.

## What it used to mean
Under the 22 Sep pack, SOCO's app kept some **old logs** (requests, impressions, clicks and feedback), and the app was going to send the same events to the engine's **new log**, `ml_events`.

For a while both would run side by side. A daily comparison would pick one **switch date**: before it, events were read from the old logs; from it onward, from the new log. Never both for the same day, or everything would be counted twice.

> [!example] Like moving house: letters before moving day at the old address, letters after it at the new one, each collected once.

## Why it went
In v1.3 the engine no longer receives events at all. The app writes every event to SOCO's own activity log (`postevents`), and the engine copies that log. With one log there is nothing to switch between.

The older logs don't disappear by themselves, though. Before the engine's first full copy, Aravinth's production migration (**DB-16**) moves them into `postevents`. Only after the engine's daily check has passed **7 days in a row** are the old logs dropped.

## What replaced it
- **One source for events:** the engine reads events only from its own copy of `postevents`, never from SOCO's database directly → [[ENG-03 - Reading SOCO's data correctly]]
- **The copying itself:** a full first copy, then a fresh read every 5 minutes, checked every day → [[Engine sync]], built in [[ENG-04 - Engine sync]]

## One place for everything else, still
The old idea survives in one form: each kind of SOCO data is read from **exactly one place**. Events come from the engine's copy of `postevents`; orders from the engine's copy of `orders`; follows from `follows`. That way nothing is ever counted twice.

## How this connects
- Retired by → [[The Pack]] (v1.3)
- The one-source rule now lives in → [[ENG-03 - Reading SOCO's data correctly]]
- What took its place → [[Engine sync]] and [[ENG-04 - Engine sync]]
- What the events are → [[Activity events]]
