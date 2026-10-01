---
tags: [concept]
---
# Settings file

The engine uses lots of **numbers**: how much a "like" counts, how fast old activity fades, how many items to consider, when to raise a fraud flag. The pack lists every one of them, with a starting value and an allowed range, on the Build List's **Settings sheet**.

Since pack v1.3 it also holds:
- **Surface modes:** for the feed and for product pages, each is `off`, `internal` (engine lists only for the test accounts, for checks before launch) or `live`. Both start `off`.
- **The engine sync's timings:** a read every 5 minutes, a 2-minute overlap, an alert when more than 15 minutes behind → [[Engine sync]].
- **Lists:** the category map, status spellings, the words that mark each step of an order's history ("Delivered…", "Cancelled by seller"), exemptions and test accounts. Each account entry says why, who changed it and when it expires → [[ENG-29 - Adapting to the platform as built]].

## The rules for it (from the pack)
- **One file** holds every one of those numbers, and nothing else. Passwords never go in it → [[Secrets and passwords]].
- **It has a version number,** so every list the engine serves can say which settings produced it.
- **It reloads itself** at least once a minute. Change a number, and within a minute the engine uses it, with no restart.
- **A broken file can't crash the engine.** It keeps using the last good version and logs the fault → [[Logs]].
- **If there has never been a good version,** the engine uses the pack's default values.
- **Every change is written down:** when, the old value, the new value, and who changed it. That diary is the `ml_config_changes` drawer → [[Collections]].

> [!example] Like a thermostat you can turn without switching the heating off. If someone scribbles nonsense on the dial, it keeps the last sensible setting.

## How to change a number
1. Open `settings/engine.toml` and change the number. Stay inside the range written next to it.
2. Raise `config_version` by one, and put your name in `changed_by`.
3. Save. Within about 30 seconds the engine uses the new number, and the change is written in its diary.

If you forget step 2, or type something invalid, nothing breaks. The engine refuses the file and keeps the last good settings.

## Status
Built in parts 3 and 4 of → [[ENG-02 - Service skeleton and settings]]. Checked live: a change took effect in 29 seconds.

## How this connects
- Part of the config area of the → [[Recommendation Engine]].
- Its values come from → [[The Pack]].
