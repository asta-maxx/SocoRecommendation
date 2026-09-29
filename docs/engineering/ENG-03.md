# ENG-03: Read platform data correctly

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 1 (within 7 working days) |
| **Waits on** | ENG-02 (built) |
| **Needed by** | ENG-08, ENG-09, ENG-10, ENG-12, ENG-16, ENG-17, ENG-21 |
| **Status** | **Built** (29 Sep 2026). The check passed on dev (`Tracing/checks/ENG-03_2026-09-29.md`). Becomes Passed when re-run on test |
| **Spec** | Build List ENG-03; SD-06; AS-12; Capture Register E13/F60–F65, X-02, X-08 |

---

## 1. What the item requires

From the Build List row, the platform module applies these rules everywhere:

1. **IDs:** every id is converted to a 24-character string. `follows` stores ids as text; `users`, `posts` and `postevents` store ObjectIds.
2. **Field names:**

   | Meaning | Field |
   |---|---|
   | Order value | `orders.total_price` |
   | Order time | `orders.created_at` |
   | Post time | `posts.timestamp` |
   | Product time | `products.createdAt` |
   | Event time | `postevents.created_at` |
   | Price | `productvariants.salePrice` (`originalPrice` is the list price) |
   | Stock | `productvariants.quantity − reservedStock` |
   | Seller | `products.createdBy` (also `productvariants.sellerId`) |
   | Post type | `posts.postType` (+ `postTypeDetailed`) |
   | Event type | `postevents.event_type` |
   | User city | `users.city` |
   | Business category | `businessregisters.category` |
   | Follows | `follows.userId` → `followingId`, with `followingReference` |

   A missing time is read from the record's `_id`.
