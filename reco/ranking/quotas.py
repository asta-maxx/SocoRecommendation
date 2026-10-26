"""The method-one pool: quotas over the candidate sources. ENG-13.

    sources, pool = await pool_for_user(settings, user_id, profile, viewer, request_id)
    pool.items      -> [SourceItem, ...]  up to retrieval.pool_size (300), interleaved
    pool.quotas     -> the places each source was given (after short sources passed theirs on)
    pool.taken      -> the places each source filled

Build List v1.4 ENG-13: a pool of 300 candidates, 40% from interest categories,
30% from follows, 20% from trending, 10% from recent platform-wide popular posts
(retrieval.source_shares). The sources are interleaved round-robin in those
proportions. If a source runs short, its share passes to the next source in that
order. Duplicates are removed; a repost counts as its original. The filters
(ENG-08) apply before and after. Every candidate keeps its source tag.

How each part is done:

- Quotas: pool_size x share, rounded by largest remainder so they sum to the pool
  size exactly (120, 90, 60, 30 for 300).
- Interleave: smooth weighted round-robin. The next place goes to the source
  furthest behind its quota ((taken + 0.5) / quota lowest; ties in source order),
  so 300 places run interest, follows, trending, interest, follows, popular, ...
  and every prefix of the pool keeps the proportions (ENG-15 cuts it by order).
- Short source: its unused places pass to the next source in the order interest,
  follows, trending, popular that still has items; after popular it wraps round to
  interest (the pack names no source after popular: decided 16 Oct 2026, to be
  confirmed). Then the interleave runs again with the new quotas.
- Duplicates: judged by SourceItem.key, the original's id for a repost (ENG-30
  point 3). The first source to reach an item keeps it; the others skip it and
  take their next item, so a duplicate never costs a source a place. A repost in
  the pool is replaced by its original (item_id = the original), keeping the
  source tag and score of the repost that brought it.
- Filters before: every item each source offered goes through ENG-08 (E-01 to
  E-12, one platform read for all of them), so a source's count is of eligible
  items before quotas are worked out. Filters after: the pool, with reposts
  replaced by their originals, goes through ENG-08 again; an original that fails
  is taken out with every item that leads to it, and the pool is built again
  without it, so it stays full. Each exclusion is logged by ENG-08 with its rule.
- A post the platform no longer has is excluded and logged (rule "missing").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from reco.config import Settings, live
from reco.eligibility.apply import eligible_posts, viewer_context
from reco.eligibility.rules import Viewer
from reco.fallback.profile import Profile
from reco.platform import fetch
from reco.ranking.sources import SourceItem, SourceResult, run_sources, top_categories

logger = logging.getLogger("reco.retrieval")

#: The method-one sources, in the order a short source passes its share on.
QUOTA_SOURCES = ("interest", "follows", "trending", "popular")
_SHARE = {"interest": "interest", "follows": "follows", "trending": "trending", "popular": "platform_popular"}


@dataclass
class Pool:
    items: list[SourceItem] = field(default_factory=list)
    quotas: dict[str, int] = field(default_factory=dict)  # after short sources passed theirs on
    planned: dict[str, int] = field(default_factory=dict)  # pool_size x share
    taken: dict[str, int] = field(default_factory=dict)
    duplicates: int = 0
    reposts_merged: dict[str, str] = field(default_factory=dict)  # original -> the repost that brought it
    excluded_before: int = 0
    excluded_after: int = 0


def shares_in_force() -> dict[str, float]:
    configured = live.current().retrieval.source_shares
    return {s: getattr(configured, _SHARE[s]) for s in QUOTA_SOURCES}


def quotas(size: int, shares: dict[str, float]) -> dict[str, int]:
    """size x share per source, by largest remainder: they sum to size exactly."""
    total = sum(shares.get(s, 0.0) for s in QUOTA_SOURCES) or 1.0
    exact = {s: size * shares.get(s, 0.0) / total for s in QUOTA_SOURCES}
    out = {s: int(exact[s]) for s in QUOTA_SOURCES}
    by_remainder = sorted(QUOTA_SOURCES, key=lambda s: (-(exact[s] - out[s]), QUOTA_SOURCES.index(s)))
    for s in by_remainder[: size - sum(out.values())]:
        out[s] += 1
    return out


def _fill(lists: dict[str, list[SourceItem]], targets: dict[str, int]) -> tuple[list[SourceItem], dict[str, int], int, set[str]]:
    """One interleave: the pool, places taken, duplicates skipped, sources with items left."""
    order = QUOTA_SOURCES
    pos = dict.fromkeys(order, 0)
    taken = dict.fromkeys(order, 0)
    pool: list[SourceItem] = []
    seen: set[str] = set()
    duplicates = 0
    active = [s for s in order if targets.get(s, 0) > 0]
    while active:
        s = min(active, key=lambda s: ((taken[s] + 0.5) / targets[s], order.index(s)))
        items = lists.get(s, [])
        while pos[s] < len(items) and items[pos[s]].key in seen:
            pos[s] += 1
            duplicates += 1
        if pos[s] >= len(items):
            active.remove(s)
            continue
        item = items[pos[s]]
        pos[s] += 1
        seen.add(item.key)
        pool.append(item)
        taken[s] += 1
        if taken[s] >= targets[s]:
            active.remove(s)
    spare = {s for s in order if any(i.key not in seen for i in lists.get(s, [])[pos[s]:])}
    return pool, taken, duplicates, spare


def interleave(lists: dict[str, list[SourceItem]], size: int, shares: dict[str, float]) -> Pool:
    """The pool from lists already filtered, in each source's own order (no database)."""
    planned = quotas(size, shares)
    targets = dict(planned)
    order = QUOTA_SOURCES
    # Each pass caps a short source at what it filled and passes its unused places to
    # the next source in order that still has items (wrapping after popular). Places
    # freed earlier and not yet taken (a source can lose a shared post to another one
    # in a later pass) go to the first source in order with items left. Bounded.
    for _ in range(4 * len(order)):
        pool, taken, duplicates, spare = _fill(lists, targets)
        before = dict(targets)
        for s in [s for s in order if taken[s] < before[s]]:
            deficit = before[s] - taken[s]
            targets[s] -= deficit
            nxt = next((order[(order.index(s) + k) % len(order)] for k in range(1, len(order))
                        if order[(order.index(s) + k) % len(order)] in spare), None)
            if nxt:
                targets[nxt] += deficit
        free = size - sum(targets.values())
        first = next((s for s in order if s in spare), None)
        if free > 0 and first:
            targets[first] += free
        if targets == before:  # settled: this pass's pool stands
            break
    else:  # pragma: no cover - not seen in practice; the last pass's pool stands
        pool, taken, duplicates, _ = _fill(lists, targets)
    # What is still unfilled had no source left to take it: a source's quota is what it filled.
    targets = {s: min(targets[s], taken[s]) for s in order}
    merged = {}
    items = []
    for item in pool:
        if item.key != item.item_id:
            merged[item.key] = item.item_id
            item = replace(item, item_id=item.key)
        items.append(item)
    return Pool(items=items, quotas=targets, planned=planned, taken=taken, duplicates=duplicates, reposts_merged=merged)


