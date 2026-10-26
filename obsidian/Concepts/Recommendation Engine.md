---
tags: [concept]
---
# Recommendation Engine

This is **what I'm building**. The documents also call it "the service" or "the engine". They're all the same thing.

## What it does
When [[SOCO_BE]] asks *"what should this person see?"*, my engine answers with an ordered list of posts or products. It has to answer in **under 0.2 seconds**.

## How it stays fast
It works in **two modes** from the same code:
- **Night mode (jobs):** at 2 AM, it does all the heavy thinking and saves the results. For example: what everyone is interested in, and how good each promoter is.
- **Day mode (API):** when a request comes in, it only **looks up** those saved results, filters them, and puts them in order. No heavy maths.

> [!example] Like a restaurant: the kitchen does the prep overnight, so during service each dish is just assembled and plated.

## Where it keeps things
- It **reads** SOCO's data → [[Platform Database]] (never changes it).
- It **writes** its own data → [[Engine Database]].

## How this connects
- It's the heart of → [[Wave 1A]].
- It grew from → [[Before Wave 1A - the M1 demo]].
- Its home and databases were set up in → [[ENG-01 - Engine home and databases]].
