# ENG-08: Eligibility filters E-01 to E-12

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 2 (within 12 working days) |
| **Waits on** | ENG-03 (built: the platform reader), ENG-29 (built: its adaptations). E-09 switches on once DB-08 exists |
| **Needed by** | ENG-13, ENG-17, APP-21, ENG-27 (and ENG-10, ENG-19, which apply the filters too) |
| **Status** | **Built** (1 Oct 2026, on dev). All twelve rules, the exclusion log and the final recheck with replacement are built; the row's check (one item excluded and one kept per rule) passes. Two rules wait on answers from Aravinth: **E-01** (the field names of a block in `followers`, question 16) and **E-08** (what a missing `status` means, question 17). The current state from ENG-27 (`ml_item_state`) is still to come; until then the item rules read the platform directly. Becomes Passed when re-run on **test** |
| **Spec** | Build List v1.3 ENG-08 (and Changes sheet v1.3 ENG-08, DB-06, APP-13, DB-14 "Not needed"; v1.2 ENG-08 "E-12 added"; Settings sheet "Filters"; AS-15, AS-19, AS-22); DS-017 v2.5 §4.3, §4.5, §7 (eligibility data); SDA v1.6 SD-31, SD-26, the `eligibility` module; Capture Register (29 Sep) X-19, X-12, F60–F65, X-16, F10, D10 |

---

## 1. What the item requires

The Build List v1.3 row, verbatim:

> Apply these rules before scoring and again on the final list. No model can override them. Log each exclusion with request_id, item_id and rule id.
>
> - **E-01:** the author has blocked the viewer, or the viewer has blocked the author: status blocked in followers, in either direction, for user and business accounts. Read from the platform when each list is built, not from the refresh, so a block takes effect on the next list.
> - **E-02:** the viewer muted the author (content feedback with feedback_type mute_author).
> - **E-03:** the viewer chose Not interested, Hide or Report on the item (feedback_type not_interested, hide or report), within the last 90 days.
> - **E-04:** the post is hidden or not public (posts.isHidden true, or posts.visibility not 'public').
> - **E-05:** the post's author has a private account (accountIsPublic false on users or businessregisters) and the viewer does not follow them.
> - **E-06:** a product post whose Product_status is not 'Activated'. 'N/A' passes: it means the post has no product.
> - **E-07:** a product that is not sellable. It passes only if products.status is 'Activate', availability.inStock is true, and at least one active variant has quantity minus reservedStock above 0.
> - **E-08:** the author or seller is not active (users.status or businessregisters.status, ignoring case).
> - **E-09:** the author is suspended or removed (restriction_level, once DB-08 exists).
> - **E-10:** the viewer's own posts and products are not shown to them.
> - **E-11:** posts whose ageGroup marks adult-only content are not shown to users under 18 (from users.DOB), or to users with no DOB. Today every post is 'All'.
>
> No region rule in Wave 1A: every product is 'All India'.
>
> - **E-12:** the post's compliance.status is deranked or removed. Posts under review are served as normal.
>
> E-04 to E-09 and E-12 are applied against the current state kept by ENG-27, not only against the nightly scores.
>
> Before a list is returned, its items are re-checked on the platform for blocks, visibility and stock (one read per list, for the returned ids). Any that fail are replaced by the next eligible items.

**How to check it is done:**

> A test case for each rule: one item excluded and one kept.

**Around the row:**