async def build_pool(
    settings: Settings, sources: SourceResult, viewer: Viewer, request_id: str | None = None, size: int | None = None
) -> Pool:
    """The method-one pool for one request, with the ENG-08 filters before and after."""
    size = size if size is not None else live.current().retrieval.pool_size
    shares = shares_in_force()
    offered = {s: list(sources.items.get(s, [])) for s in QUOTA_SOURCES}
    ids = sorted({i for items in offered.values() for item in items for i in (item.item_id, item.key)})
    posts = await fetch.read_where(settings, "post", "_id", ids)
    found = {p.post_id for p in posts}
    for missing in sorted(set(ids) - found):
        logger.info("excluded", extra={"request_id": request_id, "item_id": missing, "item_type": "post", "rule": "missing"})
    kept = {p.post_id for p in await eligible_posts(settings, posts, viewer, request_id)}

    before = {s: [i for i in items if i.item_id in kept] for s, items in offered.items()}
    excluded_before = len({i.item_id for items in offered.values() for i in items} - kept)
    failed_originals: set[str] = set()
    while True:
        lists = {s: [i for i in items if i.key not in failed_originals] for s, items in before.items()}
        pool = interleave(lists, size, shares)
        failing = {i.item_id for i in pool.items if i.item_id not in kept}
        if not failing:
            break
        failed_originals |= failing
    pool.excluded_before = excluded_before
    pool.excluded_after = len(failed_originals)
    logger.info("method-one pool", extra={
        "request_id": request_id, "pool_size": len(pool.items), "taken": pool.taken, "quotas": pool.quotas,
        "duplicates": pool.duplicates, "reposts_merged": len(pool.reposts_merged),
        "excluded_before": pool.excluded_before, "excluded_after": pool.excluded_after})
    return pool


async def pool_for_user(
    settings: Settings, user_id: str | None, profile: Profile | None, viewer: Viewer | None = None,
    request_id: str | None = None, time_limit_ms: float | None = None,
) -> tuple[SourceResult, Pool]:
    """Sources (ENG-12) and the pool (ENG-13) for one user. The top-5 categories come
    from the profile of the user's assigned interest method or its fallback rung;
    follows from the viewer (ENG-08's viewer context)."""
    viewer = viewer or await viewer_context(settings, user_id)
    shares = {c.category: c.share for c in profile.categories} if profile else {}
    found = await run_sources(settings, user_id, top_categories(shares), viewer.follows, request_id,
                              time_limit_ms=time_limit_ms)
    return found, await build_pool(settings, found, viewer, request_id)
