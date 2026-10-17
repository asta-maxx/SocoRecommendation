---
tags: [task, step-3]
task: ENG-14
status: Built
owner: Allen
---
# ENG-14: Similar posts

> [!note] Status: **Built** (16 Oct 2026, on my laptop)
> Every night the engine now works out, for each person, the 200 recent posts most like the ones they enjoyed, and stores that list. A request only reads it. The job finishes, in the tests and on dev. Reading one list takes the database 0 ms; from my laptop the network adds about 50 ms, so the official "20 ms" timing waits for a server next to the database.

**In one line:** every night, describe each post as a short list of numbers, describe each person the same way from what they liked, and store the 200 posts closest to each person.

## Why this task
The feed finds posts in two ways (step 3, "M2 retrieval"). Method one ([[ENG-13 - Quotas]]) gathers posts from your categories, the people you follow, and what's trending. Method two, this task, finds posts that *look like* the ones you already engaged with. [[ENG-15 - Merge the shortlist]] puts the two together for every person. → [[Build Steps]]

> [!example] The idea in one picture
> Give every post a fingerprint: which categories it's in, whether it's a photo or a video, and how new it is. Mix the fingerprints of the posts you liked into one "taste" fingerprint, giving more say to strong actions (an add-to-cart more than a like) and to recent ones. Then line up all recent posts by how closely their fingerprint matches yours, and keep the top 200.

## What came before
- [[ENG-07 - Nightly jobs]] runs work at 2 AM as "finish first, then swap", so nobody ever reads a half-made list. This job is one more of those. → [[Nightly batches]]
- [[ENG-10 - Interest score on real data]] set the weight of each action (like 3, add to cart 10…) and the rule that old actions fade by half every 30 days. This task reuses both.
- [[ENG-04 - Engine sync]] copies what people do on SOCO into the engine. The "taste" is read from that copy. → [[Activity events]]
- [[ENG-08 - Filters]] holds the rules for what may be shown. This task uses the ones about the post itself.

## Subtasks, one by one
The Build List row's parts (1–4), in its order, then the extras.

### 1. A fingerprint for each recent post ✅
- **What it asks:** take posts from the last 30 days (at most the 5,000 newest that may be shown). Give each one a list of numbers: one per category (split evenly if it's in several), one per post type, and a small one for age that can never outweigh the rest. Then scale it so every post's list has the same overall size.
- **What we did:** exactly that. A post's type is its detailed type if SOCO filled it in, otherwise its plain type; empty means "normal"; anything not on the list in the [[Settings file]] (photo, video, normal, other) counts as "other" and is reported in the night's log. Posts that can never be shown are left out: hidden or not public, deranked or removed, reposts (the original is used instead), seed posts (test data), and posts by accounts that aren't active.
- **Why it matters:** the fingerprints are what make "similar" measurable. Leaving out posts nobody may see keeps all 200 places useful.
- **Status:** done. On dev there are no posts from the last 30 days (the newest is from 8 Sep), so tonight's pool is empty there.

→ [[Settings file]]

### 2. A taste fingerprint for each person ✅
- **What it asks:** average the fingerprints of the person's last 50 engaged posts, weighting each by the action weights and the 30-day fading, and scale the result the same way.
- **What we did:** "engaged" means a proper view (3 seconds or more), a click, like, save, comment, share or add-to-cart. Each post's say is the sum of its actions' weights, faded by age. Never counted: "not interested" and "hide", posts just scrolled past, undone likes, likes on your own posts, seed posts, and test accounts.
- **Why it matters:** this is the person's taste in the same "language" as the posts, so the two can be compared directly.
- **Status:** done. On dev, 3 people have engaged posts; 1 has fewer than 3.

→ [[Activity events]]

### 3. Store each person's top 200 ✅
- **What it asks:** compare each person's taste with every post in the pool, keep the 200 closest, and store them with the run's id and the model version. Fewer than 3 engaged posts: no list.
- **What we did:** each match gets a score from 0 (nothing in common) to 1 (identical). Equal scores put the newer post first. The 200 rows go into the engine's candidates drawer as one complete batch, and only then become the one that's read. → [[Engine Database]]
- **Why it matters:** the heavy comparing happens at night, so the feed doesn't wait for it.
- **Status:** done. In the test, a person who liked 4 pet posts gets all the pet posts at the top of their list.

→ [[Nightly batches]]

### 4. Requests only read the stored list ✅
- **What it asks:** when someone opens the feed, just read their stored list. The check: "reading one user's list takes 20 ms or less".
- **What we did:** one quick lookup of tonight's batch, then one read of the person's list, already in order thanks to an index (like a book's index pointing straight to the page). It comes back in one go.
- **Why it matters:** the feed has about 200 ms in total; this read must be tiny.
- **Status:** done on the laptop: the database takes **0 ms**, and the engine adds about **5 ms** on top of the network. The network from my laptop to the database is about 25–35 ms each way, so the stopwatch shows 55–75 ms. The official 20 ms timing waits for the test server, which sits next to the database. → [[Indexes]], [[Environments]]

### A. In the nightly run ✅
- **What we did:** the job is called `similar_posts`. It runs every night straight after the interest score, and can be run by hand. Its log line says how many posts and people it saw and why any were left out.
- **Why it matters:** if it fails, yesterday's lists stay in use and an alert goes out.
- **Status:** done. On dev it finished in about a second.

→ [[Nightly batches]]

## Result (16 Oct 2026)
- 31 new tests pass (30 without a database, 1 against MongoDB); the rest of the suite still passes (647 without a database, 68 with).
- The job finishes, in the tests and on dev (into a throwaway database, which was then deleted).
- Reading one list: 0 ms in the database, about 5 ms beyond the network, 55–75 ms on the laptop's stopwatch.

## Decided
- **16 Oct 2026 (Kala):** a post's type is the detailed type, else the plain type; empty is "normal"; anything else is "other" and reported. Adding a type changes the model version.
- **16 Oct 2026:** likes on your own posts, seed posts and test accounts don't shape your taste (as for the interest score).
- **16 Oct 2026:** posts you engaged with long ago, or that can no longer be shown, still tell us your taste; they just can't be recommended.
- **16 Oct 2026 (Nisha), built 17 Oct:** a purchase made from a post counts towards your taste with weight 20, like in the interest score. Cancelled, rejected or returned orders, and orders with a return request still open, add nothing.
- **16 Oct 2026 (Nisha), built 17 Oct:** the posts your taste was built from are left off your list, and the next closest posts take their places, so you aren't shown what you've already seen.

## Still to do
| What | Waiting on |
|---|---|
| Time the read on the test server, then mark Passed | The test server → [[Environments]] |
| Raise the model version when this goes to the test server (the method changed on 17 Oct) | Deploy |
| Real lists on dev | New posts on dev (none in the last 30 days) |
| Merging this list with method one | [[ENG-15 - Merge the shortlist]] |

## How this connects
- **Before it:** [[ENG-13 - Quotas]]
- **Built on:** [[ENG-07 - Nightly jobs]], [[ENG-10 - Interest score on real data]], [[ENG-08 - Filters]], [[Nightly batches]], [[Settings file]], [[Engine Database]], [[Indexes]]
- **Next:** [[ENG-15 - Merge the shortlist]]. Puts method one's 300 and this list together into one shortlist of 200 for every person.
- **Technical version:** `docs/engineering/ENG-14.md` in the repo.