3. **Categories:** a post's categories are matched by name to the 23. A product's `basicInfo.categoryId` is looked up in `categories`, and the first name in its path must be one of the 23. Anything that doesn't map is dropped, not scored.
4. **Status fields:** compared ignoring case.
5. **Where each kind of data is read from:** one place each, so nothing is counted twice.
6. **Event source switch, by day:** the old collections before the ENG-04 switch date, `ml_events` from it. Never both for one day.
7. **Ignored:** `users.addNew_Interest`, `userevents`, the delivered `interestScores` (except as the old score in the ladder), and `feedScore` (except for SOCO_BE's fallback ordering).

**Check:** "Unit tests read one of each record type and return the expected
values, including a follows record with text ids."

---

## 2. What was built, subtask by subtask

Numbered as in the Obsidian note: 1–7 are the Build List's parts, and A–B are extras.

### 1. IDs as text: done

`reco/platform/ids.py` (existing `to_str`, `id_match`) plus a new
`maybe_str(value)` for optional references, which returns `None` for an empty
field. Every record id field is text.

Confirmed on the real data: `follows` stores **text** ids (93 of 93), and
`posts.userId` is text too (DB-11 lists some). Both parse to the same form.

### 2. Field names, and time from `_id`: done

`reco/platform/records.py` has one frozen Pydantic record and one pure
`parse_<kind>(doc)` per kind. **14 kinds:** `user`, `business`, `post`,
`postevent`, `follow`, `order`, `cart_line`, `product`, `variant`, `category`,
`legacy_request`, `legacy_impression`, `legacy_click`, `legacy_content_feedback`.
Each applies the ENG-03 field map above.

**Details beyond the map (choices where the pack is silent):**
- `OrderRecord.return_type`: `"No Return"` / `"No Returns"` read as `None`, as DB-03 asks.
- `UserRecord.date_of_birth` parses `DOB`, which is stored as text.
- User and business times come from `timestamp`.
- Cart lines are timed by `carts.timestamp`.
- The old recommendation collections are timed by `server_ts`.

**Time fallback:** `ids.time_of(doc, *fields)` uses the named field, then the
ObjectId's creation time from `_id` (ObjectId or 24-hex text). Naive times are
taken as UTC.

Records never carry fields ENG-03 ignores (`feedScore`, `interestScores`,
`addNew_Interest`) or anything unneeded (e.g. `users.password`).

### 3. Categories matched by name to the 23: done

`reco/platform/categories.py`:
- **`canonical_name(vocab, label)`** matches by name only, ignoring case and spacing. The legacy map is **not** consulted, even when present: ENG-03 says "by name" and "dropped, not scored". Today the legacy map is empty anyway.
- **`post_categories(...)`** returns the resolved and dropped labels for a post.
- **`ProductCategoryIndex.build(vocab, category_docs)`** maps `categoryId` to the first name of the category's `path` when that name is one of the 23, else `None`. `fetch.product_categories(settings)` builds it from the platform.

### 4. Status compared ignoring case: done

`records.status_is(value, expected)` ignores case and surrounding spaces.
Different words stay different: `products.status` is compared with `'Activate'`
and `posts.Product_status` with `'Activated'`, each separately (E-06, E-07).

### 5. One source per kind of data: done

`reco/platform/sources.py`, `SOURCES`:

| Data | Source |
|---|---|
| order, order_state, cancellation, return | `order` records (orders) |
| view, like, save, comment, share, post_add_to_cart | `postevent` records (postevents) |
| follow | `follow` records |
| add_to_cart_with_list | `ml_events` |
| request, impression, click, content_feedback | switch |

`source_of(kind)` refuses `order_placed`, `order_state_changed` and
`social_interaction`: they're stored in `ml_events` but not read in Wave 1A.
Sources are named by record kind; collection names live only in
`reco/config` (`PLATFORM_COLLECTIONS`).

### 6. The event source switch, by day: done (the date itself comes from ENG-04)

- **`sources.source_of(kind, day, switch_date)`:** `legacy` before the switch date, `ml_events` from it. With no switch date yet, always `legacy`.
- **`sources.spans(start, end, switch_date)`:** splits a window at the switch into half-open spans with no gap or overlap, so a 90-day window across the switch reads part from each.
- **`fetch.read_switched(settings, kind, start, end, switch_date)`:** reads each span from its one source. `ml_events` rows are selected by `event_name`: `recommendation_request`, `recommendation_impression`, `recommendation_click`, `content_feedback`.
- **One parser for both sources:** the new events carry the same field names as the old collections (DS-017 §6.2 against the collections' shapes), so one parser reads both.
- **Days are UTC calendar days (choice).** DS-017 stamps server times in UTC, and the pack doesn't name the day boundary.
- **Where the switch date is stored** is ENG-04's to decide when it records the date. ENG-03 takes it as a parameter.

### 7. Ignored platform data: done

`reco/config.IGNORED_PLATFORM_DATA` lists the four names and where each exception
is allowed. A test scans every string value used in `reco/` code (not docstrings
or comments) and fails if:
- `addNew_Interest`, `userevents` or `feedScore` appear outside `reco/config`;
- `interestScores` appears outside `reco/config` and `reco/fallback`.

### A. Extra: readers that return records: done

`reco/platform/fetch.py`:
- `read_records(settings, kind, query, limit)` reads a platform collection and returns parsed records.
- `read_switched(...)` is described in part 6.

A caller never sees a raw platform field.

### B. Extra: a check script over the real platform: done

`scripts/check_platform_records.py` reads **every** document of every kind
through the records. It's read-only and prints counts only, never personal fields.

Run on dev, 29 Sep 2026:

```
kind                        read  failed  time from _id   notes
user                          15       0              0   active 13/15
business                      24       0              0
post                           8       0              0   with a category of the 23 8/8
postevent                    146       0              0
follow                        93       0              0   text ids 93/93
order                          8       0              0   with checkout_id 2/8
cart_line                      2       0              0
product                     2011       0              0   category is one of the 23 0/2011
variant                     6029       0              0   in stock 5169/6029
category                     334       0              0   top level is one of the 23 92/334
legacy_request                12       0              0
legacy_impression             24       0              0
legacy_click                  35       0              0
legacy_content_feedback        -       -              -   collection 'contentfeedbacks' does not exist yet
PASS: 0 document(s) could not be read
```

---

## 3. Configuration reference

No new environment variables or settings. Two new constants in `reco/config`:
- `PLATFORM_COLLECTIONS`: record kind → platform collection name;
- `IGNORED_PLATFORM_DATA`.

---

## 4. Findings in the platform data (for Aravinth)

| Finding | Effect | Owner |
|---|---|---|
| **No product's category is one of the 23** (0 of 2,011). The top level has 27 names, of which only 4 are among the 23, and no product sits under those 4 | Under ENG-03 every product is dropped as unmappable. M5's category signal and M2/M6/M8 category use can't work until fixed | **DB-07** |
| `contentfeedbacks` doesn't exist, though E13 is reported built (Capture Register) | Feedback before the switch date has nowhere to be read from | Aravinth to confirm |
| 6 of 8 orders have no `checkout_id` | Older orders; M5 method two uses only orders with one | DB-11 clears test data |
| `carts` have no `request_id` | Expected until **DB-05** | DB-05 |

---

## 5. Tests

`tests/test_platform_records.py`:
- **One of each record type**, with documents copying the real shapes. It includes the follows record with **text ids** that the check names, and ObjectId follows reading the same.
- **Helpers:** time from `_id`; naive times as UTC; status ignoring case; by-name category matching (legacy map ignored).
- **Categories:** product categories through the tree, both mapped and unmapped.
- **Sources:** each kind has one source; stored-only events are refused; the switch before, on and after the date, and with no date; a 90-day window split with no gap or overlap.
- **Ignored data:** the scan described in part 7.
- **Against a throwaway database:** `read_records` parses what it reads, and `read_switched` reads a click stored in both places exactly once.

**Result on 29 Sep 2026:** 475 unit tests passed (1 skipped) and 33 database tests passed.

---

## 6. Runbook

```bash
.venv/bin/python scripts/check_platform_records.py        # every real platform document, read-only
.venv/bin/python -m pytest tests/test_platform_records.py -v
```

---

## 7. Open

| Open item | Needs |
|---|---|
| The M1 reader (`platform/readers.py`) still reads through its demo-era path, not these records | **ENG-10**, whose row redefines M1's sources, moves it onto `fetch` / `records` |
| ~~Where the switch date is stored~~ | Done in ENG-04: `ml_measurements` (`measure: event_source_switch`); read with `reco.events.reconcile.switch_date(settings)` |
| Re-run the check on **test**, then mark Passed | The test server |
| Categories (DB-07), `contentfeedbacks`, `checkout_id`, cart `request_id` | Aravinth (§4) |

---

## 8. Files changed

| File | Change |
|---|---|
| `reco/platform/records.py` | New: 14 record kinds, parsers, `status_is` |
| `reco/platform/sources.py` | New: one source per kind; the switch rule |
| `reco/platform/fetch.py` | New: `read_records`, `read_switched`, `product_categories` |
| `reco/platform/ids.py` | `maybe_str`, `as_utc`, `time_of` |
| `reco/platform/categories.py` | `canonical_name`, `post_categories`, `ProductCategoryIndex` |
| `reco/config/__init__.py` | `PLATFORM_COLLECTIONS`, `IGNORED_PLATFORM_DATA` |
| `scripts/check_platform_records.py` | New: the check over real data |
| `tests/test_platform_records.py` | New |

## 9. Demo

The live demo script, in plain language, is `obsidian/Demos/Demo - ENG-03.md`.

**Whole checklist:** `bash scripts/run_checklist.sh` re-runs this item's checks, with those of every other finished item. It prints PASS/FAIL per line and cleans up after itself.
