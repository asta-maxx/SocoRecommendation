"""Building one served list: candidates, paging, exploration and the scored sample. ENG-06.

    candidates = await interim_candidates(settings, surface, page, limit, context_item_id)
    items      = served_items(page_items, explore=...)
    sample     = scored_sample(candidates, returned_ids, exploration)

The ordering is the interim one the Build List sets for ENG-06 until the feed
ranking (ENG-19) and the product ranker (ENG-17) exist: eligible items (E-01 to
E-12, ENG-08) newest first -- posts on the feed, products on the product surface (the context
product left out). Page p holds positions (p-1)*limit+1 to p*limit of that
order. ENG-19 replaces this with the ranking layer, which also leaves out items
served to the user in the last 24 hours.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

from reco.config import Settings
from reco.eligibility.apply import eligible_posts, eligible_products, recheck, viewer_context
from reco.eligibility.rules import Viewer
from reco.platform import fetch

#: Per-request randomness: exploration and the 10% sample. A test replaces it.
rng = random.Random()

#: Rows read per platform page while filling a list.
_READ_PAGE = 250


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
    # X-16 / F10: a post card keeps its post id as item_id. A post card showing a
    # product has item_type product, as the platform's own feed lists write it
    # (F10: "item_type product with a post id is a post card showing a product");
    # post_id and product_id ride along, so a post id is never read as a product id.
    product = post.product_ids[0] if post.product_ids else None
    return post.post_id, ("product" if product else "post"), post.post_id, product


def _product_card(product) -> tuple[str, str, str | None, str | None]:
    return product.product_id, "product", None, product.product_id


#: The most platform rows one list reads while looking for eligible items. The
#: pack sets no limit; without one, a surface where nothing is eligible would read
#: the whole collection on every request. Fewer than `limit` items come back when
#: fewer eligible items are found within it (DS-017 4.3 allows fewer).
MAX_SCAN_ROWS = 1000


@dataclass
class Built:
    viewer: Viewer
    candidates: list[Candidate]
    cache: dict  # accounts read for this request (reco.eligibility.apply)
    rows_read: int


async def interim_candidates(
    settings: Settings, surface: str, page: int, limit: int, context_item_id: str | None,
    user_id: str | None = None, request_id: str | None = None,
) -> Built:
    """Eligible items (E-01 to E-12, ENG-08), newest first, through the end of the
    requested page plus one page more, so an item that fails the final recheck
    can be replaced by the next eligible one. The viewer's context is read at the
    same time as the first page."""
    kind, eligible, card = (
        ("post", eligible_posts, _post_card) if surface == "feed" else ("product", eligible_products, _product_card)
    )
    viewer, rows = await asyncio.gather(
        viewer_context(settings, user_id), fetch.read_newest(settings, kind, _READ_PAGE, 0)
    )
    wanted = (page + 1) * limit
    found: list[Candidate] = []
    cache: dict = {}
    read = 0
    while True:
        read += len(rows)
        for row in await eligible(settings, rows, viewer, request_id, cache):
            item_id, item_type, post_id, product_id = card(row)
            # The context product, and on a product list every product already in the
            # viewer's cart (Kala, 16 Oct), never appear.
            if item_id != context_item_id and not (kind == "product" and item_id in viewer.in_cart):
                found.append(Candidate(item_id, item_type, post_id, product_id, rank=len(found) + 1))
        if len(found) >= wanted or len(rows) < _READ_PAGE or read >= MAX_SCAN_ROWS:
            break
        # Not enough in the first page: the rest of the scan window in one read.
        rows = await fetch.read_newest(settings, kind, MAX_SCAN_ROWS - read, read)
    return Built(viewer, found[:wanted], cache, read)


async def page_after_recheck(
    settings: Settings, built: Built, page: int, limit: int, request_id: str | None
) -> list[Candidate]:
    """ENG-08: the page's items re-checked on the platform just before the list is
    returned; any that fail are replaced by the next eligible items."""
    candidates = built.candidates
    start = (page - 1) * limit
    page_items = candidates[start:start + limit]
    spare = candidates[start + limit:]
    if not page_items:
        return page_items
    failed = await recheck(
        settings, [{"item_id": c.item_id, "item_type": c.item_type, "post_id": c.post_id} for c in page_items],
        built.viewer, request_id, built.cache
    )
    if not failed:
        return page_items
    kept = [c for c in page_items if c.item_id not in failed]
    spare = [c for c in spare if c.item_id not in failed]
    return kept + spare[:limit - len(kept)]


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


def scored_not_served(candidates: list[Candidate], returned: set[str], exploration: bool, percent: int) -> list[dict[str, Any]] | None:
    """ENG-06, Capture Register F72: on `percent`% of requests at random, and on
    every exploration request, the scored items -- every returned item and every
    one passed over -- each with its score. None on the other requests (F72:
    "Present on about 10% of E1 rows, and on every exploration row"). Until the
    rankers exist (ENG-17, ENG-19) there is no model score: score is null and the
    interim rank is kept."""
    if not (exploration or rng.random() * 100 < percent):
        return None
    return [{"item_id": c.item_id, "score": None, "rank": c.rank, "returned": c.item_id in returned} for c in candidates]
