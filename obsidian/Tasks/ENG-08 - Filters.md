---
tags: [task, step-2]
task: ENG-08
status: Passed
owner: Allen
---
# ENG-08: Filters

> [!note] Status: **Built** (1 Oct 2026, on dev)
> All twelve rules work, every item left out is written in the log with its rule, and each list is checked once more just before it goes out. Two rules wait on answers from **Aravinth**: how SOCO stores a block (E-01), and whether an account with no status counts as active (E-08). The 15-minute "current state" from ENG-27 comes later. It becomes **Passed** once the checks run on the test server.

> [!success] Passed (16 Oct 2026)
> Kala: this task's check names no environment, so the run on my laptop is the evidence. One item left out and one kept per rule, on dev (1 Oct; re-run 15 Oct). On 16 Oct the block rule and the 'active person' rule were corrected to the app's real fields. It covers this task's own check, not the later ENG-30 changes. → [[Answers 16 Oct]]

> [!tip] Pack v1.4 (15 Oct 2026)
> The spelling list got its first entry: "Activated" reads as "Activate", so a product and a product post both count as active whichever word SOCO stored. New tests show the "pushed down or removed" rule (E-12) still serves posts marked ok, review, fix requested, or with no mark at all.

**In one line:** before any list leaves the engine, twelve fixed rules take out anything this person must not see: people they blocked or muted, hidden or private posts, things that can't be bought, their own posts, adult content for under-18s, and posts SOCO has pushed down or removed.

## Why this task
SOCO's backend shows the engine's lists **exactly as returned**, with no filtering of its own (API Contract, section 4.3). So the engine alone is responsible for never showing something it shouldn't. These rules sit above every model: no score, however high, can bring an item back. The product ranker (ENG-17), finding candidate posts (ENG-13), keeping eligibility current (ENG-27) and Aravinth's blocking test (APP-21) all wait on it. → [[Build Steps]]

> [!example] The idea in one picture
> A bouncer at a club door with a printed list of twelve reasons to turn someone away. It doesn't matter how good the DJ thinks they'd be for the party: on the list means not in. The bouncer writes down every person turned away and the reason number. And just before the doors open, he looks over the guest list one last time, in case someone was barred in the last few minutes.

