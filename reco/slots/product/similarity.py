"""M5 method one, attribute similarity: the maths. ENG-17. Pure: no database.

    item  = ProductItem.of(product, variants, popularity_count)
    pct   = popularity_percentiles({product_id: count})
    parts = components(viewed, candidate, price_band=0.30)
    score = weighted(parts, weights)                 # None components left out, weights rescaled
    top   = top_similar(viewed, sellable, pct, weights=..., price_band=..., limit=100)

For the product being viewed, every sellable product is scored (Build List v1.4
ENG-17; Settings "M5 product": weights sum to 1, price band 30%):

    category     0.35  1 when both are in the same category, else 0
    cross_sell   0.20  1 when the candidate is on the viewed product's crossSellProducts list
    price_band   0.15  1 when the candidate's lowest salePrice among its active variants
                       is within +-30% of the viewed product's, else 0
    popularity   0.20  clicks on the product's cards plus add-to-carts, last 30 days,
                       as a percentile among the sellable products (0 to 1)
    same_seller  0.10  1 when both have the same seller (products.createdBy)

Ratings are not used: none exist. A component missing for a product is left out,
and the weights rescale over the components present: score = sum(w x value) /
sum(w) over those.

Where the pack is silent (decided 17 Oct 2026, docs/engineering/ENG-17.md):

    category    the product's own category (basicInfo.categoryId, else the last of
                categoryPathIds); missing when either product has none. The
                top-level category is fallback step 2's (reco.slots.product.ladder).
    cross_sell  missing when the viewed product's list is empty: an empty list says
                nothing about any candidate (on dev every list is empty).
    price_band  missing when either product has no active variant with a price (a
                salePrice of 0 or below is not a price); "within" includes the edge
                (|p - p0| <= 0.30 x p0).
    popularity  never missing: no clicks and no add-to-carts is a count of 0.
                Percentiles as ENG-15 and ENG-16, (below + (equal - 1) / 2) / (n - 1),
                ties counted half; one product alone 0.5.
    same_seller missing when either product has no seller.
    ties        the higher score first, then the more popular, then the product id.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Iterable, Mapping

from reco.platform.records import ProductRecord, VariantRecord
from reco.slots.promoter.score import percentile_ranks

COMPONENTS = ("category", "cross_sell", "price_band", "popularity", "same_seller")


@dataclass(frozen=True)
class ProductItem:
    """What method one reads about one product."""

    product_id: str
    seller_id: str | None
    category_id: str | None  # the top-level category (categoryPathIds[0]): fallback step 2
    leaf_category_id: str | None  # the product's own category: method one's "same category"
    cross_sell_ids: frozenset[str]
    price: float | None  # the lowest salePrice among its active variants
    popularity: int = 0  # clicks on its cards plus add-to-carts, last 30 days
    created_ts: float = 0.0  # products.createdAt, for "newest first"

    @classmethod
    def of(cls, product: ProductRecord, variants: Iterable[VariantRecord], popularity: int = 0) -> ProductItem:
        return cls(
            product_id=product.product_id, seller_id=product.seller_id, category_id=product.category_id,
            leaf_category_id=product.leaf_category_id, cross_sell_ids=frozenset(product.cross_sell_ids),
            price=lowest_active_price(variants), popularity=popularity,
            created_ts=product.created_at.timestamp() if product.created_at else 0.0,
        )


def lowest_active_price(variants: Iterable[VariantRecord]) -> float | None:
    """The lowest salePrice among the product's active variants (None if there is none)."""
    prices = [v.price for v in variants if v.is_active and v.price is not None and v.price > 0]
    return min(prices) if prices else None


def popularity_percentiles(counts: Mapping[str, int]) -> dict[str, float]:
    """Each product's popularity as a percentile among the products given, 0 to 1."""
    return percentile_ranks({k: float(v) for k, v in counts.items()})


def in_price_band(viewed: float | None, candidate: float | None, fraction: float) -> bool | None:
    """Whether the candidate's price is within +-fraction of the viewed product's; None if either is missing."""
    if viewed is None or candidate is None or viewed <= 0:
        return None
    return abs(candidate - viewed) <= fraction * viewed + 1e-9


def components(viewed: ProductItem, candidate: ProductItem, popularity: float, price_band: float) -> dict[str, float | None]:
    """Each component's value for `candidate` against `viewed` (None = missing)."""
    same_category = (None if viewed.leaf_category_id is None or candidate.leaf_category_id is None
                     else float(viewed.leaf_category_id == candidate.leaf_category_id))
    cross_sell = float(candidate.product_id in viewed.cross_sell_ids) if viewed.cross_sell_ids else None
    band = in_price_band(viewed.price, candidate.price, price_band)
    same_seller = (None if viewed.seller_id is None or candidate.seller_id is None
                   else float(viewed.seller_id == candidate.seller_id))
    return {
        "category": same_category,
        "cross_sell": cross_sell,
        "price_band": None if band is None else float(band),
        "popularity": popularity,
        "same_seller": same_seller,
    }


def weighted(parts: Mapping[str, float | None], weights: Mapping[str, float]) -> float:
    """sum(w x value) / sum(w) over the components present; 0 if none is."""
    present = [(weights[c], v) for c, v in parts.items() if v is not None]
    total = sum(w for w, _ in present)
    return sum(w * v for w, v in present) / total if total > 0 else 0.0


@dataclass(frozen=True)
class Similar:
    product_id: str
    score: float
    components: dict[str, float | None]


def top_similar(
    viewed: ProductItem,
    sellable: Iterable[ProductItem],
    percentiles: Mapping[str, float],
    *,
    weights: Mapping[str, float],
    price_band: float,
    limit: int,
) -> list[Similar]:
    """Method one's list for `viewed`: the `limit` best-scoring sellable products,
    never the viewed product itself."""
    scored = []
    for candidate in sellable:
        if candidate.product_id == viewed.product_id:
            continue
        parts = components(viewed, candidate, percentiles.get(candidate.product_id, 0.5), price_band)
        score = weighted(parts, weights)
        scored.append((score, candidate.popularity, candidate.product_id, parts))
    best = heapq.nsmallest(limit, scored, key=lambda s: (-s[0], -s[1], s[2]))
    return [Similar(pid, score, parts) for score, _, pid, parts in best]
