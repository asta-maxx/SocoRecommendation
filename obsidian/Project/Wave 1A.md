---
tags: [project]
---
# Wave 1A

**In one line:** the first real version of SOCO's recommendations. It decides which posts and products each shopper sees, and in what order.

## Where shoppers will see it
- **The For You feed:** the home screen's main scrolling list of posts.
- **Product pages and the cart:** "you might also like" lists.

## What else it does, behind the scenes
- **Scores promoters:** people who sell through their posts get a quality score. It helps order the feed but is never shown.
- **Scores opportunities:** which products suit which promoter. Computed, but not shown yet. 
- **Spots possible fraud:** flags suspicious activity for a *person* to review. Nothing is ever punished automatically.

## What it does *not* promise
Great recommendations from day one. There's no real user activity yet, so at first it will mostly show "recent and popular". It gets smarter as people use the app.

## Rules that never bend
- My engine never changes SOCO's own data. See [[Platform Database]].
- Commission (how much a seller pays) never affects what a shopper sees.
- A person always makes the final call on fraud.
- Nothing is recorded while a user is in incognito mode.
- The app shows my list exactly as I send it.

## How this connects
- It grew out of → [[Before Wave 1A - the M1 demo]], which built one piece of it.
- Its exact rules are in → [[The Pack]].
- The piece I build is → [[Recommendation Engine]].
- The work happens in → [[Build Steps]].
