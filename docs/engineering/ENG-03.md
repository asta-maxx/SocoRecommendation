# ENG-03: Read platform data correctly

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | ENG-02 (built) |
| **Needed by** | ENG-08, ENG-09, ENG-10, ENG-12, ENG-16, ENG-17, ENG-21, ENG-29 |
| **Status** | **Built.** First built 29 Sep 2026 to the 22 Sep row; **realigned to the v1.3 row on 1 Oct 2026** (commit `2c861d7`), and its check passed again on dev the same day. Becomes Passed when re-run on test |
| **Spec** | Build List v1.3 ENG-03 (and ENG-29 items 1, 2, 4–7 where noted); SDA v1.6 SD-06; AS-12 (platform schema reference v4, 28 Sep 2026); DS-017 v2.5 §3, §6.4, §7; Capture Register (29 Sep) sheet 4 "Native event map", F02, F06, F10, F75, F79, X-05, X-09, X-16, X-18 |

> **What changed on 1 Oct (v1.3).** The 22 Sep row had an **event source
> switch**: old recommendation collections before a switch date, `ml_events`
> from it. v1.3 removes it. The platform's production migration (DB-16) moves the
> older collections into `postevents` before the engine backfill, and models read
> events only from the engine's own copy (ENG-04). The switch code, the four
> `legacy_*` record kinds and `read_switched` are gone. The row also adds
> polymorphic actors, served-item identity, positions, undo fields and post-page
> impressions, and its check names three more cases. Background:
> `Tracing/REALIGNMENT_v1.3.md`.

---

## 1. What the item requires

The Build List v1.3 row, quoted:

> The platform module and the sync apply these rules everywhere:
> - **IDs:** every id is converted to a 24-character string. follows, friends, followers.user_id, comments, orders.promoter_id and several others store ids as text (platform schema reference v4, section 23); users, posts, postevents and orders store ObjectIds. Actors are polymorphic: user_model (postevents) or userModel (orders, carts) says whether an id is in users or businessregisters.
> - **Field names** (platform schema reference v4, 28 September 2026): order value orders.total_price; order time orders.created_at; change time orders.updated_at; variant bought orders.variant_id; basket orders.checkout_id; order outcome orders.order_status, orders.statusLog (APP-08) and orders.return_info (DB-03). Post time posts.timestamp. Product time products.createdAt. Event time postevents.created_at; change time postevents.updated_at; on-screen time postevents.dwell_ms. Price productvariants.salePrice. Stock productvariants.quantity minus reservedStock. Product seller products.createdBy. Post compliance posts.compliance.status. Follows follows.userId and followingId, with followingReference.
> - **Categories:** a post's categories are matched by name to the 23; a product's categoryPathIds must start with one of the 23. Anything that does not map is dropped, not scored.
> - **Status fields:** compared ignoring case.
> - **Events:** one source, the engine's copy of postevents (ENG-04). Native event types are mapped to the E codes as in the capture register, sheet 4. Served lists: the engine's own E1 records for engine lists; recommendationrequests for fallback lists and for the delivered-list record of engine lists. There is no event source switch: the production migration (DB-16) moves the older collections into postevents before the engine backfill.
> - **Served item identity:** item_id and item_type are the card shown; post_id and product_id are kept alongside. On platform feed lists, item_type product with a post id is a post card showing a product: read it as post_id = item_id, with the post's product as product_id.
> - **Positions:** events carry the displayed position; the delivered-list record maps it to engine_position.
> - **Undo and own posts:** undone_at, undo_of and is_self are kept on every copy. Each model applies its own rule (ENG-10, ENG-16, ENG-17, ENG-21); nothing is filtered globally.
> - **Ignored:** users.addNew_Interest, the delivered interestScores (except as the old score in the fallback ladder), and feedScore (except for the fallback ordering).
> - **Post-page impressions:** impressions with surface post_detail are page visits. They never count as card impressions or qualified card views. Which cards were seen is worked out from the engine's own copy of impressions, excluding post_detail, not from the platform's seen_ids.

