"""The launch ranking layer for the feed. ENG-19.

    built = await feed_candidates(settings, page, limit, user_id, request_id, profile, promoter_method, served)

Build List v1.4 ENG-19: score each shortlisted post (ENG-15), each component on
0 to 1, the interest and promoter parts from the methods assigned to the viewer
(ENG-05):

    interest match      0.35  the viewer's M1 share for the post's category (the
                              highest share where a post has several)
    retrieval score     0.15  the post's ENG-15 percentile, as a percentile within
                              the shortlist
    promoter score      0.20  the author's M8 score; an author with none: the median
                              of their category (Kala, 16 Oct, Q8: the post's own
                              category, several: the average of their medians; else
                              the platform median; else 0.5)
    freshness           0.20  0.5 ** (age in days / 3)
    engagement quality  0.10  (likes + saves + shares + comments) per qualified view,
                              pulled toward the shortlist's average by 50 views, as a
                              percentile within the shortlist

Commission never enters this score (nothing here reads it). Ties: newer first,
then post id.

Variety, applied while filling the page (`fill_page`): no more than 2 posts in a
row from the same author; at most 3 per author on a page; at most
ceil(0.4 x limit) from one category, never fewer than 2. If the page cannot be
filled, relax in this order until it is full, and log which was relaxed: the
category cap, then the per-author cap, then the consecutive-author rule. Filling
the page always wins over variety. Each next place goes to the best-ranked post
that keeps the rules in force.

Paging: page 1 is the top of the ranked list. On page 2 and later every item
served to the user in the last serving.page_dedup_hours (24) on the feed is left
out (their request records), then the next `limit` are taken; positions start at
1 in each response. Exploration (ENG-06) and the recheck (ENG-08) follow in the
request path; after the exploration shuffle `keep_consecutive_rule` swaps
neighbours where the consecutive-author rule broke.

Where the pack is silent (decided 17 Oct 2026, docs/engineering/ENG-19.md): a
post's category for the category cap is the one its interest match used (the
viewer's highest share among its categories; a post with none of the 23 has no
cap); the author with no score: their category is not known to M8 (only scored
promoters are), so the ladder starts at the post's own categories; a shortlist
shorter than the page (no post index yet, a new user with nothing to retrieve)
is topped up with ENG-06's eligible posts, newest first, after the ranked ones,
so the feed is never empty for want of candidates.
"""

from __future__ import annotations

import logging
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from reco.config import Settings, live
from reco.eligibility.apply import viewer_context
from reco.fallback.profile import Profile
from reco.platform import fetch
from reco.ranking import merge, serving
from reco.ranking.serving import Built, Candidate
from reco.store import item_state
from reco.store import promoter as promoter_store

logger = logging.getLogger("reco.ranking")

ORDERING = "eng19_feed_ranking"
COMPONENTS = ("interest", "retrieval", "promoter", "freshness", "engagement_quality")
RELAX_ORDER = ("category_cap", "per_author_cap", "consecutive_author")


# --- scoring (pure) ---------------------------------------------------------------------------


@dataclass
class Post:
    """A shortlisted post with what the formula needs."""

    post_id: str
    author_id: str
    categories: list[str]
    created_at: datetime | None
    retrieval: float  # its ENG-15 percentile within its own source
    views: int = 0  # qualified views (people)
    engagements: int = 0  # likes + saves + shares + comments
    item_type: str = "post"
    product_id: str | None = None


@dataclass
class Scored:
    post: Post
    score: float
    parts: dict[str, float]
    category: str | None  # the one its interest match used; the category cap counts it
    promoter_source: str  # "own", "category_median", "platform_median", "default"


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """0 to 1 within the group, ties counted half; a group of one: 1 (the best of one)."""
    n = len(values)
    if n == 1:
        return {k: 1.0 for k in values}
    ordered = sorted(values.values())
    return {k: (bisect_left(ordered, v) + (bisect_right(ordered, v) - bisect_left(ordered, v) - 1) / 2) / (n - 1)
            for k, v in values.items()}


def interest_match(categories: Iterable[str], shares: dict[str, float]) -> tuple[float, str | None]:
    """The viewer's highest share among the post's categories, and which category it was."""
    best, which = 0.0, None
    for category in categories:
        share = shares.get(category, 0.0)
        if which is None or share > best:
            best, which = share, category
    return best, which