- **Capture Register X-19 (Blocks):** *"Blocks are read from followers (status blocked), in either direction, for user and business accounts, when each list is built (build list ENG-08). No blocks collection is added. Build list APP-21 test 3 checks blocking end to end."* (DB-06 and APP-13 are *Not needed* for the same reason; AS-22: blocks are saved as status blocked in followers, in either direction.)
- **Capture Register X-12 and F60–F65 (content feedback, E13):** *"E13 content_feedback is sent on not interested, hide, report or mute author. Fields F60 to F65."* F61 `target_id`: *"The post, product or author the feedback is about."* F62 `target_type`: *"One of post, product, author."* F63 `feedback_type`: *"One of not_interested, hide, report, mute_author."*
- **DS-017 v2.5 §4.3:** *"The service applies every eligibility rule itself, re-checks the returned items when it builds each list, and returns exactly limit items unless fewer eligible items exist."* SOCO_BE shows the list *"exactly as returned: no filtering"*.
- **DS-017 v2.5 §4.5 (Fallback):** SOCO_BE's own lists *"must pass the same visibility rules the app already applies: blocked authors, hidden, private, deranked or removed posts and out-of-stock products are never shown."*
- **DS-017 v2.5 §7:** *"For eligibility it also reads posts, users, businessregisters, products, productvariants, categories, follows and followers (blocks)."* and *"Blocks, visibility and stock are also re-checked on the returned items when each list is built (build list ENG-08, ENG-27)."*
- **SDA v1.6 SD-31** (the same, from the service side) and the `eligibility` module: *"Filter rules: blocks … feedback, private, hidden, deranked or removed posts, inactive or restricted accounts, out of stock. Uses the current state kept by the sync, and re-checks the returned items when each list is built (SD-31)."*
- **Settings sheet, Filters:** *"Not interested, Hide or Report hides an item for 90 days"* (range 30 to 365, fixed for Wave 1A).

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–12 are the rules E-01 to E-12, 13–16 are the row's other parts, A–B are extras.

**Layout:**

