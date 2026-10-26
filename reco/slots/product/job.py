"""M5 product ranking, the nightly job. ENG-17.

    python -m reco.jobs product_ranking

Reads the platform's products, variants, sellers and carts (reco.platform.fetch)
and the engine's copies of postevents (clicks and add-to-carts) and orders; works
out both methods; writes each method as one ENG-07 batch into ml_product_scores.
Requests read only the batch marked current (reco.ranking.products).

What is scored (Build List v1.4 ENG-17: "score every sellable product"): the
products that pass E-07 (products.status Activate, availability.inStock, an active
variant with quantity - reservedStock above 0) and whose seller passes E-08 and
E-09 -- the request applies every ENG-08 rule again, with the viewer's own. Every
product the platform has gets a list (a product out of stock can still be viewed).

    popularity     clicks on the product's cards (click, product_click) plus add_to_cart
                   rows, by product_id, last 30 days, from the engine's copy of
                   postevents; undone actions and test accounts left out
    method one     reco.slots.product.similarity, the top product.stored_per_product
                   (100) per viewed product
    method two     reco.slots.product.bought_together over product.basket_source:
                   "cart" (the platform's carts, labelled intent) until APP-22 passes,
                   then "checkout" (the engine's order copies by checkout_id, leaving
                   out Cancelled and Rejected; incognito orders count). Test accounts'
                   carts and orders are left out
    step 2 lists   per top-level category, the sellable products most popular first
                   (ties: newest, then id), the top product.stored_per_category (200),
                   written into both batches
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from reco.config import Settings, live
from reco.config.accounts import test_account_ids
from reco.eligibility.rules import account_rule, product_is_sellable
from reco.jobs.batches import run_batch
from reco.platform import fetch
from reco.platform.ids import as_utc
from reco.slots.product import bought_together as method_two
from reco.slots.product import similarity as method_one
from reco.store import product_scores as store
from reco.store.scores import utc_now

logger = logging.getLogger("reco.job")

#: ENG-17: "clicks on the product's cards plus add-to-carts, last 30 days".
POPULARITY_DAYS = 30
_IDS_PER_READ = 500


def data_window(anchor: datetime) -> dict[str, datetime]:
    return {"from": anchor - timedelta(days=POPULARITY_DAYS), "to": anchor}


def methods() -> tuple[str, str]:
    slot = live.current().slots.product_ranking
    return slot.method_one, slot.method_two


async def _read_chunked(settings: Settings, kind: str, ids: list[str]) -> list[Any]:
    found: list[Any] = []
    for start in range(0, len(ids), _IDS_PER_READ):
        found += await fetch.read_where(settings, kind, "_id", ids[start:start + _IDS_PER_READ])
    return found


async def _sellers(settings: Settings, ids: set[str]) -> dict[str, Any]:
    """A seller may be a user or a business account (as in reco.eligibility.apply)."""
    wanted = sorted(i for i in ids if i)
    users, businesses = await asyncio.gather(_read_chunked(settings, "user", wanted),
                                             _read_chunked(settings, "business", wanted))
    return {**{u.user_id: u for u in users}, **{b.business_id: b for b in businesses}}


def popularity_counts(rows: list[dict[str, Any]], *, anchor: datetime, tests: set[str]) -> tuple[Counter, Counter]:
    """Clicks plus add-to-carts per product, and what was skipped."""
    counts: Counter = Counter()
    skipped: Counter = Counter()
    for row in rows:
        at, user = as_utc(row.get("created_at")), str(row.get("user_id") or "")
        if at is None or at > anchor:
            skipped["no_time_or_future"] += 1
        elif user.lower() in tests:
            skipped["test_account"] += 1
        else:
            counts[str(row["product_id"])] += 1
    return counts, skipped


def category_lists(items: list[method_one.ProductItem], limit: int) -> dict[str, list[method_one.ProductItem]]:
    """Fallback step 2: per top-level category, most popular first (ties: newest, then id)."""
    by_category: dict[str, list[method_one.ProductItem]] = defaultdict(list)
    for item in items:
        if item.category_id:
            by_category[item.category_id].append(item)
    return {cat: sorted(found, key=lambda i: (-i.popularity, -i.created_ts, i.product_id))[:limit]
            for cat, found in by_category.items()}


async def compute(settings: Settings, anchor: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Both methods' lists and the step-2 lists, and the counts to report."""
    tunables = live.current()
    product = tunables.product
    weights = product.weights.model_dump()
    tests = test_account_ids(anchor.date())
    report: dict[str, Any] = {}

    # --- products, their variants and sellers ---------------------------------------
    products = await fetch.read_records(settings, "product")
    variants: dict[str, list[Any]] = defaultdict(list)
    for variant in await fetch.read_records(settings, "variant"):
        if variant.product_id:
            variants[variant.product_id].append(variant)
    sellers = await _sellers(settings, {p.seller_id for p in products if p.seller_id})
    not_sellable: Counter = Counter()
    sellable_ids: set[str] = set()
    for p in products:
        if not product_is_sellable(p, variants[p.product_id]):
            not_sellable["E-07"] += 1
        elif (rule := account_rule(sellers.get(p.seller_id or ""))) is not None:
            not_sellable[rule] += 1
        else:
            sellable_ids.add(p.product_id)

    # --- popularity --------------------------------------------------------------------
    rows = await store.read_popularity_rows(settings, anchor - timedelta(days=POPULARITY_DAYS))
    counts, skipped = popularity_counts(rows, anchor=anchor, tests=tests)
    items = {p.product_id: method_one.ProductItem.of(p, variants[p.product_id], counts.get(p.product_id, 0))
             for p in products}
    sellable = [items[pid] for pid in sorted(sellable_ids)]
    percentiles = method_one.popularity_percentiles({i.product_id: i.popularity for i in sellable})

    # --- method one ----------------------------------------------------------------------
    similar = {
        pid: method_one.top_similar(item, sellable, percentiles, weights=weights,
                                    price_band=product.price_band_fraction, limit=product.stored_per_product)
        for pid, item in sorted(items.items())
    }

    # --- method two ----------------------------------------------------------------------
    source = product.basket_source
    if source == "checkout":
        statuses = tunables.lists.order_status
        orders = [o for o in await store.read_basket_orders(settings)
                  if str(o.get("buyer_id") or "").lower() not in tests]
        baskets, basket_skipped = method_two.checkout_baskets(orders, left_out=(statuses.cancelled, statuses.rejected))
        report["incognito_orders"] = sum(1 for o in orders if o.get("is_incognito"))
    else:
        lines = [line for line in await fetch.read_records(settings, "cart_line")
                 if (line.user_id or "").lower() not in tests]
        baskets, basket_skipped = method_two.cart_baskets(lines)
    together, pairs = method_two.bought_together(
        baskets, strength=product.lift_strength, min_co_purchases=product.min_co_purchases,
        limit=product.stored_per_product, allowed=sellable_ids)

    categories = category_lists(sellable, product.stored_per_category)
    report.update(
        products=len(products), sellable=len(sellable), not_sellable=dict(not_sellable),
        popularity_rows=len(rows), popularity_skipped=dict(skipped), products_with_popularity=len(counts),
        method_one_lists=sum(1 for v in similar.values() if v),
        basket_source=source, label=method_two.LABELS[source], baskets=pairs.total,
        baskets_skipped=dict(basket_skipped),
        pairs_seen=len(pairs.pairs), pairs_kept=sum(1 for n in pairs.pairs.values() if n >= product.min_co_purchases),
        method_two_lists=len(together), top_level_categories=len(categories),
    )
    return {"similar": similar, "together": together, "categories": categories}, report


