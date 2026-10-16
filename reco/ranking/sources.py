"""Candidate sources for the feed: M2 retrieval, method one's inputs. ENG-12.

    result = await run_sources(settings, user_id, top_categories, follows, request_id)
    result.items["interest"]   -> [SourceItem, ...]   (also follows, trending, popular, similar)
    result.dropped             -> sources over their time limit, dropped for this request

Build List v1.4 ENG-12: four sources run in parallel, each returning item_id,
item_type, source and source_score, each within its time limit (20 ms, the setting
retrieval.source_time_limit_ms):

    1. interest   posts in the user's top-5 interest categories (from the interest
                  method assigned to the user, or the fallback rung)
    2. follows    posts by accounts the user follows
    3. trending   trending in the user's categories, by qualified views over the
                  last 7 days (Kala, 16 Oct: a plain count, source 4 limited to the
                  user's top-5 interest categories; ties newest first)
    4. popular    platform-wide popular posts, by qualified views over 7 days

The user's stored method-two list (ENG-14) is read in parallel within the same
limit, and merged in ENG-15. A source over its limit is dropped for that request
and logged. Only posts from the last 30 days are used (retrieval.post_age_days).

Every source reads the post index (reco.ranking.post_index), never computes.
source_score is each source's own measure and is never compared across sources
(ENG-15 turns them into percentiles):

    interest   the user's share of the post's best category (where a post has
               several categories, the highest share)
    follows    how new the post is (its time, as a number)
    trending   qualified views over 7 days
    popular    qualified views over 7 days
    similar    the stored cosine similarity (ENG-14)

Where the pack is silent the choice is recorded in docs/engineering/ENG-12.md.
Each source returns at most retrieval.pool_size items (300): ENG-13 takes its quota
from them, and a short source passes its share on.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from reco.config import Settings, live
from reco.store import candidates, item_state

logger = logging.getLogger("reco.retrieval")

SOURCES = ("interest", "follows", "trending", "popular", "similar")
TOP_CATEGORIES = 5


@dataclass(frozen=True)
class SourceItem:
    item_id: str
    item_type: str  # "post": the feed's sources offer posts
    source: str
    source_score: float
    created_at: datetime | None = None  # for ties: newer first


@dataclass
class SourceResult:
    items: dict[str, list[SourceItem]] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    ms: dict[str, float] = field(default_factory=dict)


def top_categories(shares: dict[str, float] | list[tuple[str, float]], n: int = TOP_CATEGORIES) -> list[tuple[str, float]]:
    """The user's top-n categories by share, highest first (ties by name, so it is stable)."""
    pairs = list(shares.items()) if isinstance(shares, dict) else list(shares)
    return sorted((p for p in pairs if p[1] > 0), key=lambda p: (-p[1], p[0]))[:n]


def _items(rows: list[dict[str, Any]], source: str, score: Callable[[dict[str, Any]], float]) -> list[SourceItem]:
    return [SourceItem(r["post_id"], "post", source, float(score(r)), r.get("created_at")) for r in rows]


def _ordered(items: list[SourceItem]) -> list[SourceItem]:
    """Best score first; ties newer first, then post id (stable)."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(items, key=lambda i: (-i.source_score, -(i.created_at or epoch).timestamp(), i.item_id), reverse=False)


async def _similar_reader(settings: Settings, user_id: str) -> list[dict[str, Any]]:
    """The user's stored method-two list (ENG-14), current batch only."""
    return await candidates.read_user_candidates(settings, user_id)


async def run_sources(
    settings: Settings,
    user_id: str | None,
    top: list[tuple[str, float]],
    follows: set[str] | frozenset[str],
    request_id: str | None = None,
    now: datetime | None = None,
    time_limit_ms: float | None = None,
) -> SourceResult:
    """Run every source in parallel, each within its time limit."""
    tunables = live.current().retrieval
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=tunables.post_age_days)
    limit = tunables.pool_size
    budget = (time_limit_ms if time_limit_ms is not None else tunables.source_time_limit_ms) / 1000
    shares = dict(top)
    categories = list(shares)
    batch = await item_state.current_batch(settings)

    async def interest() -> list[SourceItem]:
        if not batch or not categories:
            return []
        rows = await item_state.read_by_categories(settings, batch, categories, since, limit * 2)
        best = lambda r: max((shares.get(c, 0.0) for c in r.get("categories") or []), default=0.0)  # noqa: E731
        return _ordered(_items(rows, "interest", best))[:limit]

    async def by_follows() -> list[SourceItem]:
        if not batch or not follows:
            return []
        rows = await item_state.read_by_authors(settings, batch, sorted(follows), since, limit)
        return _ordered(_items(rows, "follows", lambda r: r["created_at"].timestamp()))[:limit]

    async def trending() -> list[SourceItem]:
        if not batch or not categories:
            return []
        rows = await item_state.read_most_viewed(settings, batch, since, limit, categories)
        return _ordered(_items(rows, "trending", lambda r: r["qualified_views_7d"]))

    async def popular() -> list[SourceItem]:
        if not batch:
            return []
        rows = await item_state.read_most_viewed(settings, batch, since, limit)
        return _ordered(_items(rows, "popular", lambda r: r["qualified_views_7d"]))

    async def similar() -> list[SourceItem]:
        if not user_id:
            return []
        rows = await _similar_reader(settings, user_id)
        return [SourceItem(str(r["post_id"]), "post", "similar", float(r["score"]), None) for r in rows[:limit]]

    runs: dict[str, Callable[[], Awaitable[list[SourceItem]]]] = {
        "interest": interest, "follows": by_follows, "trending": trending, "popular": popular, "similar": similar}
    result = SourceResult()

    async def timed(name: str) -> None:
        started = time.perf_counter()
        try:
            result.items[name] = await asyncio.wait_for(runs[name](), budget)
        except asyncio.TimeoutError:
            result.dropped.append(name)
            result.items[name] = []
            logger.warning("candidate source over its time limit; dropped for this request",
                           extra={"request_id": request_id, "source": name, "limit_ms": budget * 1000})
        result.ms[name] = round((time.perf_counter() - started) * 1000, 1)

    await asyncio.gather(*(timed(name) for name in SOURCES))
    logger.info("candidate sources", extra={"request_id": request_id, "sizes": {k: len(v) for k, v in result.items.items()},
                                            "ms": result.ms, "dropped": result.dropped})
    return result
