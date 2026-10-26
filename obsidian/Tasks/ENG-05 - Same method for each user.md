---
tags: [task, step-1]
task: ENG-05
status: Passed
owner: Allen
---
# ENG-05: Same method for each user

> [!note] Status: **Built** (1 Oct 2026, on my laptop)
> All four parts work, and the three checks pass. It counts as finished once the same checks are re-run on the **test** server, which doesn't exist yet. → [[Environments]]

> [!success] Passed (16 Oct 2026)
> Kala: this task's check names no environment, so the run on my laptop is the evidence. Its three checks passed on dev (1 Oct; re-run 15 Oct). It covers this task's own check, not the later ENG-30 changes. → [[Answers 16 Oct]]

**In one line:** in each of three places where the engine has two ways of doing something, decide which way each user gets, and give them the same one every single time.

## Why this task
It's the last of the Step 1 foundations. → [[Build Steps]]

Three parts of the engine (the **slots**) each have **two methods**, and both get built. We want to learn which method works better on real people (ENG-26). That only works if:
- each user always sees the **same** method (otherwise their behaviour mixes both);
- the users are split **fairly**, about half each;
- every list says **which** method made it.

This task does all three. Serving a list ([[ENG-06 - Serve a recommendation list]]) asks it which method to use for each user. The product ranker (ENG-17) and the interest check script (ENG-11) wait on it too. → [[Two methods per slot]]

## What came before
- The M1 demo had **one** interest method and no choosing at all. → [[Before Wave 1A - the M1 demo]]
- [[ENG-02 - Service skeleton and settings]] made the [[Settings file]]: one file holding every number the engine can tune, re-read every 30 seconds without a restart, with every change written in a diary. The slot settings (the split and the method names) were put in it then, but nothing read them yet. This task is the first thing that does.
- [[ENG-04 - Engine sync]] copies SOCO's activity into my engine's database. This task needs none of it: choosing a method only needs the user's ID and the settings.

## Subtasks, one by one
The Build List splits ENG-05 into four numbered parts (1–4). We added three extras (A–C): the record of the method on each list, a rule for a missing user, and a script to look at the split.

The three slots and their methods:

| Slot | What it decides | Method one | Method two |
|---|---|---|---|
| `interest` | What a user likes (M1) | recency decay: recent actions count more | time windows: last week, last month, last 3 months, weighted |
| `product_ranking` | "You might also like" (M5) | attribute similarity: same category, price, seller | bought together: products bought in the same basket |
| `promoter_score` | How good a promoter is (M8) | `shrinkage` | `cohort_percentile` |

> [!note] The pack just says "method one" and "method two" for promoter_score. The names `shrinkage` and `cohort_percentile` are ours, taken from what ENG-16 describes: one pulls a small promoter's score toward their category's average, the other ranks them against similar promoters.

### 1. Turn each user into a number from 0 to 99 ✅
- **What it asks:** take the slot's name and the user's ID, joined by a colon (like `interest:64f1c0ffee…`), run it through SHA-256, and turn the first 8 characters of the result into a number from 0 to 99. That number is the user's **bucket**.
- **What we did:** exactly that. SHA-256 is a fixed recipe that turns any text into a long code. The same text always gives the same code, on any computer, today or in a year.
  - The slot's name is part of the text, so a user's bucket for `interest` says nothing about their bucket for `product_ranking`. The three choices are independent.
  - Only the user's ID is used. Never the session or the phone, because those change.
  - Never Python's own built-in `hash()`. It's re-seeded every time the program starts: on 1 Oct, the same text gave 23 on one run and 56 on the next.
- **Why it matters:** this is what makes the choice **stable**. A user who restarts the app, changes phone or comes back next month lands in the same bucket.
- **Status:** done.

> [!example] Like a coin that always lands the same way for the same name
> Toss it for "Asha" a thousand times: heads every time. Toss it for "Ravi": maybe tails every time. Across many names, it's still about half and half. The slot name is part of the "name" on the coin, so Asha can get heads for interest and tails for products.

→ [[Two methods per slot]]

### 2. Low buckets get method two ✅
- **What it asks:** each slot has a **split**. A bucket below the split gets method two; everyone else gets method one.
- **What we did:** with a split of 50, buckets 0 to 49 get method two and 50 to 99 get method one. With a split of 20, only buckets 0 to 19 get method two. The engine looks up the split **at the moment it's asked**, from the settings in force right then.
- **Why it matters:** the split is a dial. Turning it moves people between methods straight away, with no new release of the code. Later, ENG-26 turns it down to hand everyone the winning method.
- **Status:** done. Over 10,000 test IDs on the real settings: 50.21%, 49.72% and 50.59% on method two (all within 2 points of 50).
- → [[Two methods per slot]]

### 3. The split and the method names are settings ✅
- **What it asks:** the split, the two methods' names and the default method all live in the settings. The split starts at 50 everywhere; the default is method one.
- **What we did:** each slot has a short section in the [[Settings file]] with four lines: method one's name, method two's name, the split (50), and the default (`method_one`).
  - The split must be between 0 and 50. A file with 60 is refused, and the engine keeps the settings it already had.
  - The default can only be method one. The pack fixes it for Wave 1A.
  - Like every setting, a change needs a new version number, and it's written in the diary with who changed what.
- **Why it matters:** no number is hidden in the code. Anyone can see, and change, how users are split, and every change is on record.
- **Status:** done. These settings were put in the file with [[ENG-02 - Service skeleton and settings]]; this task is what reads them.
- → [[Settings file]]

