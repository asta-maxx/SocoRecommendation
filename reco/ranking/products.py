"""The product surface's list: M5, the product ranker, at request time. ENG-17.

    built = await product_candidates(settings, page, limit, context_item_id, user_id, request_id, assignment)
    built.candidates, built.fallback_step, built.detail

Build List v1.4 ENG-17: "The list served is the one from the method assigned to
the user (ENG-05). [...] A request reads the stored list for the method assigned
to the user (ENG-05), applies the filters, and returns exactly limit items, or
fewer only when fewer eligible products exist." On product detail the context
product is the one viewed; on the cart, SOCO_BE sends the most recently added cart
item (Kala, 16 Oct). Always excluded: the context product, and every product in
the viewer's cart, on every product request (Kala, 16 Oct: the engine reads the
cart itself, reco.eligibility.apply.viewer_context).

The list is filled from the sources of reco.slots.product.ladder, in order: the
assigned method's own stored list (ml_product_scores, current batch only), then
the fallback steps -- for bought_together, 1. the method-one list for that
product; then, for both, 2. eligible products in the same top-level category,
most popular first (stored nightly); 3. eligible products, newest first (read
from the platform). Every product goes through E-01 to E-12 (ENG-08) before it
takes a place; ENG-06's final recheck follows (reco.ranking.serving). A current
batch older than interest.stale_after_hours is not read (ENG-22 check 10).

Like the feed, the list runs through the end of the requested page plus one page
more, so a product that fails the final recheck is replaced by the next one.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from reco.config import Settings, live
from reco.eligibility.apply import eligible_products, viewer_context
from reco.platform import fetch
from reco.ranking.serving import MAX_SCAN_ROWS, Built, Candidate, _READ_PAGE
from reco.slots.assignment import Assignment
from reco.slots.product import ladder
from reco.slots.product.bought_together import LABELS
from reco.store import product_scores as store
from reco.store.scores import utc_now

#: Recorded on the E1, so a product list is never mistaken for the interim ordering.
ORDERING = "eng17_product_ranker"

#: Stored ids checked per platform read while filling a list (at least this many).
_CHUNK = 20


def _card(product_id: str, rank: int) -> Candidate:
    # A product rail carries product ids only (ENG-29 item 6): post_id is null.
    return Candidate(product_id, "product", None, product_id, rank=rank)


async def _none() -> tuple[None, str]:
    return None, "not needed"


async def product_candidates(
    settings: Settings, page: int, limit: int, context_item_id: str | None,
    user_id: str | None, request_id: str | None, assignment: Assignment,
) -> Built:
    tunables = live.current()
    slot = tunables.slots.product_ranking
    one, two = slot.method_one, slot.method_two
    now = utc_now()
    stale_hours = tunables.interest.stale_after_hours
    method = assignment.method
    viewer, (batch_one, why_one), (batch_two, why_two) = await asyncio.gather(
        viewer_context(settings, user_id),
        store.current_batch(settings, one, now, stale_hours),
        store.current_batch(settings, two, now, stale_hours) if method == two else _none(),
    )
    own_batch = batch_two if method == two else batch_one
    wanted = (page + 1) * limit
    exclude = {context_item_id or "", *viewer.in_cart}
    found: list[str] = []
    seen: set[str] = set()
    added: dict[str, int] = {}
    cache: dict = {}
    rows_read = 0

    async def from_ids(ids: list[str]) -> int:
        """Fill from stored ids, in order, each through the filters."""
        nonlocal rows_read
        total = 0
        pending = [i for i in ids if i not in seen and i not in exclude]
        while pending and len(found) < wanted:
            size = max(_CHUNK, 2 * (wanted - len(found)))
            chunk, pending = pending[:size], pending[size:]
            rows = await fetch.read_where(settings, "product", "_id", chunk)
            rows_read += len(rows)
            kept = {p.product_id for p in await eligible_products(settings, rows, viewer, request_id, cache)}
            total += ladder.take(found, seen, (i for i in chunk if i in kept), exclude, wanted)
        return total

    async def newest() -> int:
        """Step 3: eligible products, newest first, within ENG-06's scan window."""
        nonlocal rows_read
        total, read = 0, 0
        size = _READ_PAGE
        while len(found) < wanted and read < MAX_SCAN_ROWS:
            rows = await fetch.read_newest(settings, "product", size, read)
            read += len(rows)
            kept = await eligible_products(settings, rows, viewer, request_id, cache)
            total += ladder.take(found, seen, (p.product_id for p in kept), exclude, wanted)
            if len(rows) < size:
                break
            size = MAX_SCAN_ROWS - read
        rows_read += read
        return total

    async def stored(batch: str | None) -> int:
        """A stored list for the context product: the method's own, or step 1."""
        return await from_ids(await store.read_product_list(settings, batch, context_item_id or ""))

    async def top_level_category() -> str | None:
        rows = await fetch.read_where(settings, "product", "_id", [context_item_id]) if context_item_id else []
        return rows[0].category_id if rows else None

    async def step_two() -> int:
        category = await top_level_category()
        return await from_ids(await store.read_category_list(settings, own_batch or batch_one or batch_two, category))

    sources: dict[str, Callable[[], Awaitable[int]]] = {
        ladder.OWN: lambda: stored(own_batch),
        ladder.STEP_1: lambda: stored(batch_one),
        ladder.STEP_2: step_two,
        ladder.STEP_3: newest,
    }

    for source in ladder.ladder(method, method_one=one, method_two=two):
        if len(found) >= wanted:
            break
        added[source] = await sources[source]()

    filled = ladder.Filled(found, added)
    detail: dict[str, Any] = {
        "ordering": ORDERING,
        "steps_used": {s: n for s, n in added.items() if n},
        "method_served": filled.method_served,
        "batch": {"job_run_id": own_batch, "why": why_two if method == two else why_one},
    }
    if method == two:
        detail["label"] = LABELS[tunables.product.basket_source]
    return Built(viewer, [_card(pid, rank) for rank, pid in enumerate(found, start=1)], cache, rows_read,
                 fallback_step=filled.fallback_step, detail=detail)
