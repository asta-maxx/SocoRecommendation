"""Building one served list: candidates, paging, exploration and the scored sample. ENG-06.

    candidates = await interim_candidates(settings, surface, page, limit, context_item_id)
    items      = served_items(page_items, explore=...)
    sample     = scored_sample(candidates, returned_ids, exploration)

The ordering is the interim one the Build List sets for ENG-06 until the feed
ranking (ENG-19) and the product ranker (ENG-17) exist: eligible items newest
first -- posts on the feed, products on the product surface (the context
product left out). Page p holds positions (p-1)*limit+1 to p*limit of that
order. ENG-19 replaces this with the ranking layer, which also leaves out items
served to the user in the last 24 hours.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from reco.config import Settings
from reco.eligibility.basic import post_is_eligible, product_is_eligible
from reco.platform import fetch

#: Per-request randomness: exploration and the 10% sample. A test replaces it.
rng = random.Random()

#: Rows read per platform page while filling a list.
_READ_PAGE = 100


@dataclass(frozen=True)
class Candidate:
    """One eligible item, as the item adapter shapes it (ENG-29 item 6, DS-017 section 3)."""

    item_id: str
    item_type: str  # post or product
    post_id: str | None
    product_id: str | None
    rank: int  # 1 = first in the ordering

    def card(self, position: int) -> dict[str, Any]:
        return {"item_id": self.item_id, "item_type": self.item_type, "post_id": self.post_id,
                "product_id": self.product_id, "position": position, "reason_code": None}


def _post_card(post) -> tuple[str, str, str | None, str | None]:
    # A post card keeps its post id as item_id; a product it shows rides along as
    # product_id, so a post id is never read as a product id.
    return post.post_id, "post", post.post_id, (post.product_ids[0] if post.product_ids else None)


def _product_card(product) -> tuple[str, str, str | None, str | None]:
    return product.product_id, "product", None, product.product_id


async def interim_candidates(
    settings: Settings, surface: str, page: int, limit: int, context_item_id: str | None
) -> list[Candidate]:
    """Eligible items, newest first, through the end of the requested page."""
    kind, eligible, card = (
        ("post", post_is_eligible, _post_card) if surface == "feed" else ("product", product_is_eligible, _product_card)
    )
    wanted = page * limit
    found: list[Candidate] = []
    skip = 0
    while len(found) < wanted:
        rows = await fetch.read_newest(settings, kind, _READ_PAGE, skip)
        for row in rows:
            item_id, item_type, post_id, product_id = card(row)
            if eligible(row) and item_id != context_item_id:
                found.append(Candidate(item_id, item_type, post_id, product_id, rank=len(found) + 1))
        if len(rows) < _READ_PAGE:
            break
        skip += _READ_PAGE
    return found[:wanted]


def decide_exploration(surface: str, percent: int) -> bool:
    """ENG-06: on `percent`% of feed requests, never on product. Decided per request,
    separately from the method choice."""
    return surface == "feed" and rng.random() * 100 < percent


def explore(items: list[Candidate], keep_top: int) -> list[Candidate]:
    """Keep the top `keep_top` positions as ranked; shuffle the rest among themselves."""
    head, tail = items[:keep_top], items[keep_top:]
    tail = tail[:]
    rng.shuffle(tail)
    return head + tail


def scored_sample(
    candidates: list[Candidate], returned: set[str], exploration: bool, percent: int
) -> list[dict[str, Any]]:
    """ENG-06: every returned item, plus `percent`% of the scored items not returned
    at random -- or all of them on an exploration list."""
    sample = []
    for c in candidates:
        was_returned = c.item_id in returned
        if was_returned or exploration or rng.random() * 100 < percent:
            sample.append({"item_id": c.item_id, "item_type": c.item_type, "post_id": c.post_id,
                           "product_id": c.product_id, "rank": c.rank, "returned": was_returned})
    return sample
