"""M5 method two, bought together: the maths. ENG-17. Pure: no database.

    baskets = checkout_baskets(order_copies, left_out=("Cancelled", "Rejected"))   # once APP-22 passes
    baskets = cart_baskets(cart_lines)                                             # until then: "intent"
    pairs   = pair_counts(baskets)
    lift(n_ab, n_a, n_b, total)            P(A and B) / (P(A) x P(B))
    adjusted_lift(n, lift, strength=10)    (n x lift + 10) / (n + 10)
    lists   = bought_together(baskets, strength=10, min_co_purchases=2, limit=100)

Build List v1.4 ENG-17, Settings "M5 product" (strength 10, at least 2):

    lift = P(A and B) / (P(A) x P(B)), counted over orders that share a checkout_id,
    leaving out Cancelled and Rejected orders; with N baskets, n_A baskets holding A
    and n_AB holding both, lift = (n_AB / N) / ((n_A / N) x (n_B / N)).
    adjusted lift = (n x lift + 10) / (n + 10), n = how often the pair was bought
    together (n_AB): a pair seen rarely is pulled toward 1, "no association".
    A pair needs at least 2 co-purchases to count.

Until the basket test (APP-22) passes, it is computed over cart contents and
labelled "intent" (the setting product.basket_source, cart until then). Incognito
orders count (DS-017 6.4: an anonymous total); no buyer is ever named: a basket
is a set of product ids, nothing else is kept.

Where the pack is silent (decided 17 Oct 2026, docs/engineering/ENG-17.md):

    a basket   one checkout_id's orders, or one owner's cart (carts lines grouped by
               user_id); a product counts once per basket, whatever the quantity or
               the number of variants. Orders with no checkout_id and cart lines
               with no owner are not baskets (counted in the job's report).
    N          every basket holding at least one product, including baskets of one
               product: P(A) is the share of all baskets that hold A.
    order      each product's partners by adjusted lift, highest first; ties: more
               co-purchases first, then the product id.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable, Mapping

from reco.platform.records import status_is

#: product.basket_source -> the label stored on every method-two row (ENG-17, ENG-22 check 7).
LABELS = {"cart": "intent", "checkout": "checkout"}


def checkout_baskets(orders: Iterable[Mapping[str, Any]], left_out: Iterable[str]) -> tuple[list[frozenset[str]], Counter]:
    """One basket per checkout_id: the products of its orders, leaving out orders
    whose status is any of `left_out` (Cancelled, Rejected). Returns the baskets and
    what was skipped."""
    left_out = tuple(left_out)
    by_checkout: dict[str, set[str]] = defaultdict(set)
    skipped: Counter = Counter()
    for order in orders:
        product, checkout = order.get("product_id"), order.get("checkout_id")
        if any(status_is(order.get("status"), s) for s in left_out):
            skipped["cancelled_or_rejected"] += 1
        elif not product:
            skipped["no_product"] += 1
        elif not checkout:
            skipped["no_checkout_id"] += 1
        else:
            by_checkout[str(checkout)].add(str(product))
    return [frozenset(b) for _, b in sorted(by_checkout.items())], skipped


def cart_baskets(lines: Iterable[Any]) -> tuple[list[frozenset[str]], Counter]:
    """One basket per cart owner (carts lines grouped by user_id): the products in it."""
    by_owner: dict[str, set[str]] = defaultdict(set)
    skipped: Counter = Counter()
    for line in lines:
        if not line.product_id:
            skipped["no_product"] += 1
        elif not line.user_id:
            skipped["no_owner"] += 1
        else:
            by_owner[line.user_id].add(line.product_id)
    return [frozenset(b) for _, b in sorted(by_owner.items())], skipped


def lift(n_ab: int, n_a: int, n_b: int, total: int) -> float:
    """P(A and B) / (P(A) x P(B)) = n_AB x N / (n_A x n_B)."""
    if n_a <= 0 or n_b <= 0 or total <= 0:
        return 0.0
    return (n_ab / total) / ((n_a / total) * (n_b / total))


def adjusted_lift(n: int, raw_lift: float, strength: float) -> float:
    """(n x lift + strength) / (n + strength)."""
    return (n * raw_lift + strength) / (n + strength)


@dataclass(frozen=True)
class PairCounts:
    total: int  # N: baskets holding at least one product
    single: Counter  # n_A: baskets holding each product
    pairs: Counter  # n_AB, keyed (A, B) with A < B


def pair_counts(baskets: Iterable[frozenset[str]]) -> PairCounts:
    single: Counter = Counter()
    pairs: Counter = Counter()
    total = 0
    for basket in baskets:
        if not basket:
            continue
        total += 1
        single.update(basket)
        pairs.update(combinations(sorted(basket), 2))
    return PairCounts(total, single, pairs)


@dataclass(frozen=True)
class Partner:
    product_id: str
    score: float  # adjusted lift
    lift: float
    co_purchases: int  # n


def bought_together(
    baskets: Iterable[frozenset[str]],
    *,
    strength: float,
    min_co_purchases: int,
    limit: int,
    allowed: set[str] | frozenset[str] | None = None,
) -> tuple[dict[str, list[Partner]], PairCounts]:
    """Each product's partners (adjusted lift, highest first), from pairs with at
    least `min_co_purchases`. `allowed` (the sellable products) limits who can be a
    partner; any product can be the one viewed. Products with no such pair have no
    list: the request falls back (reco.slots.product.ladder)."""
    counts = pair_counts(baskets)
    partners: dict[str, list[Partner]] = defaultdict(list)
    for (a, b), n in counts.pairs.items():
        if n < min_co_purchases:
            continue
        raw = lift(n, counts.single[a], counts.single[b], counts.total)
        score = adjusted_lift(n, raw, strength)
        for viewed, other in ((a, b), (b, a)):
            if allowed is None or other in allowed:
                partners[viewed].append(Partner(other, score, raw, n))
    lists = {
        viewed: sorted(found, key=lambda p: (-p.score, -p.co_purchases, p.product_id))[:limit]
        for viewed, found in partners.items()
    }
    return lists, counts