def _category_rows(categories: dict[str, list[method_one.ProductItem]], common: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"_id": f"{common['job_run_id']}:{store.CATEGORY_POPULAR}:{cat}:{rank}", "list": store.CATEGORY_POPULAR,
         "context_product_id": None, "category_id": cat, "product_id": item.product_id,
         "score": float(item.popularity), "rank": rank, **common}
        for cat, found in categories.items() for rank, item in enumerate(found, start=1)
    ]


def method_one_rows(lists: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"_id": f"{common['job_run_id']}:{store.SIMILAR}:{viewed}:{rank}", "list": store.SIMILAR,
         "context_product_id": viewed, "category_id": None, "product_id": s.product_id, "score": s.score,
         "rank": rank, "components": s.components, **common}
        for viewed, found in lists["similar"].items() for rank, s in enumerate(found, start=1)
    ] + _category_rows(lists["categories"], common)


def method_two_rows(lists: dict[str, Any], common: dict[str, Any], label: str, source: str) -> list[dict[str, Any]]:
    return [
        {"_id": f"{common['job_run_id']}:{store.BOUGHT_TOGETHER}:{viewed}:{rank}", "list": store.BOUGHT_TOGETHER,
         "context_product_id": viewed, "category_id": None, "product_id": p.product_id, "score": p.score,
         "rank": rank, "lift": p.lift, "co_purchases": p.co_purchases, "label": label, "basket_source": source,
         **common}
        for viewed, found in lists["together"].items() for rank, p in enumerate(found, start=1)
    ] + _category_rows(lists["categories"], common)


async def run(settings: Settings, anchor: datetime | None = None) -> dict[str, Any]:
    """Compute once, then write each method as its own batch (each becomes current
    only once complete)."""
    anchor = anchor or utc_now()
    tunables = live.current()
    await store.ensure_product_score_indexes(settings)
    lists, report = await compute(settings, anchor)
    window = data_window(anchor)
    one, two = methods()
    source = tunables.product.basket_source
    records = {}
    for method in (one, two):
        async def work(job_run_id: str, method: str = method) -> int:
            common = {"method": method, "slot": store.SLOT, "job_run_id": job_run_id,
                      "model_version": settings.model_version, "config_version": tunables.config_version,
                      "computed_at": utc_now(), "data_window": window, "confidence": None}
            rows = (method_one_rows(lists, common) if method == one
                    else method_two_rows(lists, common, method_two.LABELS[source], source))
            return await store.write_product_scores(settings, rows)

        records[method] = await run_batch(settings, job=store.JOB, slot=store.SLOT, method=method,
                                          collection=store.COLLECTION, data_window=window, work=work)
    report["batches"] = {m: {"job_run_id": r["_id"], "rows": r["rows_written"]} for m, r in records.items()}
    return report
