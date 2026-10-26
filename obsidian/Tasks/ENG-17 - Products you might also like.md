---
tags: [task, step-3]
task: ENG-17
status: Built
owner: Allen
---
# ENG-17: Products you might also like (M5)

> [!note] Status: **Built** (17 Oct 2026, on my laptop)
> Works and is tested, including on a real database and on SOCO's dev data (263 product lists). Becomes **Passed** when both methods are shown serving on the test server.

**In one line:** when someone looks at a product (or their cart), show other products they might like, worked out two different ways, and never show the product they're looking at or anything already in their cart.

## Why this task
The product page and the cart get their "you might also like" rail from the engine. Until now the engine served a stand-in there (newest products first). The checks in ENG-22 and the launch tests in ENG-23 need the real thing. → [[Build Steps]]

> [!example] The idea in one picture
> **Method one** is a shop assistant who looks at what you're holding and fetches things like it: same kind of product, a similar price, the same shop, things popular right now, and anything the seller said goes with it.
> **Method two** is the till receipt: "people who bought this also bought that", counted over many baskets.

## What came before
- [[ENG-05 - Same method for each user]]: each shopper is given method one or method two, the same one every time.
- [[ENG-07 - Nightly jobs]]: the lists are worked out at night and swapped in whole.
- [[ENG-08 - Filters]]: the rules that keep out blocked, hidden or out-of-stock items.
- [[ENG-06 - Serve a recommendation list]]: the door SOCO asks for a list, which until now served newest products first on this rail.

## Subtasks, one by one

### 1. Method one: products like this one ✅
- **What it asks:** score every product that can be bought on five things: same category (35%), on the seller's "goes with" list (20%), a price within 30% either way (15%), popular in the last 30 days (20%), same seller (10%). No star ratings (there are none). If a thing can't be worked out for a product, leave it out and share its weight among the others.
- **What we did:** exactly that, every night, for every product: its 100 best matches are stored. "Popular" counts clicks on the product plus add-to-carts, turned into a rank from 0 to 1 among all products.
- **Why it matters:** this list exists for every product from day one, so nobody ever sees an empty rail.
- **Status:** done. On dev: 263 products, each with a list. (No seller has filled in a "goes with" list yet, so that part is always left out for now.) → [[Two methods per slot]]

### 2. Method two: bought together ✅ (over carts for now)
- **What it asks:** "lift": how much more often two products are bought together than chance would predict. Pull rarely seen pairs toward "nothing special" (the adjusted lift, with strength 10), and ignore any pair bought together fewer than 2 times. Until SOCO's basket test passes (APP-22), use what's in people's carts instead, and call it "intent".
- **What we did:** exactly that. A basket is one person's cart for now; once APP-22 passes, one setting switches it to real checkouts (orders sharing a checkout number), with cancelled and rejected orders left out. Incognito orders count in the totals, but no buyer is ever named or stored.
- **Why it matters:** this is the method that can find surprising pairs (a phone and its case) that method one can't.
- **Status:** done. On dev: 51 carts, only 1 pair seen twice or more, so 2 products have a list. Checkouts on dev have no pair seen twice yet. → [[Nightly batches]]

### 3. When method two has nothing: the back-up order ✅
- **What it asks:** if there's no pair for a product (true for most at launch), fall back: 1. method one's list; 2. popular products in the same top-level category; 3. newest products. Record which step was used. Never an empty list.
- **What we did:** a list is filled from those sources in that order until it's full, and the step used is written on the list and on its receipt.
- **Why it matters:** shoppers on method two still see a full rail, and we can tell afterwards which lists were "real" method two and which were back-ups, so the comparison stays fair.
- **Status:** done. On dev, a method-two shopper gets a full list, marked "step 1". → [[Served list record]]

### 4. Never the product being viewed, never what's in the cart ✅
- **What it asks:** leave out the product on screen, and on the cart every product already in it.
- **What we did:** every list leaves out the product being viewed and everything in the shopper's cart (the engine reads the cart itself, as Kala answered on 16 Oct), at every step of the back-up order.
- **Why it matters:** recommending what you're already looking at, or already buying, wastes the slot.
- **Status:** done, tested on every step. → [[ENG-08 - Filters]]

### 5. Stored every night, read on request, exactly the right length ✅
- **What it asks:** write both methods every night; a request reads the list for the shopper's method, applies the filters, and returns exactly the number asked for (fewer only when there aren't enough suitable products).
- **What we did:** each method is saved as its own complete batch each night (like the other models), and a request reads only the finished batch. A batch more than 48 hours old isn't trusted: the back-up order takes over. Every product is checked against the filters before it gets a place, and the page is checked once more just before it goes out.
- **Why it matters:** a request never calculates anything, so the rail stays fast; a broken night leaves yesterday's lists in use.
- **Status:** done. On dev, both methods returned full lists of 10. → [[Nightly batches]]

### A. Wired into the product rail ✅
- **What we did:** the product rail now serves these lists instead of the stand-in. The home feed is unchanged.
- **Status:** done. → [[ENG-06 - Serve a recommendation list]]

## Result (17 Oct 2026)
- 28 automatic checks pass (27 quick ones and one on a real database), including the pack's own check: the "lift" for three pairs worked out by hand matches.
- On SOCO's dev data: 247 products can be sold; 263 method-one lists; 2 method-two lists from carts. Requests on both methods returned full lists that never included the product being viewed.

## Decided
- **17 Oct 2026:** "same category" in method one means the product's own (most specific) category; the back-up's step 2 uses the top-level one.
- **17 Oct 2026:** an empty "goes with" list is treated as missing, so its weight is shared out.
- **17 Oct 2026:** for now a basket is one person's cart; test accounts don't count.
- **17 Oct 2026:** a list that's too short is topped up from the back-up steps, so it's always full when enough products exist; the step recorded is the first back-up used (`product_step_1`, `_2` or `_3`), and none when the method's own list was enough.
- **17 Oct 2026:** each product keeps its best 100; each category its 200 most popular.

## Still to do
| What | Waiting on |
|---|---|
| Switch method two from carts to real checkouts | APP-22, the basket test (Aravinth) |
| Show both methods serving on the test server | The test server → [[Environments]] |
| Kala and Nisha to confirm the choices above | Kala, Nisha → [[People]] |
| The full check script | ENG-22 |

## How this connects
- **Before it:** [[ENG-16 - Promoter score]]
- **Built on:** [[ENG-05 - Same method for each user]], [[ENG-07 - Nightly jobs]], [[ENG-08 - Filters]], [[Nightly batches]]
- **Next:** ENG-19, ordering the feed (the last ranking piece; the product rail is now done).
- **Technical version:** `docs/engineering/ENG-17.md` in the repo.