## What came before
- [[ENG-03 - Reading SOCO's data correctly]] taught the engine to read SOCO's posts, products, accounts and follows, comparing statuses ignoring case. Every rule here reads through those readers. → [[Platform Database]]
- [[ENG-29 - Adapting to the platform as built]] added the spelling list ("Activate" vs "Activated"), the rule that a post card showing a product keeps its post id, and the made-up SOCO data the tests run on.
- [[ENG-04 - Engine sync]] copies SOCO's activity into the engine. The "mute", "not interested", "hide" and "report" taps are read from that copy. → [[Engine sync]], [[Activity events]]
- [[ENG-06 - Serve a recommendation list]] built the serving door with a **stand-in** safety check (public, not hidden, in stock). This task replaces it with the full set of twelve rules.

## Subtasks, one by one
The Build List gives twelve rules (1–12, one per rule E-01 to E-12), then four more parts (13–16). There are two extras (A–B).

Each item is tested against the rules in order, and the **first** rule it breaks is the one written down. One item, one reason.

### 1. E-01: Blocked, either way ✅ built / ⏳ waiting on how SOCO stores a block
- **What it asks:** if the author blocked me, or I blocked the author, I never see their posts or products. This applies to personal and business accounts, and it's read from SOCO fresh for every list, so a block works on the very next list.
- **What we did:** each time a list is built, the engine looks up every block row touching me (or any business I own) in SOCO's `followers` collection (where SOCO marks a block with the status "blocked"). Whoever is on the other side of each row goes on my "blocked" list, in both directions.
- **Why it matters:** seeing someone you blocked is the worst thing a feed can do. It's also Aravinth's acceptance test 3 (APP-21).
- **Status:** built and tested. But SOCO's `followers` is **empty on dev** and nobody has written down which field is the blocker and which is the blocked person. I assumed one shape; question 16 to Aravinth asks for the real one. If it differs, it's a small change in one place. → [[Platform Database]]

### 2. E-02: Muted author ✅
- **What it asks:** if I muted an author, I never see their things.
- **What we did:** the engine reads my "mute author" taps from its own copy of SOCO's activity. A mute names the author directly; if it was recorded against a post, the engine looks up who wrote that post and mutes them. A mute I later undid doesn't count. Mutes have **no time limit**: one from a year ago still applies.
- **Why it matters:** a mute is a clear "not this person", and should last.
- **Status:** done. Tested with a mute named directly, one made on a post, a year-old one and an undone one. → [[Activity events]]

### 3. E-03: Not interested, Hide or Report, last 90 days ✅
- **What it asks:** if I tapped Not interested, Hide or Report on an item in the last 90 days, I don't see it again.
- **What we did:** the same copy of my taps gives a "dismissed" list of posts and products. The 90 days is a setting (fixed for Wave 1A). The tap names its target the way SOCO's app sends it (the target's id and whether it's a post, product or author).
- **Why it matters:** if someone said "not this" and sees it again, they stop trusting the feed.
- **Status:** done. Tested: a 91-day-old Hide no longer applies. → [[Settings file]]

### 4. E-04: Hidden or not public ✅
- **What it asks:** never show a post that is hidden or isn't public.
- **What we did:** a post marked hidden, or whose visibility isn't "public", is left out.
- **Why it matters:** the author (or SOCO) chose not to show it to everyone.
- **Status:** done.

### 5. E-05: Private account I don't follow ✅
- **What it asks:** if the author's account is private and I don't follow them, I don't see their posts.
- **What we did:** the engine reads who I follow when the list is built. A post by a private account I don't follow is left out. My own private posts aren't caught here; rule 10 handles those.
- **Why it matters:** private means "followers only".
- **Status:** done. **On SOCO's dev data, this is the rule that leaves out 5 of the 8 posts** for a made-up viewer who follows nobody.

### 6. E-06: Product post that isn't Activated ✅
- **What it asks:** a post selling a product shows only if its product status is "Activated". "N/A" is fine: it means the post has no product.
- **What we did:** exactly that. Where the status is missing altogether, the post passes only if it doesn't carry a product. (The pack doesn't say; a post with a product but no status isn't "Activated", so it's left out.)
- **Why it matters:** a post pointing to a product that SOCO switched off leads to a dead end.
- **Status:** done.

### 7. E-07: A product you can't buy ✅
- **What it asks:** a product shows only if it's switched on ("Activate"), marked in stock, and at least one of its active variants (sizes, colours) has stock left after what's already reserved in baskets.
- **What we did:** exactly those three checks. The engine reads the variants only for products that passed everything else, to save time. It also applies this to **feed posts showing a product**: if the product can't be bought, the post is left out too, because the pack says out-of-stock products are never shown.
- **Why it matters:** recommending something you can't buy is frustrating, and wastes a slot.
- **Status:** done. **On dev, 143 of the newest 1,000 products fail this** (marked out of stock).

### 8. E-08: Author or seller not active ✅ built / ⏳ waiting on what "no status" means
- **What it asks:** the author or seller's account must be active.
- **What we did:** an account whose status isn't "active" (ignoring case) is left out, along with everything it posts or sells. An account the engine can't find at all counts as not active. So does an account with **no status written**: the pack doesn't say, so I chose the safe reading.
- **Why it matters:** a closed or switched-off account shouldn't keep selling through recommendations.
- **Status:** built. But on dev, the two big import sellers (2,006 of SOCO's 2,011 products) have **no status at all**, so today **no product on dev can be served**. Question 17 to Aravinth: does a missing status mean active? If yes, it's a one-line change.

> [!warning] Why the product rail is empty on dev
> It isn't a bug in the rules. SOCO's import sellers simply have no status written, and the engine won't guess "active" for them. Aravinth's answer decides it.

### 9. E-09: Suspended or removed ✅ built / ⏳ switches on with DB-08
- **What it asks:** if an author is suspended or removed (a fraud penalty), hide their things. The field that records this (`restriction_level`) comes with Aravinth's DB-08.
- **What we did:** the engine already reads that field. Today it doesn't exist, so nothing is left out. The day DB-08 adds it, "suspended" and "removed" start excluding, with no change on my side. "Warning" and "restricted" don't hide anything.
- **Why it matters:** a penalty has to show in what people see.
- **Status:** ready; waiting on DB-08, which comes only once SOCO names its fraud reviewers.

### 10. E-10: My own things ✅
- **What it asks:** don't recommend me my own posts or products.
- **What we did:** "me" means my personal account **and** every business account I own. Anything posted or sold by any of them is left out.
- **Why it matters:** your own post in your For You feed is a wasted slot.
- **Status:** done.

### 11. E-11: Adult-only content and under-18s ✅ (nothing to exclude today)
- **What it asks:** posts marked adult-only aren't shown to people under 18, worked out from their date of birth, or to people with no date of birth. Today every post is marked "All".
- **What we did:** exactly that. The pack doesn't say what an adult-only mark looks like, so **any** mark other than "All" (or blank) is treated as adult-only. That way, the day a new value appears, it's kept from minors first and questioned after.
- **Why it matters:** protecting minors is non-negotiable, even before the content exists.
- **Status:** done; no post triggers it today. (The pack also says: no region rule in Wave 1A, since every product ships all over India.)

### 12. E-12: Pushed down or removed by SOCO ✅
- **What it asks:** a post SOCO's moderation "deranked" or "removed" never shows. One "under review" shows as normal.
- **What we did:** exactly that.
- **Why it matters:** moderation decisions must hold everywhere, not just in SOCO's own feed.
- **Status:** done.

### 13. Write down every item left out ✅
- **What it asks:** each exclusion is logged with the list's ID, the item's ID and the rule number.
- **What we did:** one log line per item left out, with the list ID (`request_id`), the item ID, whether it's a post or product, and the rule. The engine also stopped pre-sorting items inside the database query, which used to drop hidden and out-of-stock items before the rules ever saw them, so those were never written down. Now **every** item goes through the rules, so **every** exclusion is logged.
- **Why it matters:** when someone asks "why didn't my post show up for her?", the answer is one search in the log.
- **Status:** done. Tested: every post is either kept or logged, none disappears silently. → [[Logs]]

### 14. Before scoring, and again on the final list ✅ final list / ⏳ before scoring
- **What it asks:** apply the rules both before items are scored and on the finished list. No model can override them.
- **What we did:** every list served now goes through the rules, and the page is checked again just before it leaves (part 16). Nothing after the rules can add an item back. The overnight jobs that will score items (the interest score, finding candidate posts, the product ranker) will call the very same rules on their candidates.
- **Why it matters:** filtering early saves scoring things that can never be shown; filtering at the end is the safety net.
- **Status:** on the served list, done. "Before scoring": the product ranker's overnight job now scores only products that can be bought (17 Oct → [[ENG-17 - Products you might also like]]); ENG-13 is still to come. → [[Nightly batches]]

### 15. Use the engine's 15-minute snapshot ⏳ ENG-27
- **What it asks:** rules 4 to 9 and 12 read the current state of posts, accounts and products that ENG-27 keeps, refreshed every 15 minutes.
- **What we did:** ENG-27 isn't built, so for now these rules read **SOCO directly** for the items in hand. That's even more up to date, just slower.
- **Why it matters:** ENG-27 makes it faster and lighter on SOCO's database, without letting a list drift more than 15 minutes behind.
- **Status:** waiting on ENG-27.

### 16. One last check before the list goes out ✅
- **What it asks:** just before returning a list, re-read its items on SOCO (one read per list) for blocks, visibility and stock. Anything that now fails is replaced by the next eligible item.
- **What we did:** the engine builds one extra page of eligible items as spares. Just before answering, it re-reads the page's posts or products from SOCO. Anything that changed in those few milliseconds (hidden, sold out) is dropped, written in the log, and the next spare takes its place.
- **Why it matters:** SOCO shows the list as-is, so this is the last chance to catch a late change.
- **Status:** done. Tested: a post hidden after the list was built is swapped for the next one. → [[Served list record]]

### A. Extra: making it fast enough ✅
- **What we did:** with every rule reading SOCO, one list now needs several reads, and SOCO's backend waits at most a quarter of a second. So:
  - **Upgraded the database library** (PyMongo, from 4.10.1 to 4.18.2). The old version ran "parallel" reads one after another: five quick pings took about 110 ms, against about 25 ms on the new one.
  - Kept 10 database connections **open and warmed up** from start-up, so no request waits to open one.
  - Read **only the fields the rules need** (product records carry images and specifications, which are most of their size).
  - Read each author or seller **once per list**, however many of their items appear.
  - Look at **no more than 1,000** posts or products per list. (The pack sets no limit; without one, a surface where nothing qualifies would read all of SOCO every time.)
- **Why it matters:** a safe list that arrives too late is never shown.
- **Status:** done. **Measured 1 Oct from my laptop over the internet:** feed lists in **127 ms** for 95 in 100 requests. The official 200 ms check is on the test server (ENG-20).

### B. Extra: a window onto the rules ✅
- **What we did:** a script (`show_exclusions.py`) that builds the first feed page and the first product page on SOCO's real data, like the engine does, without serving or recording anything, and counts how many items each rule left out. It shows counts and rule names, never IDs.
- **Why it matters:** one command tells me which rule is emptying a surface.
- **Status:** done. **Real run, 1 Oct:** feed 3 eligible of 8 read (E-05 ×5); product 0 eligible of 1,000 read (E-07 ×143, E-08 ×857).

## Result (1 Oct 2026)
- All twelve rules work, each with a test that leaves one item out and keeps one: the Build List's check. **17 passed** in the filters' own tests (4 of them against a database). The whole test suite: **634 passed, 1 skipped**.
- Every item left out is written in the log with its list, item and rule.
- The last-moment check before a list goes out works, and swaps in the next item.
- On SOCO's real dev data: the feed serves 3 of its 8 posts to a stranger; the product rail is empty until question 17 is answered.

## Decided
| Date | Decision | Why |
|---|---|---|
| 1 Oct 2026 | Report the **first** rule an item breaks, in number order | One clear reason per item in the log |
| 1 Oct 2026 | A block row is read as "userId blocked followerId" | `followers` is empty on dev and its fields aren't documented (question 16) |
| 1 Oct 2026 | An account with no status, or not found, is **not** active | The pack doesn't say; safe choice (question 17) |
| 1 Oct 2026 | A post with a product but no product status is left out | Only 'Activated' or 'N/A' pass |
| 1 Oct 2026 | Any age mark other than "All" counts as adult-only | Protect minors first when a new value appears |
| 1 Oct 2026 | Mutes never expire; Not interested / Hide / Report last 90 days | The pack gives only the second a window |
| 1 Oct 2026 | A feed post showing an unbuyable product is left out | "Out-of-stock products are never shown" (API Contract 4.5) |
| 1 Oct 2026 | No pre-sorting in the database | So every exclusion is logged |
| 1 Oct 2026 | Read at most 1,000 items per list | The pack sets no limit; a list must stay fast |
| 1 Oct 2026 | Upgrade PyMongo to 4.18.2 | The old version didn't run reads in parallel |

## Still to do
| What | Waiting on |
|---|---|
| The real field names of a block (E-01) | Aravinth, question 16 → [[People]] |
| Does "no status" mean active? (E-08; empties the product rail on dev) | Aravinth, question 17 |
| Suspended and removed accounts (E-09) start being hidden | Aravinth's DB-08 |
| Read rules 4–9 and 12 from the 15-minute snapshot | ENG-27 |
| Apply the rules before scoring in the overnight jobs | ENG-10, ENG-13, ENG-17 |
| Blocking tested end to end in the app, both ways | Aravinth's APP-21 test 3 |
| Run the checks on the **test** server, then mark Passed | The test server ([[ENG-01 - Engine home and databases]]) → [[Environments]] |

## How this connects
- **Before it:** [[ENG-29 - Adapting to the platform as built]]
- **Built on:** [[ENG-03 - Reading SOCO's data correctly]], [[ENG-04 - Engine sync]], [[ENG-06 - Serve a recommendation list]], [[Platform Database]], [[Activity events]], [[Logs]], [[Settings file]], [[SOCO_BE]]
- **Next:** [[ENG-09 - Fallback ladder]]. It decides what a new or quiet user is shown when the models have little to go on, and every list it builds goes through these filters.
- **Demo:** [[Demo - ENG-08]]. How to show each rule leaving one item out and keeping one.
- **Technical version:** `docs/engineering/ENG-08.md` in the repo.