**How to check it is done:** "Unit tests read one of each record type and return
the expected values, including a follows record with text ids, a businessRegister
actor, a product post on a platform feed list, and an order with a status log and
a return request."

**ENG-29 overrides part of this row.** ENG-29 (v1.3): "Where ENG-03 or ENG-04
mention orders.statusLog, return_info, the delivered-list record or
engine_position, this item replaces them: the platform does not have those."
So the order's history is `orders.tracking_info` (ENG-29 item 4), returns are the
stored `Return Requested` / `Returned` values (items 2 and 5), and there is no
delivered-list record or `engine_position` (item 7). The records below are built
that way.

> **Added on top by ENG-29 (1 Oct 2026, `f7c82f3`):** status spellings from the
> settings (`lists.status_spellings`, used by `status_is` and `spellings_of`),
> tracking stages and actors on each `tracking_info` entry (`lists.tracking_stages`;
> `delivered_at`, `return_requested_at`, `returned_at`, `cancelled_at`), the
> `serve_log` record kind (`parse_serve_log`), and the account lists helper
> (`reco/config/accounts.py`). See `docs/engineering/ENG-29.md` and, in the vault,
> `obsidian/Tasks/ENG-29 - Adapting to the platform as built.md`.

> **Audit and questions, 1 Oct 2026** (commits `11e515e`, `d1e5427`, `6c3ef46`,
> `2b585af`; checked against the v1.3 pack; questions in
> `Tracing/REALIGNMENT_v1.3.md`, "Questions (reviewed 1 Oct 2026)"):
> - **Part 10:** a post-page impression is recognised whatever the case of its
>   surface (`post_detail`, `Post_Detail`…), like every other status compare (part 4).
> - **Part 6:** question 4 answered: a feed post card showing a product is stored
>   with `item_type` `product` (F10, X-16); the engine's own lists now write it
>   that way (ENG-06). The reading rule here is unchanged.
> - **Part 2:** new record fields for ENG-08: `PostEventRecord.target_id` /
>   `target_type` (E13 F61/F62), `restriction_level` on users and businesses
>   (E-09), and `BlockRecord` (an **assumed** `followers` shape, question 16).
> - **Answered, off the open list:** 11 (seen items), 4 (`item_type`), 6 (follows).
> - **Still open here:** the M1 refresh reads live `postevents` through the old
>   reader (ENG-10 fixes it).

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–10 are the v1.3 row's parts, in its order;
A–B are extras.

### 1. IDs, and polymorphic actors: built

- `reco/platform/ids.py`: `to_str`, `id_match`, and `maybe_str(value)` for
  optional references (`None` for an empty field). Every record id is the
  24-character text form, whether stored as ObjectId or text.
- **Opaque ids are kept as written:** `event_id`, `request_id`, `session_id` and
  `checkout_id` are strings, not ObjectIds (DS-017 v2.5 §3). `records._opaque`.
- **Actors** (F79): `records.actor_kind(value)` maps `user_model` (postevents) or
  `userModel` (orders, carts, recommendationrequests) to `user`, `business`
  (`businessRegister`, any case) or `unknown`. `PostEventRecord.actor`,
  `OrderRecord.buyer_actor`, `CartLineRecord.actor`, `ServedListRecord.actor`.
- Real data, 1 Oct: `follows` ids are text (93/93); 6 of 146 `postevents` rows
  are by a businessRegister actor.

### 2. Field names, and time from `_id`: built

`reco/platform/records.py` has one frozen Pydantic record and one pure
`parse_<kind>(doc)` per kind. **11 kinds** (`records.RECORD_KINDS`): `user`,
`business`, `post`, `postevent`, `follow`, `order`, `cart_line`, `product`,
`variant`, `category`, `served_list`.

