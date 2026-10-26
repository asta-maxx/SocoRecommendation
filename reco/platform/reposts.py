"""Reposts led back to their original. ENG-30 point 3 (used by ENG-13, ENG-16, ENG-21).

    originals, report, known = await resolve_originals(settings, posts)
    originals["p9"]  -> "p1"   the original of repost p9
    originals["p1"]  -> "p1"   a post that is not a repost is its own original
    originals["p7"]  -> None   a broken chain: no original (logged)

Build List v1.4 ENG-30 point 3: while a post has isRepost true, follow
repostDetails.originalPostId to the post it reshared, until a post that is not a
repost (the original). Stop after commerce.repost_chain_max_steps (10) or on a loop.
If a link is missing, there is no original, and the break is logged.

The chain is walked one level at a time: each level is one read of the parents
not yet in hand, so a chain of 10 costs at most 10 reads however many posts are
resolved together. A parent may be older than any window: it is read by id.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Iterable

from reco.config import Settings, live
from reco.platform import fetch
from reco.platform.records import PostRecord

logger = logging.getLogger("reco.reposts")

#: Why a chain has no original.
MISSING_LINK = "missing_link"  # isRepost true but no originalPostId
MISSING_POST = "missing_post"  # originalPostId names a post that is not there
LOOP = "loop"
TOO_LONG = "too_long"


def original_of(post_id: str, known: dict[str, PostRecord | None], max_steps: int) -> tuple[str | None, str | None]:
    """(original id, None), or (None, the reason the chain broke). `known` holds every
    post on the chain that could be read (None: looked for, not found)."""
    seen = {post_id}
    current = known.get(post_id)
    steps = 0
    while current is not None and current.is_repost:
        if steps >= max_steps:
            return None, TOO_LONG
        parent = current.repost_of
        if not parent:
            return None, MISSING_LINK
        if parent in seen:
            return None, LOOP
        seen.add(parent)
        current = known.get(parent)
        if current is None:
            return None, MISSING_POST
        steps += 1
    return (current.post_id if current is not None else None), (None if current is not None else MISSING_POST)


async def resolve_originals(
    settings: Settings, posts: Iterable[PostRecord], max_steps: int | None = None
) -> tuple[dict[str, str | None], Counter[str], dict[str, PostRecord | None]]:
    """The original of every post given, reading the missing parents level by level.
    Returns the originals, a count of reposts by outcome (resolved or the break), and
    every post read on the way (None: looked for, not found)."""
    limit = max_steps if max_steps is not None else live.current().commerce.repost_chain_max_steps
    posts = list(posts)
    known: dict[str, PostRecord | None] = {p.post_id: p for p in posts}
    wanted = {p.repost_of for p in posts if p.is_repost and p.repost_of}
    for _ in range(limit):
        missing = sorted(i for i in wanted if i not in known)
        if not missing:
            break
        found = {p.post_id: p for p in await fetch.read_where(settings, "post", "_id", missing)}
        known.update({i: found.get(i) for i in missing})
        wanted = {p.repost_of for p in found.values() if p.is_repost and p.repost_of}
    originals: dict[str, str | None] = {}
    report: Counter[str] = Counter()
    for post in posts:
        original, broken = original_of(post.post_id, known, limit)
        originals[post.post_id] = original
        if post.is_repost:
            report[broken or "resolved"] += 1
            if broken:
                logger.warning("repost with no original", extra={"post_id": post.post_id, "reason": broken})
    return originals, report, known
