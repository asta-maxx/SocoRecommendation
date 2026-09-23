---
tags: [concept]
---
# Settings file

The engine uses lots of **numbers**: how much a "like" counts, how fast old activity fades, how many items to consider, when to raise a fraud flag. The pack lists every one of them, with a starting value and an allowed range, on the Build List's **Settings sheet**.

## The rules for it (from the pack)
- **One file** holds every one of those numbers, and nothing else. Passwords never go in it → [[Secrets and passwords]].
- **It has a version number,** so every list the engine serves can say which settings produced it.
- **It reloads itself** at least once a minute. Change a number, and within a minute the engine uses it, with no restart.
- **A broken file can't crash the engine.** It keeps using the last good version and logs the fault → [[Logs]].
- **If there has never been a good version,** the engine uses the pack's default values.
- **Every change is written down:** when, the old value, the new value, and who changed it. That diary is the `ml_config_changes` drawer → [[Collections]].

> [!example] Like a thermostat you can turn without switching the heating off. If someone scribbles nonsense on the dial, it keeps the last sensible setting.

## Status
Being built as parts 3 and 4 of → [[ENG-02 - Service skeleton and settings]].

## How this connects
- Part of the config area of the → [[Recommendation Engine]].
- Its values come from → [[The Pack]].