### 4. If the settings are missing, everyone gets the default ✅
- **What it asks:** if the slot's settings can't be found, give everyone the default method, log the fault, and carry on.
- **What we did:** if the engine can't find a slot's settings, everyone gets method one, and it writes an ERROR line in its [[Logs]] saying so. The list is still served. Each list built that way is marked "used the default", so it can be found later.
- **Why it matters:** a settings mistake never breaks the app's feed. At worst, everyone gets the safe default for a while.
- **And if a slot's section is left out of the file?** Found and fixed on 1 Oct. Before, the engine quietly filled in the pack's starting 50/50 split and said nothing. Now, when it reads the file, it notices the missing section, puts everyone in that slot on method one, and logs an ERROR naming the slot ("settings file has no [slots.interest]"). The other slots carry on as written.
- **Status:** done, both cases.
- → [[Logs]], [[Settings file]]

### A. Extra: every list says which method made it (`policy_id`) ✅
- **What we did:** every list the engine returns carries a short label, the `policy_id`. For example, `cfg2.interest-recency_decay.promoter_score-shrinkage` means "settings version 2; the interest slot used recency decay; the promoter slot used shrinkage". A product list's label looks like `cfg2.product_ranking-attribute_similarity`. A feed list touches interest and promoter_score; a product list touches product_ranking.
- **Why it matters:** this is how the two methods are compared later (ENG-26). Every view and tap on the list is linked back to it. SOCO's own backup lists never start with `cfg`, so the two are never confused.
- **Why names and not "1" or "2":** when a winner is chosen later, the names are swapped round, so the winner becomes "method one". If the label said "2", it would mean one method before the swap and the other after. A name always says what actually ran.
- **Status:** done. → [[Served list record]]

### B. Extra: no user ID means the default everywhere ✅
- **What we did:** if a request ever arrives without a user ID, every slot gives method one. The pack's API contract asks for this. Login is required, so it shouldn't happen.
- **Why it matters:** without this rule, every such request would land in the same single bucket and be pushed onto whatever method that bucket gets. That would quietly tilt the comparison.
- **Status:** done.

### C. Extra: a script to see the split ✅
- **What we did:** a small script, `scripts/show_assignment.py`, reads the settings exactly as the engine does and shows:
  - for a user ID: their bucket, method and label in each slot;
  - with no ID: the share of 10,000 fixed test IDs on method two in each slot, and whether it's within 2 points of the split.

  It needs no database. Point it at a copy of the settings to try a change before making it.
- **Why it matters:** the split can be checked in seconds, on any machine, before and after any change. It's also the heart of the demo. → [[Demo - ENG-05]]
- **Status:** done.

## Result (1 Oct 2026)
- **Same user, same method:** two fresh starts of the program give every user the same method in every slot.
- **Labels name the method:** re-run after the change to names, one test user's labels read `cfg2.interest-recency_decay`, `cfg2.product_ranking-bought_together` and `cfg2.promoter_score-cohort_percentile`.
- **A slot left out of the settings:** everyone in it gets method one (0.00% on method two), with an ERROR line naming the slot; the other two stay at 50/50.
- **Turning the dial works:** with the split at 20 in a copy of the settings, the shares on method two were 19.55%, 20.19% and 20.01%. One test user moved from "bought together" to "attribute similarity" in the product slot; nothing else about them changed.
- **Fair split:** on the real settings, 50.21%, 49.72% and 50.59% of 10,000 test IDs get method two.
- **Automatic checks:** all **15** pass, with no database needed. The five checklist lines for this task pass too. → [[Checklist]]

## Decided
- **The `policy_id` label names the method (1 Oct 2026):** `cfg<version>.<slot>-<method name>` for each slot the list used, like `cfg2.interest-recency_decay.promoter_score-shrinkage`. We use our settings' slot names (`promoter_score`).

  > [!note] How we got there
  > The pack's texts disagreed. The API contract's example shows the method as a **number** and shortens the slot to `promoter` (`cfg3.interest-2.promoter-1`). The Build List writes `<method>`, its ENG-26 row says the label records method **names** "so history stays readable across the swap", and the Service Design Agreement says the same. The Build List comes first in the pack's order, so we use names. Briefly on 1 Oct the label used numbers; it was switched to names the same day. Kala is asked to correct the API example. The method's number is still written in each list's full record, next to its name. → [[Served list record]]
- **A slot left out of the settings file means everyone there gets the default, with a logged error (1 Oct 2026):** from the API contract's "missing configuration" rule. Before this, the engine quietly used the pack's starting 50/50 split.
- **A missing user ID gets the default in every slot (1 Oct 2026):** from the API contract.
- **Missing slot settings give the default, and the fault is logged (1 Oct 2026):** from the Build List.
- **Starting values (from the pack):** split 50 in all three slots; the default is method one, fixed for Wave 1A.

## Still to do
| What | Waiting on |
|---|---|
| Re-run the three checks on the test server and save the result | The test server → [[ENG-01 - Engine home and databases]] |
| Correct the API contract's `policy_id` example to match the Build List (names, `promoter_score`) | Kala, in writing |
| Count users per method per slot each week | ENG-24 |
| Compare the methods and promote the winner | ENG-26, after launch |

## How this connects
- **Before it:** [[ENG-04 - Engine sync]]
- **Built on:** [[Settings file]], [[Two methods per slot]], [[Logs]]
- **Next:** [[ENG-06 - Serve a recommendation list]]. It asks this task which method each user gets, puts the `policy_id` on every list it returns, and writes the method of each slot into the list's record.
- **Used later by:** the nightly jobs compute **both** methods for everyone, so whichever one a user is given is ready → [[Nightly batches]]. The rankers (ENG-17, ENG-19) read the row for the user's method.
- **Demo:** [[Demo - ENG-05]]. How to show this task working, step by step.
- **Technical version:** `docs/engineering/ENG-05.md` in the repo.