def promoter_part(author_id: str, categories: list[str], scores: dict[str, float],
                  medians: dict[str, float], platform: float | None) -> tuple[float, str]:
    """The author's M8 score, else Kala's ladder (Q8)."""
    if author_id in scores:
        return scores[author_id], "own"
    known = [medians[c] for c in categories if c in medians]
    if known:
        return sum(known) / len(known), "category_median"
    if platform is not None:
        return platform, "platform_median"
    return 0.5, "default"


def freshness(created_at: datetime | None, now: datetime, half_life_days: float) -> float:
    if created_at is None:
        return 0.0
    age = max(0.0, (now - created_at).total_seconds() / 86400)
    return 0.5 ** (age / half_life_days)


def score_posts(posts: list[Post], *, shares: dict[str, float], promoter_scores: dict[str, float],
                medians: dict[str, float], platform_median: float | None, now: datetime,
                weights: dict[str, float], half_life_days: float, shrinkage_views: float) -> list[Scored]:
    """The ENG-19 formula for every post, best first (ties: newer, then post id)."""
    if not posts:
        return []
    retrieval = percentile_ranks({p.post_id: p.retrieval for p in posts})
    total_views = sum(p.views for p in posts)
    average = sum(p.engagements for p in posts) / total_views if total_views else 0.0
    quality = {p.post_id: (p.engagements + shrinkage_views * average) / (p.views + shrinkage_views) for p in posts}
    quality_pct = percentile_ranks(quality)
    out = []
    for p in posts:
        interest, category = interest_match(p.categories, shares)
        promoter, source = promoter_part(p.author_id, p.categories, promoter_scores, medians, platform_median)
        parts = {"interest": interest, "retrieval": retrieval[p.post_id], "promoter": promoter,
                 "freshness": freshness(p.created_at, now, half_life_days), "engagement_quality": quality_pct[p.post_id]}
        out.append(Scored(p, sum(weights[c] * parts[c] for c in COMPONENTS), parts, category, source))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(out, key=lambda s: (-s.score, -(s.post.created_at or epoch).timestamp(), s.post.post_id))


# --- variety (pure) ---------------------------------------------------------------------------


@dataclass
class VarietyRules:
    max_consecutive: int = 2
    max_per_author: int = 3
    category_cap: int = 2

    @classmethod
    def for_page(cls, limit: int, tunables: Any) -> VarietyRules:
        r = tunables.ranking
        return cls(r.max_consecutive_same_author, r.max_per_author_per_page,
                   max(r.min_category_cap, math.ceil(r.max_category_fraction * limit)))


def _fits(item: Scored, page: list[Scored], rules: VarietyRules, relaxed: set[str]) -> bool:
    author = item.post.author_id
    if "consecutive_author" not in relaxed and len(page) >= rules.max_consecutive and all(
            s.post.author_id == author for s in page[-rules.max_consecutive:]):
        return False
    if "per_author_cap" not in relaxed and sum(s.post.author_id == author for s in page) >= rules.max_per_author:
        return False
    if ("category_cap" not in relaxed and item.category is not None
            and sum(s.category == item.category for s in page) >= rules.category_cap):
        return False
    return True


def fill_page(ranked: list[Scored], limit: int, rules: VarietyRules) -> tuple[list[Scored], list[str]]:
    """The page: each place to the best-ranked post that keeps the rules in force,
    relaxing them in RELAX_ORDER only when the page could not otherwise be filled.
    Returns the page and the rules relaxed."""
    want = min(limit, len(ranked))
    relaxed: list[str] = []
    while True:
        page: list[Scored] = []
        left = list(ranked)
        while len(page) < want:
            pick = next((s for s in left if _fits(s, page, rules, set(relaxed))), None)
            if pick is None:
                break
            page.append(pick)
            left.remove(pick)
        if len(page) == want or len(relaxed) == len(RELAX_ORDER):
            return page, relaxed
        relaxed.append(RELAX_ORDER[len(relaxed)])


def keep_consecutive_rule(items: list[Candidate], max_consecutive: int = 2) -> list[Candidate]:
    """After the exploration shuffle: where more than `max_consecutive` posts of one
    author stand in a row, swap the offending one with the nearest later post by
    another author, so shuffling cannot undo variety."""
    items = list(items)
    for i in range(max_consecutive, len(items)):
        author = items[i].author_id
        if author and all(items[j].author_id == author for j in range(i - max_consecutive, i)):
            swap = next((j for j in range(i + 1, len(items)) if items[j].author_id != author), None)
            if swap is not None:
                items[i], items[swap] = items[swap], items[i]
    return items


# --- the request -------------------------------------------------------------------------------


