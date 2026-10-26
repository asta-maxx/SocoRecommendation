---
tags: [concept]
---
# Two methods per slot

Three parts of the engine (the **slots**) each have **two ways** of working (the **methods**). Both are built. Each user is given one of the two, so the methods can be compared on real people later (ENG-26).

| Slot | Model | Method one | Method two |
|---|---|---|---|
| `interest` | M1, what a user likes | recency decay | time windows |
| `product_ranking` | M5, "you might also like" | attribute similarity | bought together |
| `promoter_score` | M8, how good a promoter is | method one | method two |

## How a user is given a method
The engine takes the slot's name and the user's ID, for example `interest:65f1…`, and runs it through **SHA-256**. SHA-256 is a fixed recipe that turns any text into a long code, and the same text always gives the same code. The first 8 characters of that code become a number from 0 to 99: the user's **bucket**.

- Bucket **below the split** → method two.
- Everyone else → method one.

The split starts at **50** in every slot, so about half the users get each method. It's in the [[Settings file]], so changing it needs no new release.

> [!example] Like a coin that always lands the same way for the same name. Toss it for "Asha" a thousand times and it's heads every time. Toss it for "Ravi" and it might be tails every time.

## Why it's done this way
- **Same answer every time.** The user keeps their method across restarts, phones and days. Python's own `hash()` isn't used: it changes every time the program starts.
- **Slots don't move together.** The slot name is part of the text, so a user's method for interest says nothing about their method for product ranking.
- **Never a session or device ID.** Those change, so the user would flip between methods.
- **Recorded on every list.** The list's `policy_id` says which method each slot used, for example `cfg2.interest-recency_decay.promoter_score-shrinkage`. Methods are named, not numbered, so the history still reads correctly if the two methods ever swap places. That's how the two methods are compared later.

If the settings are missing (or a slot is left out of the settings file), everyone gets the **default** (method one) there and the fault is logged. The request still succeeds.

## How this connects
- Built in → [[ENG-05 - Same method for each user]].
- Every served list records it → [[Served list record]] ([[ENG-06 - Serve a recommendation list]]).
- The nightly jobs compute **both** methods for every user, so either can be served → [[Nightly batches]].
- The split and method names live in → [[Settings file]].
