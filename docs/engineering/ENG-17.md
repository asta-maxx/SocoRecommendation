# ENG-17: Product ranker, both methods (M5)

| | |
|---|---|
| **Owner** | Allen |
| **Step** | Step 3 (within 17 working days) |
| **Waits on** | ENG-03, ENG-05, ENG-07, ENG-08 (all built). Method two's checkout version waits on APP-22 (the basket test, "Built, verification pending": ENG-23 V5) |
| **Needed by** | ENG-22 (checks 6, 7, 9, 10, 11), ENG-23 (T6, A5) |
| **Status** | **Built** (17 Oct 2026, dev). Becomes Passed when "Both methods serve on test" is shown on the test server |
| **Spec** | Build List v1.4 ENG-17; Settings "M5 product" (weights 0.35/0.20/0.15/0.20/0.10, lift strength 10, at least 2 co-purchases, price band 30%, no blend); ENG-05 (slot `product_ranking`); ENG-07 (batches); ENG-08 (filters); ENG-22 checks 6, 7, 9, 10, 11; DS-017 v2.6 §4.2, §4.3, §6.4 ("M5 bought together: orders sharing a checkout_id, leaving out Cancelled and Rejected orders. Incognito orders count; no buyer is named"); SDA v1.7 (`ml_product_scores`, product detail and cart); Kala's answers of 16 Oct (Q7: the cart) |

## 1. What the item requires

The Build List row in full is in `Tracing/pack_text/` (`grep "^ENG-17 |"`). In short:

- **Method one, attribute similarity.** For the viewed product, every sellable product scores: same category 0.35; on the viewed product's `crossSellProducts` 0.20; price band (lowest `salePrice` among active variants within ±30% of the viewed product's) 0.15; popularity (clicks on the product's cards plus add-to-carts, last 30 days, as a percentile; add-to-carts only from `add_to_cart` rows in the engine's copy of postevents, by `product_id`) 0.20; same seller 0.10. No ratings. A missing component is left out and the weights rescale.
- **Method two, bought together.** lift = P(A and B) / (P(A) × P(B)) over orders sharing a `checkout_id`, leaving out Cancelled and Rejected; adjusted lift = (n × lift + 10) / (n + 10), n = co-purchases; a pair needs at least 2. Until APP-22 passes, over cart contents, labelled "intent". Incognito orders count; no buyer is named.
- **When method two has nothing:** 1. the method-one list for that product; 2. eligible products in the same top-level category, most popular first; 3. eligible products, newest first; the step is recorded; never an empty list.
- **Always excluded:** the viewed product; on the cart surface every product in the cart.
- **Serving:** the list of the user's ENG-05 method; on product detail the context is the viewed product, on the cart the most recently added item. Both methods nightly into `ml_product_scores`; a request reads the stored list, applies the filters, and returns exactly `limit`, or fewer only when fewer eligible products exist.

*How to check it is done:* "Both methods serve on test. Hand-computed lift for three pairs matches."

## 2. What was built

### 1. Method one, attribute similarity: `reco/slots/product/similarity.py` (pure)

