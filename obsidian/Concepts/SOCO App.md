---
tags: [concept]
---
# SOCO App

SOCO is a **social shopping app**. People post content, follow each other, and buy products, often *through* someone's post. Those people are called **promoters**, and they earn commission.

It has three parts:
- **The phone app** (built in Flutter): what users hold in their hands.
- **The backend** → [[SOCO_BE]]: the server the phone app talks to.
- **The database** → [[Platform Database]]: where all of SOCO's data is kept.

> [!note] The phone app **never** talks to my engine directly. It always goes through [[SOCO_BE]].

## How this connects
- The recommendations it shows come from → [[Recommendation Engine]].
- What's being built for it now → [[Wave 1A]].