| Meaning | Field | Record field |
|---|---|---|
| Order value / time / change time | `orders.total_price` / `created_at` / `updated_at` | `OrderRecord.value` / `created_at` / `updated_at` |
| Variant bought / basket | `orders.variant_id` / `checkout_id` | `variant_id` / `checkout_id` |
| Order outcome | `orders.order_status`, history in `tracking_info` (ENG-29 item 4) | `status`, `tracking`, `is_returned`, `cancelled_by` |
| Post time / compliance | `posts.timestamp` / `compliance.status` | `PostRecord.created_at` / `compliance_status` |
| Product time / seller | `products.createdAt` / `createdBy` | `ProductRecord.created_at` / `seller_id` |
| Event time / change time / on-screen time | `postevents.created_at` / `updated_at` / `dwell_ms` | `PostEventRecord.created_at` / `updated_at` / `dwell_ms` |
| Price / list price | `productvariants.salePrice` / `originalPrice` | `VariantRecord.price` / `list_price` |
| Stock | `quantity − reservedStock` | `VariantRecord.stock` |
| Follows | `follows.userId` → `followingId`, `followingReference` | `FollowRecord` |

**Time fallback:** `ids.time_of(doc, *fields)` uses the named field, then the
ObjectId creation time from `_id`. Naive times are taken as UTC. `updated_at` is
read as stored (it is the sync key, ENG-04) and never falls back to `_id`.

**Orders (ENG-29 items 2, 4, 5, built here because the check names "an order
with a status log and a return request"):**
- `tracking` is `orders.tracking_info`, each entry's `status` and `timestamp`.
- `is_returned` is true when `order_status` or any `tracking_info` entry is
  `Return Requested` or `Returned`, compared ignoring case. The values come from
  the settings' `lists.order_status` (`OrderStatusValues`), not code.
- `cancelled_by` is worked out, not stored (DS-017 v2.5 §6.4): `Cancelled` is the
  buyer; `Rejected` with `buyer_approval_status` `Rejected By Seller` is the
  seller; `Rejected` with `Rejected` is the buyer.
- `cancel_reasons` keeps whichever of `reason_code`, `cancel_reason`,
  `cancel_reason_by_buyer`, `reject_reason_by_buyer` is present. Stored, never
  scored (ENG-29 item 4).
- `is_incognito` (`isIncognitoMode`) is kept. Incognito is purchase privacy only
  (X-09): the order counts for the buyer; nothing names them.

**Added 1 Oct 2026 for ENG-08's eligibility rules** (`11e515e`, `d1e5427`):

| Record | Field | From | For |
|---|---|---|---|
| `PostEventRecord` | `target_id`, `target_type` (lower case) | `postevents.target_id`, `target_type` | E13 feedback: the post, product or author it is about (Capture Register F61, F62; ENG-08 E-02, E-03) |
| `UserRecord`, `BusinessRecord` | `restriction_level` (lower case, `None` when blank) | `restriction_level` | ENG-08 E-09, once DB-08 adds the field |
| `BlockRecord` (`parse_block`) | `blocker_id`, `blocked_id` | a `followers` row with `status` `blocked` (any case): `userId` blocks `followerId` | ENG-08 E-01 (DB-06: "the existing status blocked in followers"). **Assumed shape**: `followers` is empty on dev with only its `_id` index; question 16 to Aravinth. A row that isn't a block returns `None`. Read by `fetch.read_blocks` |

`BlockRecord` is not in `RECORD_KINDS`: it is a view of `followers` rows, used
only by `read_blocks`.

**Choices where the pack is silent:** user and business times come from
`timestamp`; cart lines from `carts.timestamp`; served lists from `server_ts`,
then `created_at`; `users.DOB` (stored as text) is parsed as ISO, `d-m-Y`,
`d/m/Y` or `Y/m/d`.

### 3. Categories: built

`reco/platform/categories.py`:
- **`canonical_name(vocab, label, category_map)`:** matches by name to the 23,
  ignoring case and spacing. If that fails, the settings' `lists.category_map`
  (ENG-29 item 1) is tried, and its target must itself be one of the 23. The old
  legacy map is **never** consulted. Anything still unmatched returns `None`:
  dropped, not scored, never guessed.
- **`post_categories(...)`:** a post's (and a user's declared) categories,
  resolved and dropped kept apart.