| File | Holds |
|---|---|
| `reco/eligibility/rules.py` | The rules, **pure** (no database): `RULES` (id → name), `Viewer`, `post_rule`, `product_rule`, `product_is_sellable`, `account_rule` |
| `reco/eligibility/apply.py` | Applying them to real items: `viewer_context`, `eligible_posts`, `eligible_products`, `recheck`, the per-request account cache, and the exclusion log |
| `reco/platform/fetch.py` | `read_where`, `read_blocks`, `read_newest`, `_FIELDS` projections |
| `reco/platform/records.py` | `BlockRecord` / `parse_block`; `restriction_level` on user and business records; `target_id` / `target_type` on `PostEventRecord` |
| `reco/store/writers.py` | `read_viewer_feedback` (the engine's copy of feedback events) |
| `reco/ranking/serving.py` | `interim_candidates` (returns `Built`), `page_after_recheck`, `MAX_SCAN_ROWS` |

ENG-06's stand-in check (`reco/eligibility/basic.py`) was removed; serving uses these rules instead (`11e515e`).

**How a rule is reported.** `post_rule` and `product_rule` return the **first** rule an item fails, in E-number order, or `None` when the item is eligible. One item, one logged rule. Status fields are compared with `records.status_is` (ignoring case and surrounding spaces, plus the ENG-29 spelling map).

**The viewer.** `Viewer(user_id, own_ids, follows, blocked, muted, dismissed, date_of_birth, today)`, built by `viewer_context(settings, user_id)` when each list is built. One round trip in parallel (`asyncio.gather`): the user (DOB), the businesses they own (`businessregisters.user_id`), their follows (`follows.userId`), block rows touching their user id, and their feedback from the engine's copy. Only when they own a business is a second read made, for the blocks touching those business ids. A request with no `user_id` gets an empty `Viewer`.

### 1. E-01: blocked, either direction: done; field names wait on question 16

- `fetch.read_blocks(settings, account_ids)`: `followers` rows whose `status` is `blocked` (any case, spaces trimmed) with `userId` **or** `followerId` among the viewer's own ids (their user id and every business they own), ids matched as text or ObjectId. Read from the **platform** when each list is built, never from a refresh, so a block takes effect on the next list (row; X-19).
- `viewer.blocked` = the other side of each row: the blocked account when the blocker is one of the viewer's ids, otherwise the blocker. So "they blocked me" and "I blocked them" both exclude.
- `post_rule` / `product_rule`: the post's author (`posts.userId`) or the product's seller (`products.createdBy`) in `viewer.blocked` → E-01.
- **Assumed shape (pack silent):** `records.parse_block` reads `{userId: blocker, followerId: blocked, status: "blocked"}`. `followers` is empty on dev and its field names aren't documented. *Open question 16 to Aravinth* (`Tracing/REALIGNMENT_v1.3.md`): which fields hold the blocker and the blocked account, and can either be a `businessregisters` id. If the answer differs, only `parse_block` and the `read_blocks` query change. *Rule the choice must satisfy:* X-19 "in either direction, for user and business accounts".

### 2. E-02: muted author: done

- Feedback is read by `writers.read_viewer_feedback(settings, user_id, since)` from `ml_events` (the engine's copy of `postevents`, ENG-04): `event_type: feedback`, `undone_at: None` (an undone mute or dismissal no longer applies).
- A `mute_author` row mutes `target_id` when `target_type` is `author` (F61, F62); otherwise `influencer_id`; otherwise, a mute recorded against a post (`post_id`, or `target_id` with `target_type: post`) mutes **that post's author** (one extra post read).
- **No time limit**: every `mute_author` is read, however old. *The row gives E-03 a 90-day window and E-02 none.*
- `post_rule` / `product_rule`: author or seller in `viewer.muted` → E-02.

### 3. E-03: not interested, hide or report, last 90 days: done

- `not_interested`, `hide` and `report` rows since `now − filters.feedback_hide_days` (90; Settings sheet "Filters", fixed for Wave 1A) add the item to `viewer.dismissed`: `target_id` when `target_type` is `post` or `product` (F61, F62), plus any of `item_id`, `post_id`, `product_id` the row carries (the shapes older copies have).
- `post_rule`: `post_id` in `viewer.dismissed` → E-03; `product_rule`: `product_id` in it → E-03.

### 4. E-04: hidden or not public: done

`posts.isHidden` true, or `posts.visibility` not `public` (ignoring case) → E-04.

### 5. E-05: private author the viewer doesn't follow: done

The author's `accountIsPublic` is `false` (on `users` or `businessregisters`) and the author is not in `viewer.follows` → E-05. Only an explicit `false` counts as private (the row's words). The viewer's own private posts are not E-05: they fall to E-10.

### 6. E-06: product post not Activated: done

A post that carries a product (`products` / `productId`), or whose `Product_status` is set and isn't `N/A`, must have `Product_status` `Activated` (ignoring case) → otherwise E-06. `N/A` passes.

**Choice (pack silent):** a **missing** `Product_status` passes only when the post carries no product. *Rule it must satisfy:* the row's "'N/A' passes: it means the post has no product"; a product post with no status is not 'Activated'.

### 7. E-07: product not sellable: done (also on post cards)

`rules.product_is_sellable`: `products.status` `Activate` (ignoring case, spelling map) **and** `availability.inStock` true **and** at least one variant with `status` active and `quantity − reservedStock > 0` (a missing `reservedStock` counts as 0).

- `eligible_products` runs every check that needs no variants first, and reads `productvariants` only for the products still in the running.
- **Also on the feed:** a post card showing a product needs that product sellable too, or the post is excluded as E-07 (`eligible_posts`). *Choice (the row is about products; the pack is explicit that out-of-stock products are never shown, DS-017 §4.5).*

### 8. E-08: author or seller not active: done; missing status waits on question 17

`rules.account_rule`: the author or seller's `status` must be `active` (ignoring case) → otherwise E-08.

- **Choice (pack silent):** a **missing** status is not active (as in ENG-03), and an account **not found** in either `users` or `businessregisters` is not active. *Open question 17 to Aravinth:* does a missing status mean active? On dev the two import sellers (2,006 of 2,011 products), 2 users and 4 businesses have no `status`, so **no product on dev can be served** today. If the answer is "missing means active", the change is one line in `records` (`is_active`).

### 9. E-09: suspended or removed: done; switches on by itself with DB-08

`restriction_level` is read on users and businesses (`_FIELDS`, `records`), lower-cased. `suspended` or `removed` → E-09 (`BLOCKED_RESTRICTIONS`). The field doesn't exist yet (DB-08 sits outside the six steps, needed once SOCO names the fraud roles), so today nothing is excluded; when DB-08 adds it, the rule applies with no code change. `warning` and `restricted` are not excluded (the row names only suspended and removed).

### 10. E-10: the viewer's own items: done

`viewer.own_ids` = the viewer's user id plus the ids of every business they own (`businessregisters.user_id`). An author or seller in it → E-10.

### 11. E-11: adult-only content: done (nothing to exclude today)

`viewer.is_adult`: 18 or over on today's date from `users.DOB`; no DOB → not adult. A post whose `ageGroup` is adult-only, shown to a viewer who isn't adult → E-11.

**Choice (pack silent on the values):** any `ageGroup` other than `All` or empty counts as adult-only. *Rule:* the row ("Today every post is 'All'") and AS-15: when anything else appears, the rule starts excluding, failing safe. No region rule (row; AS-19).

### 12. E-12: deranked or removed: done

`posts.compliance.status` `deranked` or `removed` (ignoring case) → E-12. `under_review` passes ("served as normal").

### 13. Log each exclusion with request_id, item_id and rule id: done

`apply._log`: one INFO line per excluded item on logger `reco.eligibility`, message `excluded`, fields `request_id`, `item_id`, `item_type` (`post` or `product`) and `rule`. With the engine's JSON logging (`reco.monitoring.logs`):

```
{"ts": "2026-10-01T12:37:43.355Z", "level": "INFO", "logger": "reco.eligibility", "message": "excluded", "env": "dev", "request_id": "req-demo-eng08", "item_id": "6a5a7b814834d0026569a2d1", "item_type": "post", "rule": "E-05"}
```

**No database pre-filter** (`fetch._EMPTY_INDEX` comment, `d1e5427`): serving reads posts and products with an empty query and every row goes through the rules, so **every** exclusion is logged with its rule. The first version (`11e515e`) narrowed the query at the database (public, not hidden posts; `Activate`, in-stock products), so those exclusions were never logged (audit finding, removed in `d1e5427`, 1 Oct).

### 14. Before scoring and again on the final list; no model can override: built on serving / ⏳ the scoring jobs

- **On the final list:** done. `serving.interim_candidates` keeps only items that pass `eligible_posts` / `eligible_products`, and `page_after_recheck` (part 16) runs them again on the page just before it is returned. Nothing after the filters adds items back: exploration shuffles only eligible items (DS-017 §4.3).
- **Before scoring:** the nightly jobs that score items (ENG-10, ENG-13, ENG-17) will call the same functions on their candidates. **17 Oct 2026:** ENG-17's job scores only sellable products (`product_is_sellable`, E-07, and the seller's `account_rule`, E-08/E-09) and the request applies every rule again with the viewer's own; ENG-13 still to come.
- *No model can override:* the rules live in one module that takes no model input, and serving applies them after any ordering.