- `ProductItem.of(product, variants, popularity)`: seller (`products.createdBy`), top-level category (`category_id`, `categoryPathIds[0]`), own category (`leaf_category_id`, new on `ProductRecord`: `basicInfo.categoryId`, else the last of `categoryPathIds`), the cross-sell ids, the lowest `salePrice` among **active** variants (`lowest_active_price`), the popularity count, the creation time.
- `components(viewed, candidate, popularity, price_band)`: `category` 1/0 (same own category), `cross_sell` 1/0, `price_band` 1/0 (`|p − p₀| ≤ 0.30 × p₀`, the edge included), `popularity` (percentile), `same_seller` 1/0. `None` = missing.
- `weighted(parts, weights)` = Σ w × value / Σ w over the components present (the row's rescaling).
- `popularity_percentiles(counts)`: `(below + (equal − 1)/2) / (n − 1)` over the sellable products, ties counted half, one product 0.5 (the same formula as ENG-15 and ENG-16; `reco.slots.promoter.score.percentile_ranks`).
- `top_similar(viewed, sellable, percentiles, weights, price_band, limit)`: the best `limit` (product.stored_per_product, 100), never the viewed product; ties by popularity, then id.

### 2. Method two, bought together: `reco/slots/product/bought_together.py` (pure)

- `checkout_baskets(orders, left_out=(Cancelled, Rejected))`: one basket per `checkout_id` of the engine's order copies; statuses compared ignoring case (`status_is`); Returned and every other status count; incognito orders count. `cart_baskets(lines)`: one basket per cart owner (`carts` lines by `user_id`). A basket is a set of product ids: no buyer is kept.
- `lift(n_ab, n_a, n_b, N)` = (n_AB/N) / ((n_A/N)(n_B/N)); `adjusted_lift(n, lift, 10)` = (n × lift + 10) / (n + 10).
- `bought_together(baskets, strength=10, min_co_purchases=2, limit, allowed)`: every pair with n ≥ 2; each product's partners by adjusted lift, highest first (ties: more co-purchases, then id); partners must be sellable (`allowed`); any product can be the viewed one.
- `LABELS = {"cart": "intent", "checkout": "checkout"}`: every method-two row carries `label` and `basket_source`.
- **The switch (APP-22):** the setting `product.basket_source`, `"cart"` (default) until APP-22 passes (ENG-23 V5), then `"checkout"`. A setting, so no deploy.

### 3. The fallback order and the step: `reco/slots/product/ladder.py` (pure)

`ladder(method)`: bought_together → own list, `product_step_1`, `product_step_2`, `product_step_3`; attribute_similarity → own list, `product_step_2`, `product_step_3`. `fill` / `take` fill a list from sources in order, deduplicated, skipping exclusions, until it holds what the request needs. `Filled.fallback_step`: null when the method's own list filled the page, else the first fallback step that added a product; `method_served`: the own list added something (SD-23).

### 4. Always excluded

The context product and every product in `Viewer.in_cart` (read from `carts` with the viewer's follows and blocks, `reco.eligibility.apply.viewer_context`, Kala Q7) are skipped by every source, on every product request. The pack's surface is `product` for both product detail and the cart (DS-017 F02), so the cart exclusion applies to every product list, as Kala answered.

### 5. The nightly job: `reco/slots/product/job.py` (`python -m reco.jobs product_ranking`, nightly after `promoter`)

- **Reads:** products, variants (`read_records`), sellers (users and businessregisters, `read_where`), carts (`read_records("cart_line")`) through `reco/platform/fetch.py`; the engine's copies of postevents (`click`, `product_click`, `add_to_cart` with a `product_id`, last 30 days, not undone) and orders (`ml_orders`) through `reco/store/product_scores.py`. No new platform reader was needed.
- **Sellable** (scored and listed): E-07 (`product_is_sellable`) and the seller's E-08/E-09 (`account_rule`). Every product the platform has gets a method-one list (an out-of-stock product can still be viewed).
- **Popularity:** clicks + add-to-carts per product; test accounts and future rows left out.
- **Step-2 lists:** per top-level category, sellable products by popularity (ties newest, then id), the top `product.stored_per_category` (200).
- **Writes:** each method as one ENG-07 batch (`run_batch`, job `product_ranking`, slot `product_ranking`, methods from `slots.product_ranking`). Method one's batch: `similar` lists + `category_popular` lists; method two's: `bought_together` lists + `category_popular` lists (so each batch answers its own requests whole).

### 6. The store: `reco/store/product_scores.py`

One row per (list, rank): `list` (`similar`, `bought_together`, `category_popular`), `context_product_id` or `category_id`, `product_id`, `score`, `rank`, `components` (method one) or `lift`, `co_purchases`, `label`, `basket_source` (method two), and on every row `method`, `slot`, `job_run_id`, `model_version`, `config_version`, `computed_at`, `data_window`, `confidence` (null: neither method has one) (ENG-07). Indexes: `run_context_rank` (job_run_id, context_product_id, rank), `run_category_rank` (job_run_id, category_id, rank), `method_run` (method, job_run_id); created by `writers.ensure_indexes`. `current_batch(settings, method, now, hours)` returns the current batch, or none when it is older than `interest.stale_after_hours` (48, ENG-22 check 10). Writes only through `writers._collection`.

### 7. The request: `reco/ranking/products.py`

`product_candidates(settings, page, limit, context_item_id, user_id, request_id, assignment)`: reads the viewer's context and the current batch(es) at once; fills the list from the ladder's sources: the stored list(s) by rank (`read_product_list`), step 2 (the context product's `category_id` from the platform, then `read_category_list`), step 3 (`fetch.read_newest`, within ENG-06's 1,000-row scan window). Every product passes `eligible_products` (E-01 to E-12) before it takes a place. Like the feed, it fills through the end of the page plus one page more, so ENG-06's recheck (`serving.page_after_recheck`) can replace a product that fails at the last moment; the page is then exactly `limit`, or fewer only when fewer eligible products exist. Returns `serving.Built` with `fallback_step` and `detail` (ordering `eng17_product_ranker`, steps used and how many each added, `method_served`, the batch read and why, and the `label` for bought_together).

### 8. Wiring: `reco/api/recommendations.py`

The product surface now calls `product_ranker.product_candidates` with the user's `product_ranking` assignment; the feed is unchanged (`serving.interim_candidates`). The response's `fallback_step` on the product surface is the product ranker's; the E1's `slot_methods` entry for `product_ranking` carries `fallback_step`, `method_served`, `steps_used`, `batch` and `label`; its `ordering` is `eng17_product_ranker` (the feed keeps `interim_newest_first`). `is_exploration` stays false on the product surface.

**Where the pack is silent (decided 17 Oct 2026):**

| Decision | The rule it must satisfy |
|---|---|
| Method one's "same category" is the product's own category (`basicInfo.categoryId`, else the last of `categoryPathIds`); the top-level category (`categoryPathIds[0]`) is step 2's | The row says "same category" for method one and "same top-level category" for step 2 |
| A component is **missing** when: category, either product has none; cross-sell, the viewed product's list is empty (on dev every list is empty); price band, either product has no active variant with a price above 0; same seller, either has no seller. Popularity is never missing (a count of 0 is a value) | "A component missing for a product is left out, and the weights rescale" |
| Price band is 1 or 0, the edge included | "within ±30% of the viewed product's" |
| Popularity counts rows (clicks + add-to-carts), test accounts left out; `product_click` counts as a click (sheet 4: the older builds' click) | "clicks on the product's cards plus add-to-carts, last 30 days, as a percentile" |
| A cart basket is one owner's current cart (`carts` lines by `user_id`); a product counts once per basket; N counts every basket with a product, including one-product baskets | "compute it over cart contents instead"; P(A) is a share of all baskets |
| Test accounts' carts and orders are left out of the baskets | ENG-29 item 3 (test accounts never count) |
| A short own list is filled by the next steps; method one with no list (a product newer than the batch, or no batch) takes steps 2 and 3 | "returns exactly limit items, or fewer only when fewer eligible products exist"; "never gets an empty list" |
| `fallback_step` names: `product_step_1`, `product_step_2`, `product_step_3`; null when the own list filled the page; otherwise the first fallback step that added a product (all steps used are on the E1) | DS-017 §4.2: "string or null"; "record which step was used" |
| A batch older than `interest.stale_after_hours` (48) is not read (the setting ENG-09 uses) | ENG-22 check 10 |
| Stored per product 100, per category 200 (new settings, ranges 50–500 and 50–1,000) | A page plus a spare page at `limit` 50 |
| Step 2's popularity is method one's (clicks + add-to-carts, 30 days); ties newest, then id | "most popular first" |
| Lists are kept only for sellable partners; the request re-checks every rule with the viewer's own (blocks, mutes, dismissals, own items) | ENG-08: before scoring and again on the final list |

## 3. Configuration

New in `[product]` (`reco/config/tunables.py` `Product`, `settings/engine.toml`), none on the pack's Settings sheet: `stored_per_product` (100, 50–500), `stored_per_category` (200, 50–1,000), `basket_source` (`"cart"` | `"checkout"`, default `"cart"`). Existing: `product.weights.*`, `product.lift_strength` (10), `product.min_co_purchases` (2), `product.price_band_fraction` (0.30), `slots.product_ranking` (`attribute_similarity`, `bought_together`, split 50), `interest.stale_after_hours` (48), `lists.order_status`, `lists.test_accounts`.

## 4. Tests

`tests/test_product_ranker.py`, 28 (27 unit, 1 MongoDB):

- Method one: the Settings sheet's values; every component and the score by hand (including the band's edge and rescaling over 0.65); missing components; the lowest active price; percentiles with ties; never the viewed product, the best kept in order; popularity counts (test accounts, future rows); step-2 lists by top-level category.
- Method two: **hand-computed lift for three pairs** (A&B 1.25 → 55/52, A&C 1 → 1, C&D 4/3 → 19/18, ten baskets); the at-least-2 rule (three pairs seen once give nothing; E has no list); sellable partners and the cap; checkout baskets (Cancelled and Rejected out, ignoring case; Returned in; incognito in; no checkout_id skipped); cart baskets; rows labelled intent, no buyer field.
- The ladder: the order for each method; the step recorded; dedupe and exclusions.
- The request (reads stubbed): the own list first; method two falling back to method one with `product_step_1` (check 9); then category, then newest; method one taking steps 2 and 3; no batch; **the context product and the cart never appear in any step** (check 11); the filters on every step; exactly `limit` on pages 1 and 2, fewer only when fewer exist.
- The request path: the product surface's response and E1 report the step, label and steps used. The job is in `JOBS` and nightly after `promoter`.
- **MongoDB, end to end:** eight products (one out of stock), carts, clicks and add-to-carts; the job writes two current batches; out-of-stock never listed; method-two rows labelled intent with A&B = (3 × 1.5 + 10)/13 and A&C = 1 by hand; B&D seen once gives no list; method one's top for A is B; step 2's order by popularity; a method-two user viewing A (C in the cart) gets B first and 5 products, never A or C, `product_step_1` recorded; viewing E (no pair) a full list from step 1; a method-one user gets its own list with no fallback; a batch made 49 hours stale falls to `product_step_3`; with `basket_source = "checkout"` the pairs come from checkouts (Cancelled left out, incognito counted), labelled checkout.

`tests/test_recommendations.py`: the `served` fixture now also stubs `product_ranker.product_candidates` (the product surface no longer calls `interim_candidates`); no assertion changed. `test_a_product_list_leaves_out_the_context_product` (MongoDB) still passes unchanged: with no batch, step 3 (newest first) gives the same list.

Results, 17 Oct 2026: unit suite **791 passed, 1 skipped** (764 before; +27); MongoDB suite **73 passed** (on Atlas, throwaway `reco_test_<pid>` databases), including this item's end-to-end test and ENG-06's unchanged product-list test.

**Dev, 17 Oct 2026** (synced into a throwaway engine database, `reco_eng17_check`, dropped afterwards; 47,385 postevents, 726 orders, 51 return requests; reconciliation passed): 263 products, **247 sellable** (7 E-07, 9 seller E-08); 1,328 click/add-to-cart rows (all `product_click`; no `add_to_cart` rows exist on dev yet), 92 products with popularity; **263 method-one lists**, 26,547 rows; carts: **51 baskets** (labelled intent), 104 pairs seen, **1 pair with 2 or more**, so **2 method-two lists**, 249 rows (with the 247 step-2 rows, 20 top-level categories); 19 s. Checkout baskets (computed, not written): 625 baskets (65 Cancelled/Rejected orders left out, 9 incognito orders counted), 41 pairs seen, **0 with 2 or more**. Requests (limit 10, laptop to Atlas): both methods returned 10 products, never the context product; method one `fallback_step` null; method two `product_step_1` (one with its own list adding 1 and step 1 the rest, one with no pair); 295–469 ms over the laptop link (the 200 ms target is measured on the test server).

## 5. Runbook

```bash
python -m reco.jobs product_ranking
python -m pytest -q tests/test_product_ranker.py            # unit
python -m pytest -q -m mongo tests/test_product_ranker.py   # end to end
```

To switch method two to checkouts once APP-22 passes: set `basket_source = "checkout"` in `[product]`; the next nightly run writes checkout lists labelled `checkout`.

## 6. Open

| What | Waits on |
|---|---|
| Switch to checkout baskets | APP-22 verified (ENG-23 V5) |
| "Both methods serve on test" | The test server |
| ENG-22's script (checks 6, 7, 9, 10, 11 are unit- and MongoDB-tested here) | ENG-22 |
| Kala/Nisha to confirm the decisions in §2 (category level, the cart basket, the step names, filling a short own list) | Kala, Nisha |

## 7. Files changed

| File | Change |
|---|---|
| `reco/slots/product/` | New: `similarity.py`, `bought_together.py`, `ladder.py`, `job.py` |
| `reco/store/product_scores.py` | New: indexes, reads, batch writes, current batch with staleness |
| `reco/ranking/products.py` | New: the request side |
| `reco/ranking/serving.py` | `Built.fallback_step`, `Built.detail`; docstrings |
| `reco/api/recommendations.py` | The product surface serves ENG-17; its step on the response and E1 |
| `reco/platform/records.py` | `ProductRecord.leaf_category_id` |
| `reco/store/writers.py` | `ensure_indexes` creates `ml_product_scores`' indexes |
| `reco/config/tunables.py`, `settings/engine.toml` | `product.stored_per_product`, `stored_per_category`, `basket_source` |
| `reco/jobs/__main__.py`, `scheduler.py` | Job `product_ranking`, nightly after `promoter` |
| `tests/test_product_ranker.py` | New |
| `tests/test_recommendations.py` | The `served` fixture stubs the product ranker too |
