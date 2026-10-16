"""Merge the two retrieval methods into the shortlist. ENG-15.

    shortlist = await shortlist_for_user(settings, user_id, profile, viewer, request_id)
    shortlist.items -> [ShortlistItem, ...]   up to retrieval.shortlist_size (200)

Build List v1.4 ENG-15: merge the method-one pool (ENG-13) and the method-two list
(ENG-14) for every user; both methods run for everyone, this is not a traffic
split. Source scores are not comparable across sources (a view count is not a
cosine similarity): each candidate's source_score is replaced by its percentile
within its own source, 0 to 1, and only these percentiles are ever compared.
Duplicates are removed, keeping the higher percentile and recording both source
tags. The shortlist is cut to 200 by taking candidates in the ENG-13 interleaved
order, not by score, so the quotas survive the cut. The pool size per source is
logged on each request.

How each part is done:

- Percentile within a source: over the items the source returned for this
  request (ENG-12's list, before quotas), the share of the source's other items
  with a lower score, ties counted half: (below + (equal - 1) / 2) / (n - 1). The
  best is 1, the worst 0; a source of one item gives 1. A repost merged into its
  original keeps the percentile of the repost that brought it.
- Order: the method-one pool in its interleaved order, and the method-two list in
  its rank order, interleaved in proportion to their sizes (300 to 200 gives 3 to
  2, so a cut at 200 keeps about 120 and 80). The pack gives method two no place in
  ENG-13's order; decided 16 Oct 2026, to be confirmed (Nisha/Kala, Q8). A user
  with no method-two list gets the method-one pool alone, and the other way round.
- Method two's list goes through the ENG-08 filters before the merge, as the pool
  did in ENG-13; its items are the stored list's posts (ENG-14 leaves reposts out).
- Duplicates: the first place an item reaches stands; a later copy adds its source
  tag and raises the percentile if higher, and does not take a place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from reco.config import Settings, live
from reco.eligibility.apply import eligible_posts, viewer_context
from reco.eligibility.rules import Viewer
from reco.fallback.profile import Profile
from reco.platform import fetch
from reco.ranking.quotas import Pool, pool_for_user
from reco.ranking.sources import SOURCES, SourceItem, SourceResult

logger = logging.getLogger("reco.retrieval")

METHOD_ONE, METHOD_TWO = "method_one", "method_two"


@dataclass
class ShortlistItem:
    item_id: str
    item_type: str
    sources: list[str]  # every source that offered it; the first is the one whose place it holds
    percentile: float  # the highest percentile within its own source(s), 0 to 1
    method: str  # the method whose place it holds


@dataclass
class Shortlist:
    items: list[ShortlistItem] = field(default_factory=list)
    pool_sizes: dict[str, int] = field(default_factory=dict)  # per source, before the merge
    by_source: dict[str, int] = field(default_factory=dict)  # places held, per source, after the cut
    duplicates: int = 0
    excluded_method_two: int = 0


def percentiles(items: list[SourceItem]) -> dict[str, float]:
    """Each item's percentile within its own source, 0 to 1 (ties counted half)."""
    n = len(items)
    if n == 0:
        return {}
    if n == 1:
        return {items[0].item_id: 1.0}
    scores = sorted(i.source_score for i in items)
    out: dict[str, float] = {}
    for item in items:
        below = _count_below(scores, item.source_score)
        equal = _count_below(scores, item.source_score, inclusive=True) - below
        out[item.item_id] = (below + (equal - 1) / 2) / (n - 1)
    return out


def _count_below(scores: list[float], value: float, inclusive: bool = False) -> int:
    from bisect import bisect_left, bisect_right

    return (bisect_right if inclusive else bisect_left)(scores, value)


