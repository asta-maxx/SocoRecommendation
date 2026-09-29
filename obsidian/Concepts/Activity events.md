---
tags: [concept]
---
# Activity events

An **event** is one small record of something a shopper did, or something the engine did:

| Event | Means |
|---|---|
| recommendation_request | The engine (or SOCO's backend) produced a list for someone |
| recommendation_impression | A shopper actually **saw** an item on that list |
| recommendation_click | A shopper **tapped** an item |
| add_to_cart | A product went into the cart |
| order_placed | An order was placed |
| order_state_changed | An order moved on (accepted, delivered, cancelled…) |
| social_interaction | Like, save, share, repost, follow, or their undo |
| content_feedback | "Not interested", hide, report, or mute |

Every event carries three things:
- **its own ID**, which is how duplicates are spotted;
- **its name** (one of the eight above);
- **who** did it.

## How events reach the engine
```
Shopper's phone → SOCO_BE (collects them) → the engine's front door → ml_events
```
SOCO's backend sends them in batches of up to 100, with a secret token. The engine checks each one, refuses bad ones with a reason, and never stores the same event twice. → [[SOCO_BE]], [[Secrets and passwords]]

> [!example] Like a post office with a numbered-receipt rule. Every letter has a unique number. If the same letter arrives twice (because the courier wasn't sure it got through), the second copy is recognised and set aside. Nothing is lost, and nothing is counted twice.

## How this connects
- The front door was built in → [[ENG-04 - Receiving activity events]]
- They're stored in the `ml_events` drawer → [[Collections]]
- They replace SOCO's old logs, day by day → [[Event source switch]]