@dataclass
class FeedDetail:
    shortlist: int = 0
    scored: int = 0
    topped_up: int = 0
    left_out_served: int = 0
    relaxed: list[str] = field(default_factory=list)
    promoter_sources: dict[str, int] = field(default_factory=dict)


async def feed_candidates(
    settings: Settings, page: int, limit: int, user_id: str | None, request_id: str | None,
    profile: Profile | None, promoter_method: str | None, served: set[str] | None = None,
    time_limit_ms: float | None = None,
) -> Built:
    """The feed's list for one request: shortlist (ENG-15), scored, the served items
    left out on later pages, the page filled under the variety rules, then the rest
    in rank order as spares for the recheck. Already paged (Built.page_start = 0)."""
    tunables = live.current()
    now = datetime.now(timezone.utc)
    viewer = await viewer_context(settings, user_id)
    shortlist = await merge.shortlist_for_user(settings, user_id, profile, viewer, request_id, time_limit_ms)
    ids = [i.item_id for i in shortlist.items]
    batch = await item_state.current_batch(settings)
    records, index_rows = await _read(settings, ids, batch)
    authors = sorted({r.author_id for r in records.values()})
    method = promoter_method or tunables.slots.promoter_score.method_one
    promoter_scores = await promoter_store.read_promoter_scores(settings, authors, method)
    medians, platform = await promoter_store.read_medians(settings, method)

    posts = []
    for item in shortlist.items:
        record = records.get(item.item_id)
        if record is None:
            continue  # gone from the platform since the shortlist was read; the recheck would drop it too
        row = index_rows.get(item.item_id, {})
        card = serving._post_card(record)
        posts.append(Post(item.item_id, record.author_id, record.categories, record.created_at, item.percentile,
                          int(row.get("qualified_views") or 0), int(row.get("engagements") or 0),
                          item_type=card[1], product_id=card[3]))
    shares = {c.category: c.share for c in profile.categories} if profile else {}
    weights = tunables.ranking.weights.model_dump()
    ranked = score_posts(posts, shares=shares, promoter_scores=promoter_scores, medians=medians,
                         platform_median=platform, now=now, weights=weights,
                         half_life_days=tunables.ranking.freshness_half_life_days,
                         shrinkage_views=tunables.ranking.engagement_shrinkage_views)
    detail = FeedDetail(shortlist=len(shortlist.items), scored=len(ranked))
    for s in ranked:
        detail.promoter_sources[s.promoter_source] = detail.promoter_sources.get(s.promoter_source, 0) + 1
    if page > 1 and served:
        kept = [s for s in ranked if s.post.post_id not in served]
        detail.left_out_served = len(ranked) - len(kept)
        ranked = kept

    page_items, detail.relaxed = fill_page(ranked, limit, VarietyRules.for_page(limit, tunables))
    if detail.relaxed:
        logger.info("variety relaxed to fill the page", extra={"request_id": request_id, "relaxed": detail.relaxed})
    chosen = {s.post.post_id for s in page_items}
    ordered = page_items + [s for s in ranked if s.post.post_id not in chosen]
    candidates = [Candidate(s.post.post_id, s.post.item_type, s.post.post_id, s.post.product_id, rank=n,
                            score=round(s.score, 6), author_id=s.post.author_id)
                  for n, s in enumerate(ordered, start=1)]

    # A shortlist shorter than the page and a spare page: ENG-06's eligible posts,
    # newest first, after the ranked ones (decided 17 Oct 2026).
    wanted = 2 * limit
    if len(candidates) < wanted:
        interim = await serving.interim_candidates(settings, "feed", 1, wanted, None, user_id, request_id)
        have = {c.item_id for c in candidates} | (served if page > 1 and served else set())
        extra = [c for c in interim.candidates if c.item_id not in have][:wanted - len(candidates)]
        detail.topped_up = len(extra)
        candidates += [Candidate(c.item_id, c.item_type, c.post_id, c.product_id, rank=len(candidates) + n,
                                 author_id=c.author_id) for n, c in enumerate(extra, start=1)]
    logger.info("feed ranked", extra={"request_id": request_id, **detail.__dict__})
    return Built(viewer, candidates, {}, len(ids), detail={"ordering": ORDERING, **detail.__dict__}, page_start=0)


async def _read(settings: Settings, ids: list[str], batch: str | None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not ids:
        return {}, {}
    records = {p.post_id: p for p in await fetch.read_where(settings, "post", "_id", ids)}
    return records, await item_state.read_posts_by_ids(settings, batch, ids)