def merge(pool: Pool, sources: SourceResult, similar: list[SourceItem], size: int) -> Shortlist:
    """The shortlist from the pool and the (filtered) method-two list (no database)."""
    pct = {s: percentiles(sources.items.get(s, [])) for s in SOURCES}
    reposts = dict(pool.reposts_merged)  # original -> the repost that brought it

    def percentile(item: SourceItem) -> float:
        by_id = pct.get(item.source, {})
        return by_id.get(item.item_id, by_id.get(reposts.get(item.item_id, ""), 0.0))

    lanes = {METHOD_ONE: list(pool.items), METHOD_TWO: list(similar)}
    weights = {m: len(v) for m, v in lanes.items()}
    pos = dict.fromkeys(lanes, 0)
    placed = dict.fromkeys(lanes, 0)
    out: list[ShortlistItem] = []
    index: dict[str, ShortlistItem] = {}
    duplicates = 0
    while len(out) < size:
        live_lanes = [m for m in lanes if pos[m] < len(lanes[m])]
        if not live_lanes:
            break
        m = min(live_lanes, key=lambda m: ((placed[m] + 0.5) / weights[m], m != METHOD_ONE))
        item = lanes[m][pos[m]]
        pos[m] += 1
        p = percentile(item)
        if item.item_id in index:
            held = index[item.item_id]
            duplicates += 1
            if item.source not in held.sources:
                held.sources.append(item.source)
            held.percentile = max(held.percentile, p)
            continue
        entry = ShortlistItem(item.item_id, item.item_type, [item.source], p, m)
        index[item.item_id] = entry
        out.append(entry)
        placed[m] += 1
    # Copies further down either lane than the cut still add their tag and percentile.
    for m in lanes:
        for item in lanes[m][pos[m]:]:
            held = index.get(item.item_id)
            if held is not None:
                duplicates += 1
                if item.source not in held.sources:
                    held.sources.append(item.source)
                held.percentile = max(held.percentile, percentile(item))
    by_source: dict[str, int] = {}
    for entry in out:
        by_source[entry.sources[0]] = by_source.get(entry.sources[0], 0) + 1
    sizes = {s: pool.taken.get(s, 0) for s in pool.taken}
    sizes["similar"] = len(similar)
    return Shortlist(items=out, pool_sizes=sizes, by_source=by_source, duplicates=duplicates)


async def eligible_similar(settings: Settings, similar: list[SourceItem], viewer: Viewer, request_id: str | None) -> list[SourceItem]:
    """Method two's list through the ENG-08 filters (as ENG-13 does for the pool)."""
    if not similar:
        return []
    posts = await fetch.read_where(settings, "post", "_id", [i.item_id for i in similar])
    found = {p.post_id for p in posts}
    for missing in [i.item_id for i in similar if i.item_id not in found]:
        logger.info("excluded", extra={"request_id": request_id, "item_id": missing, "item_type": "post", "rule": "missing"})
    kept = {p.post_id for p in await eligible_posts(settings, posts, viewer, request_id)}
    return [i for i in similar if i.item_id in kept]


async def shortlist_for_user(
    settings: Settings, user_id: str | None, profile: Profile | None, viewer: Viewer | None = None,
    request_id: str | None = None, time_limit_ms: float | None = None,
) -> Shortlist:
    """Sources (ENG-12), the pool (ENG-13), the method-two list (ENG-14), merged (ENG-15)."""
    viewer = viewer or await viewer_context(settings, user_id)
    sources, pool = await pool_for_user(settings, user_id, profile, viewer, request_id, time_limit_ms)
    offered = sources.items.get("similar", [])
    similar = await eligible_similar(settings, offered, viewer, request_id)
    shortlist = merge(pool, sources, similar, live.current().retrieval.shortlist_size)
    shortlist.excluded_method_two = len(offered) - len(similar)
    logger.info("shortlist", extra={
        "request_id": request_id, "pool_sizes": shortlist.pool_sizes, "shortlist_size": len(shortlist.items),
        "by_source": shortlist.by_source, "duplicates": shortlist.duplicates,
        "excluded_method_two": shortlist.excluded_method_two, "dropped_sources": sources.dropped})
    return shortlist
