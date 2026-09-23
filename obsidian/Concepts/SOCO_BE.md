---
tags: [concept]
---
# SOCO_BE (the app's backend)

**SOCO_BE** is the server behind the [[SOCO App]]. Aravinth looks after it (→ [[People]]).

Think of it as the **middleman**:

```
Phone app  →  SOCO_BE  →  my Recommendation Engine
```

## What it does with my engine
- **Asks for lists:** "Give me the feed for this user." It waits at most a quarter of a second. If I'm too slow or down, it shows its own older list instead, so users never see an error.
- **Passes on activity:** what users viewed, clicked and liked. It collects these and forwards them to me in batches.
- **Shows my list exactly as I send it:** no reordering and no trimming.

## Where it lives
In a private network. My engine must sit in the **same** private network so the two can talk, while nothing on the public internet can reach my engine.

## How this connects
- It talks to → [[Recommendation Engine]].
- Its data lives in → [[Platform Database]].
- Putting my engine next to it is part of → [[ENG-01 - Engine home and databases]].