### 15. E-04 to E-09 and E-12 against ENG-27's current state: ⏳ ENG-27

The row has these rules read ENG-27's `ml_item_state` (refreshed every 15 minutes, `filters.eligibility_refresh_minutes`). ENG-27 isn't built, so **until it is, the item rules read the platform directly** for the items in hand (`fetch.read_where` / `read_newest`), which is at least as current. When ENG-27 lands, `eligible_posts` / `eligible_products` read its state instead and `recheck` (part 16) stays a platform read.

### 16. Final recheck with replacement: done

- `serving.interim_candidates` builds the eligible list **through the requested page plus one spare page** (`wanted = (page + 1) × limit`).
- `serving.page_after_recheck` takes the page's items and calls `apply.recheck`, which re-reads them on the platform **just before the list is returned**: posts by id in one read, products by id in one read (a card with a `post_id` is a post card, including one showing a product, X-16 / F10). Accounts read earlier in the same request are reused from the account cache; blocks are the ones read when this list was built.
- Items that now fail are logged (part 13) and replaced by the next items from the spare page, in order. DS-017 §4.3 allows fewer than `limit` when there are no more eligible items.
- Tested: a post hidden on the platform after the list was built is dropped and the next eligible post takes its place.

### A. Extra: speed work, and PyMongo 4.10.1 → 4.18.2: done

With every rule reading the platform, a request makes several reads; SOCO_BE allows 250 ms (AS-07, DS-017 §4.3).

- **PyMongo 4.10.1 → 4.18.2** (`requirements.txt`). 4.10's async client ran parallel operations one after another: five pings took about 110 ms on 4.10 and about 25 ms on 4.18 (measured 1 Oct from the laptop).
- **Warm connections:** `minPoolSize` 10 on both clients (`MIN_POOL`), and `warm()` at startup opens them in parallel (`reco/main.py`). *Choice (pack sets no pool size).* Driver retries are off (SD-26, ENG-06).
- **Projections:** `fetch._FIELDS` reads only the fields the parsers use (product documents carry images and specifications).
- **Account cache:** within one request each author or seller is read once (`AccountCache`), and the recheck reuses it.
- **Scan cap:** `serving.MAX_SCAN_ROWS = 1000`. *Choice (pack silent); rule:* without a cap, a surface where nothing is eligible would read the whole collection on every request; DS-017 §4.3 allows fewer than `limit` items when fewer eligible items exist.
- **Result (1 Oct, laptop over HTTP to Atlas):** feed p95 **127 ms**. The official 200 ms check is on the test server (ENG-20).