- **`ProductCategoryIndex`:** a product's category id is `categoryPathIds[0]`; the
  first name in that category's `path` in `categories` must be one of the 23 (by
  name or the map). **Choice:** where `categoryPathIds` is absent, use
  `basicInfo.categoryId`, so the rule still applies to today's data (0 of 2,011
  products carry `categoryPathIds`). Rule it satisfies: an unmapped category is
  dropped, never guessed.
- `fetch.product_categories(settings)` builds the index.

### 4. Status compared ignoring case: built

`records.status_is(value, expected)` ignores case and surrounding spaces.
Different words stay different: `products.status` is compared with `Activate`
and `posts.Product_status` with `Activated`, separately (E-06, E-07). The status
spelling map (ENG-29 item 2) is a later addition.

### 5. Events: one source, the native event map, served lists, no switch: built

**One source per kind of data:** `reco/platform/sources.py`, `SOURCES`:

| Data | Source |
|---|---|
| `event` (every postevents type) | `ml_events` (the engine's copy, ENG-04) |
| `served_list` (engine E1 lists; fallback lists from `recommendationrequests`) | `ml_events` |
| `order`, `order_history`, `cancellation`, `return` | `ml_orders` (the engine's copy) |
| `follow_graph` | `follows` (platform). Question 6, answered 1 Oct: business follows come from `follows` too (`followingReference` businessRegister), not from postevents follow rows (Build List ENG-10) |
| `block` | `followers` (platform, read when each list is built, ENG-08; `BlockRecord`, assumed shape, question 16) |
| `eligibility_state` | `ml_item_state` (ENG-27) |

`source_of(kind)` refuses any other kind. **There is no event source switch**: no
switch date, no `spans`, no `read_switched` (a test asserts they are gone).

**The collections read** (`reco/config.PLATFORM_COLLECTIONS`) are exactly DB-02's
13 (DS-017 v2.5 §7): `users`, `businessregisters`, `posts`, `postevents`,
`follows`, `followers`, `orders`, `carts`, `products`, `productvariants`,
`categories`, `recommendationrequests`, `rec_serve_log`. The old
`recommendationimpressions`, `recommendationclicks` and `contentfeedbacks`
readers are removed: they aren't on DB-02's list. `followers` and
`rec_serve_log` have names but no record kind yet (ENG-08 and ENG-29 add them).

**Native event map:** `reco/platform/native_events.py`, `NATIVE_EVENTS`: the 26
`postevents` types of sheet 4, each with its E code (or none, where the sheet
gives "—"), whether a Wave 1A model scores it, and the type it undoes:

| E code | Native types |
|---|---|
| E2 | `impression` (measurement only; M1 does not use it) |
| E3 | `click`, `product_click` (older builds) |
| E4 | `add_to_cart` (scored); `remove_from_cart` (capture only) |
| E5 | `purchase` (the order is the authority, X-18) |
| E9 | `like`, `comment`, `share`, `save`, `follow`, and the undos `unlike`, `uncomment`, `unsave`, `unfollow` (scored); `repost` (capture only) |
| E13 | `feedback` (`not_interested`, `hide`, `report`, `mute_author`) |
| none | `view` (scored: M1 qualified view at `dwell_ms` ≥ 3,000); capture only: `product_view`, `video_play`, `video_complete`, `variant_select`, `checkout_start`, `wishlist_add`, `wishlist_remove`, `search` |

`PostEventRecord` carries `event_type` (lower case), `event_code` and `scored`.

**Surfaces** (F02): `SURFACES` maps `home_for_you` → `feed`, `product_detail` and
`cart` → `product`. Any other native surface is not an engine surface (`None`);
the native value is kept as `native_surface`.

**Served lists:** `parse_served_list` reads a `recommendationrequests` row.
`is_fallback` is true when `policy_id` doesn't start with `cfg` (F06: engine
lists carry `cfg…`, fallback lists keep the platform's own policy id). On dev,
12 of 12 rows are fallback lists.

### 6. Served item identity: built

`records.card_identity(item_id, item_type, post_id, product_id, surface)`
returns `(card, post_id, product_id)` (X-16, F10, F75; ENG-29 item 6):
- the card is `item_id`; with no `item_id`, the post, else the product;
- on a feed list, `item_type` `product` with a post id is **a post card showing a
  product**: `post_id` is the card and `product_id` stays the product, so a post
  id is never read as a product id;
- on the product surface, `item_type` `product` is a product card.

**Choice:** using the post (then the product) as the card when `item_id` is
missing. Rule it satisfies: post and product ids are never mixed.

**Question 4, answered 1 Oct 2026** (`Tracing/REALIGNMENT_v1.3.md`): the
`item_type` for a post card showing a product is `product`, with the post id as
`item_id` and `post_id` and the product as `product_id` (Capture Register F10,
X-16; confirmed by real feed clicks on dev). That is the case this function
reads. ENG-06's E1 record now writes engine lists the same way, and ENG-08's
final recheck tells such a card by its `post_id` (`6c3ef46`).

### 7. Positions: built

`PostEventRecord.position` is the position on the event, kept as an integer
(non-integers read as `None`). ENG-29 item 7 replaces the delivered-list
`engine_position`: SOCO_BE never drops or renumbers engine lists, so the event's
position is the engine's position.

### 8. Undo and own posts: built

`PostEventRecord` keeps `undone_at`, `undo_of` and `is_self` as stored (X-18).
`NATIVE_EVENTS[...].undoes` names the type each undo reverses (`unlike` → `like`,
`uncomment` → `comment`, `unsave` → `save`, `unfollow` → `follow`,
`wishlist_remove` → `wishlist_add`). **Nothing is filtered:** each model applies
its own rule (ENG-10, ENG-16, ENG-17, ENG-21).

### 9. Ignored platform data: built

`reco/config.IGNORED_PLATFORM_DATA` lists the three names v1.3 gives and where
each exception is allowed:
- `addNew_Interest`: never;
- `interestScores`: only in `reco/fallback` (the old score in the ladder);
- `feedScore`: never in the engine (SOCO_BE's fallback ordering only).

A test scans every string literal in `reco/` code (not docstrings or comments)
and fails if one is used outside its allowed place. `userevents` was dropped from
the list: the v1.3 row no longer names it.

### 10. Post-page impressions: built

`PostEventRecord.is_page_visit` is true for an `impression` with surface
`post_detail` (X-05, `native_events.PAGE_VISIT_SURFACE`). Its engine `surface` is
`None`, so it can't be read as a feed or product card impression. Working out
"which cards were seen" from these copies belongs to the models that use it.
On dev, 0 of 146 rows are page visits.

**Fix, 1 Oct 2026 (audit, `2b585af`):** the surface is compared ignoring case and
surrounding spaces (`str(native_surface).strip().lower()`), as `engine_surface`
already did for feed and product surfaces, so `Post_Detail` is a page visit too.
Build List v1.3 ENG-03: "Status fields: compared ignoring case."

**Question 11, answered 1 Oct 2026** (`Tracing/REALIGNMENT_v1.3.md`; Build List
ENG-19, X-05): paging leaves out items **served** to the viewer in the last 24
hours, taken from the engine's own records (ENG-19), and the platform's
`seen_ids` is for measurement. So no ENG-03 change: these records already keep
page visits apart, and nothing here reads `seen_ids` for paging.

### A. Extra: readers that return records: built

`reco/platform/fetch.py`:
- `read_records(settings, kind, query, limit)` reads one platform collection and
  returns parsed records, using the live settings' `category_map` and
  `order_status`. A caller never sees a raw platform field.
- `product_categories(settings)` (part 3).

The same file also holds ENG-04's raw reads for the sync (`read_page_by_id`,
`read_page_by_updated_at`, `read_by_ids`, `read_touched`). They are documented
in `docs/engineering/ENG-04.md`.

### B. Extra: a check script over the real platform: built

`scripts/check_platform_records.py` reads **every** document of every record kind
through the records. Read-only; prints counts only, never personal fields.

Run on dev, 1 Oct 2026:

```
platform soco on nex-dev.cob9whd.mongodb.net (read-only)

kind                        read  failed  time from _id   notes
user                          15       0              0   active 13/15
business                      24       0              0
post                           8       0              0   with a category of the 23 8/8
postevent                    146       0              0   with an E code 127/146, business actor 6/146, with updated_at 0/146, page visits 0/146
follow                        93       0              0   text ids 93/93
order                          8       0              0   with checkout_id 2/8, with tracking_info 8/8, returned 0/8
cart_line                      2       0              0
product                     2011       0              0   category is one of the 23 0/2011
variant                     6029       0              0   in stock 5169/6029
category                     334       0              0   top level is one of the 23 92/334
served_list                   12       0              0   fallback lists 12/12

PASS: 0 document(s) could not be read
```

Re-run 1 Oct 2026 after the audit: the same counts, plus a line ENG-29 added for
the 12th kind:

```
serve_log                      -       -              -   collection 'rec_serve_log' does not exist yet
```

**8,682 documents, 0 failed.** (The 29 Sep run read 8,741: the 59 documents of
the two removed old collections, `recommendationimpressions` and
`recommendationclicks`, are no longer read; `recommendationrequests` is now read
as `served_list`.)

---

## 3. Configuration reference

No new environment variables. In `reco/config`:
- `PLATFORM_COLLECTIONS`: record kind → platform collection; now DB-02's 13.
- `IGNORED_PLATFORM_DATA`: three entries (v1.3).

Settings read (v1.3 Settings sheet, *Lists*, defined in `reco/config/tunables.py`):
- `lists.category_map`: platform category → one of the 23 (ENG-29 item 1). Empty
  today.
- `lists.order_status`: the stored order-status values (`Delivered`,
  `Cancelled`, `Rejected`, `Return Requested`, `Returned`).

---

## 4. Platform data, 1 Oct 2026 (dev, read-only)

| Finding | Effect | Owner |
|---|---|---|
| **No product's category is one of the 23** (0 of 2,011); only 92 of 334 categories have a top level among the 23 | Every product is dropped from category scoring until mapped. DB-07 is now *Not needed*: the fix is the settings category map | **Allen, ENG-29 item 1** |
| `products.categoryPathIds` present on 0 of 2,011 | `basicInfo.categoryId` is used instead (part 3) | Platform schema v4 |
| `postevents.updated_at` on 0 of 146; `orders.updated_at` on 3 of 8 | Parsed as stored; the sync's incremental read needs it | APP-12 (ENG-04) |
| `orders.tracking_info` on 8 of 8 | Order history reads | – |
| 6 of 8 orders have no `checkout_id` | Older orders; M5 method two uses only orders with one | DB-11 clears test data |
| `rec_serve_log` doesn't exist; `followers` is empty | Nothing to read yet | APP-15; Aravinth |

---

## 5. Tests

`tests/test_platform_records.py` (60 tests):
- **The check's four cases:** `test_follow_with_text_ids`,
  `test_postevent_from_a_businessregister_actor`,
  `test_a_product_post_on_a_platform_feed_list`,
  `test_order_with_history_and_a_return_request`.
- **One of each record type:** user, business, post (compliance, categories),
  product (via `categoryPathIds` and the tree), variant, cart line (first list),
  served list (fallback by `policy_id`).
- **Native map:** 26 types; E codes and scored flags; surfaces; a product card on
  the product surface; a post-page impression; undo, dwell and own-post fields.
- **Orders:** who cancelled; the return value comes from the settings.
- **Helpers:** time from `_id`; status ignoring case; actor kind; categories by
  name, then the category map, never the legacy map.
- **Sources:** each kind has one source; no event source switch; the collections
  are exactly DB-02's list.
- **Ignored data:** the scan in part 9.
- **Against a throwaway database:** `read_records` parses follows, products and
  orders it reads.

**Result on 1 Oct 2026 (laptop):** `tests/test_platform_records.py` **60 passed,
0 failed, 0 skipped** (59 unit, 1 database). Checklist section 3 (3.1–3.5) passes.

**Re-run 1 Oct 2026 after the audit fixes:** `tests/test_platform_records.py` **60
passed** again (with ENG-02's and ENG-04's files, 181 passed); whole suite after
`964f4ec`: **634 passed, 1 skipped**. The new fields (`target_id`, `target_type`,
`restriction_level`, `BlockRecord`) are tested in `tests/test_eligibility.py`
(ENG-08), where they are used.

---

## 6. Runbook

```bash
.venv/bin/python scripts/check_platform_records.py        # every real platform document, read-only
.venv/bin/python -m pytest tests/test_platform_records.py -v
bash scripts/run_checklist.sh                              # section 3 is ENG-03
```

---

## 7. Open

| Open item | Needs |
|---|---|
| The M1 refresh (`reco/platform/readers.py`) still reads **live `postevents`** on the platform through its demo-era reader, not the engine's copy (`ml_events`) and these records. Confirmed in the 1 Oct audit | **Done 14 Oct 2026** (ENG-10): on the live profile M1 reads the engine copies through these records (`reco/slots/interest/copies.py`); the demo reader serves only `DATA_PROFILE=demo` |
| Category map covering every category in use; daily unmapped report | **ENG-29** item 1 |
| ~~Status spelling map; `followers` and `rec_serve_log` record kinds~~ Done: ENG-29 (`status_spellings`, `serve_log`) and ENG-08 (`BlockRecord`) | — |
| The `followers` block shape (`BlockRecord` assumes `userId` blocks `followerId`, `status: blocked`) | Question 16: Aravinth or the backend code |
| Re-run the check on **test**, then mark Passed | The test server |

---

## 8. Files changed

| File | Change |
|---|---|
| `reco/platform/records.py` | 11 record kinds and parsers; actors, opaque ids, `card_identity`, order history, returns, `cancelled_by`, `status_is` (rewritten 1 Oct). 1 Oct audit: `target_id`/`target_type`, `restriction_level`, `BlockRecord`/`parse_block`; page visit ignores case |
| `reco/platform/fetch.py` (1 Oct, ENG-08) | `read_blocks` |
| `reco/platform/native_events.py` | New 1 Oct: sheet 4 map, surfaces, page-visit surface |
| `reco/platform/sources.py` | One source per kind; switch removed (1 Oct) |
| `reco/platform/fetch.py` | `read_records`, `product_categories`; `read_switched` removed (1 Oct); ENG-04's sync reads |
| `reco/platform/ids.py` | `maybe_str`, `as_utc`, `time_of` |
| `reco/platform/categories.py` | `canonical_name`, `post_categories`, `ProductCategoryIndex`; category map, `categoryPathIds` (1 Oct) |
| `reco/config/__init__.py` | `PLATFORM_COLLECTIONS` = DB-02's 13; `IGNORED_PLATFORM_DATA` |
| `scripts/check_platform_records.py` | The check over real data |
| `scripts/run_checklist.sh` | Section 3 |
| `tests/test_platform_records.py` | Rewritten 1 Oct |

## 9. Demo

The live demo script, in plain language, is `obsidian/Demos/Demo - ENG-03.md`.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks,
with those of every other finished item. It prints PASS/FAIL per line and cleans
up after itself.