### B. Extra: `scripts/show_exclusions.py`: done

Read-only. Builds the first feed page and the first product page the way the engine does (as a made-up viewer, or a real user id given as an argument), records nothing, and counts the exclusion log lines per rule. Prints counts and rule names only, no ids.

**Real run on dev, 1 Oct 2026** (re-run for this doc):

```
feed: 3 eligible of 8 read
product: 0 eligible of 1000 read
left out, by rule:
  E-05  post         5  private author the viewer does not follow
  E-07  product    143  product not sellable
  E-08  product    857  author or seller not active
```

- **Feed:** dev holds 8 posts; 5 are by private authors the made-up viewer doesn't follow.
- **Product:** the newest 1,000 products (the scan cap) are all excluded. 143 fail E-07 first (out of stock, `availability.inStock` false); the other 857 are sold by sellers with no `status` (question 17), so E-08. Every seller of those products has no status, so even the in-stock ones can't be served until question 17 is answered.

---

## 3. Configuration reference

No new environment variables. Settings (`settings/engine.toml`, `[filters]`, validated in `reco/config/tunables.py`):

| Setting | Value | Rule |
|---|---|---|
| `feedback_hide_days` | 90 | 30–365, fixed for Wave 1A (Settings sheet "Filters"); E-03's window |
| `eligibility_refresh_minutes` | 15 | 5–60, fixed; used by ENG-27, not yet |

Code constants (choices, §2): `rules.BLOCKED_COMPLIANCE = ("deranked", "removed")`, `rules.BLOCKED_RESTRICTIONS = ("suspended", "removed")`, `serving.MAX_SCAN_ROWS = 1000`, `serving._READ_PAGE = 250`, `connection.MIN_POOL = 10` (both clients).

---

## 4. Tests

`tests/test_eligibility.py`, on platform-shaped documents from `tests/platform_dataset.py` (ENG-29 item 8):

| What | Test |
|---|---|
| The check: one excluded, one kept, per rule | `test_e01_blocked_either_way` … `test_e12_deranked_or_removed` (12 tests, no database) |
| All twelve rules named, in order | `test_every_rule_is_named` |
| Viewer context from the platform and the engine copy: blocks, follows (ids as text and ObjectId), a 91-day-old hide ignored, a mute on a post mutes its author, `target_id` / `target_type`, a year-old mute still applies, an undone mute doesn't | `test_the_viewer_context_comes_from_the_platform_and_the_engine_copy` |
| Each exclusion logged with request_id, item_id and rule; logged + kept = all | `test_each_exclusion_is_logged_with_request_id_item_and_rule` |
| A post hidden after the list was built is replaced by the next eligible one | `test_an_item_failing_the_final_recheck_is_replaced` |
| A post card showing a product with no stock left is excluded | `test_e07_a_post_card_showing_an_unsellable_product_is_left_out` |

```bash
TEST_MONGO_TIMEOUT_MS=15000 .venv/bin/python -m pytest -q tests/test_eligibility.py
```

**Results, 1 Oct 2026:** `tests/test_eligibility.py`: **17 passed** (13 without a database, 4 marked `mongo`), with `TEST_MONGO_DB=reco_test_eng08doc`. Full suite at `964f4ec` (working tree clean): **634 passed, 1 skipped** (1 Oct 2026).

`scripts/run_checklist.sh` section 9:

| Line | Checks |
|---|---|
| 9.1 | each rule E-01 to E-12: one item excluded, one kept (the ENG-08 check), expects `12 passed` |
| 9.2 | the viewer's follows, blocks and feedback are read when the list is built |
| 9.3 | every exclusion is logged with request_id, item_id and rule |
| 9.4 | an item failing the final recheck is replaced by the next eligible one |
| 9.5 | the rules run on SOCO's real data (`show_exclusions.py`) |

---

## 5. Runbook

```bash
# Which rules leave what out on SOCO's data (read-only, no ids printed).
.venv/bin/python scripts/show_exclusions.py               # a made-up viewer
.venv/bin/python scripts/show_exclusions.py <user id>     # as a real user

# The row's check.
.venv/bin/python -m pytest -q tests/test_eligibility.py -m 'not mongo' -k 'test_e0 or test_e1'
```

**Why was an item not served?** Search the logs for `"logger": "reco.eligibility"` with the request's `request_id`: one `excluded` line per item left out, with its `rule`. `RULES` in `reco/eligibility/rules.py` names each rule.

**When Aravinth answers question 16** (block fields): change `records.parse_block` and the `fetch.read_blocks` query; rerun `test_the_viewer_context…` with a block row in the real shape. **Question 17** (missing status): change `is_active` in `records.parse_user` / `parse_business` if missing means active; rerun `show_exclusions.py` and expect products on the product surface.

---

## 6. Open

| Open item | Waits on |
|---|---|
| E-01: the real field names of a block row in `followers` (assumed `userId` blocker, `followerId` blocked); can either side be a business | **Question 16**, Aravinth (`Tracing/REALIGNMENT_v1.3.md`) |
| E-08: does a missing `status` mean active? (no product on dev can be served while it doesn't) | **Question 17**, Aravinth |
| E-09 starts excluding | **DB-08** (`restriction_level`) |
| E-04 to E-09 and E-12 read `ml_item_state` instead of the platform | **ENG-27** |
| Apply the filters before scoring | **ENG-10, ENG-13, ENG-17** (the scoring jobs, not built) |
| Blocking end to end, both directions, within a minute | **APP-21** test 3 (Aravinth) |
| Run the checks on test, then mark Passed | The test environment (ENG-01) |
| The 200 ms p95 at SOCO_BE (127 ms on the laptop over HTTP) | ENG-20 on the test server |

---

## 7. Files changed

Commits `11e515e`, `6c3ef46`, `d1e5427`, `964f4ec` (1 Oct 2026):

| File | Change |
|---|---|
| `reco/eligibility/rules.py` | New: `RULES`, `Viewer`, `post_rule`, `product_rule`, `product_is_sellable`, `account_rule` |
| `reco/eligibility/apply.py` | New: `viewer_context`, `eligible_posts`, `eligible_products`, `recheck`, account cache, exclusion log |
| `reco/eligibility/basic.py` | Removed (ENG-06's stand-in check) |
| `reco/ranking/serving.py` | `interim_candidates` returns `Built` and builds a spare page; `page_after_recheck`; `MAX_SCAN_ROWS` |
| `reco/api/recommendations.py` | Serving calls the filters and the recheck |
| `reco/platform/fetch.py` | `read_where`, `read_blocks`, `_FIELDS` projections, no database pre-filter |
| `reco/platform/records.py` | `BlockRecord`, `parse_block`; `restriction_level`; `target_id` / `target_type` on post events |
| `reco/platform/connection.py`, `reco/store/connection.py`, `reco/main.py` | `minPoolSize`, `warm()`, no driver retries |
| `reco/store/writers.py` | `read_viewer_feedback` |
| `requirements.txt` | `pymongo` 4.10.1 → 4.18.2 |
| `scripts/show_exclusions.py` | New |
| `scripts/run_checklist.sh` | Section 9 (9.1–9.5) |
| `tests/test_eligibility.py` | New: 17 tests |
| `tests/test_recommendations.py` | Serving through the filters |

## 8. Demo

The live demo script, in plain language, is `obsidian/Demos/Demo - ENG-08.md`.

## Pack v1.4 update (15 Oct 2026)

- Rework (ENG-29): status comparisons go through the spelling map, so "Activate" and "Activated" both count. The code already did (`records.status_is`); on 15 Oct the map gained its first entry, `status_spellings = { activated = "activate" }` (settings config_version 4).
- ENG-30 point 11 (a check only): `test_e12_serves_every_other_compliance_status`, where ok, review, fix_requested and no compliance record are served.

## Update, 16 Oct 2026

**16 Oct 2026:** Passed (Kala S1). Blocks read `follower_id` (blocker) / `user_id` (blocked); a person is active by `moderation.state` (missing or active). F3 proof: `Tracing/checks/F3_E08_by_store_2026-10-16.md`. See `ANSWERS_2026-10-16.md`.
