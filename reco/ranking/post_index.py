"""The post index job: recent posts and their 7-day qualified views. ENG-12.

    python -m reco.jobs post_index     one refresh (the sync loop runs it every
                                       filters.eligibility_refresh_minutes, 15)

Why it exists: the candidate sources (reco.ranking.sources) must each answer in
20 ms (retrieval.source_time_limit_ms) and a request never calculates anything
(SD-17). Trending and popular need each post's qualified views over 7 days, and
the interest source needs each post's categories matched to the 23; neither can
be worked out inside a request. So they are worked out here, written whole as a
batch, and read by the sources.

Per post created in the last retrieval.post_age_days (30): post_id, author_id,
categories (one of the 23), created_at, is_repost, and qualified_views_7d: the
number of people with a qualified view (dwell_ms >= events.qualified_view_seconds)
of it in the last 7 days, from the engine's copy of postevents, test accounts left
out (ENG-29 item 3). Seed posts (_seedTag, ENG-30 point 9) are test data and are
not indexed, so no source ever offers one.

Each row also carries original_id (ENG-30 point 3, for ENG-13's "a repost counts
as its original"): the post itself, or for a repost the original its chain leads
to. A repost whose chain breaks keeps original_id None and is offered as itself
(the break is logged); a repost of a seed post is not indexed.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from reco.config import Settings, live
from reco.config.accounts import test_account_ids
from reco.platform.recent import read_recent_posts
from reco.platform.reposts import resolve_originals
from reco.store import item_state, writers

#: The window of trending and popular (Build List ENG-12 sources 3 and 4).
VIEWS_WINDOW_DAYS = 7


def data_window(now: datetime) -> dict[str, datetime]:
    return {"from": now - timedelta(days=live.current().retrieval.post_age_days), "to": now}


async def build_post_index(settings: Settings, now: datetime, job_run_id: str) -> tuple[int, dict[str, int]]:
    tunables = live.current()
    posts = await read_recent_posts(settings, data_window(now)["from"])
    tests = test_account_ids()
    pairs = await writers.read_qualified_views(
        settings, now - timedelta(days=VIEWS_WINDOW_DAYS), tunables.events.qualified_view_seconds * 1000)
    views = Counter(str(p["post_id"]) for p in pairs if str(p.get("user_id") or "").lower() not in tests)
    originals, reposts, known = await resolve_originals(settings, posts)
    rows: list[dict[str, Any]] = []
    seed = 0
    for post in posts:
        original = originals.get(post.post_id)
        if post.is_seed or getattr(known.get(original or ""), "is_seed", False):
            seed += 1
            continue
        rows.append({
            "_id": f"{job_run_id}:{post.post_id}", "kind": "post", "method": item_state.METHOD,
            "job_run_id": job_run_id, "computed_at": now, "config_version": tunables.config_version,
            "post_id": post.post_id, "author_id": post.author_id, "categories": post.categories,
            "created_at": post.created_at, "is_repost": post.is_repost,
            "original_id": original, "qualified_views_7d": views.get(post.post_id, 0),
        })
    written = await item_state.write_post_index(settings, rows)
    return written, {"posts_read": len(posts), "seed_posts_left_out": seed,
                     "posts_with_views": sum(1 for r in rows if r["qualified_views_7d"]),
                     "reposts": dict(reposts)}


async def refresh(settings: Settings) -> dict[str, Any]:
    """One refresh, written whole as an ENG-07 batch and then made current."""
    from reco.jobs.batches import run_batch
    from reco.store.scores import utc_now

    now = utc_now()
    detail: dict[str, Any] = {}
    await item_state.ensure_post_index_indexes(settings)

    async def work(job_run_id: str) -> int:
        written, detail["counts"] = await build_post_index(settings, now, job_run_id)
        return written

    record = await run_batch(settings, job=item_state.JOB, slot="retrieval", method=item_state.METHOD,
                             collection="ml_item_state", data_window=data_window(now), work=work)
    return {"job_run_id": record["_id"], "posts": record["rows_written"], **detail.get("counts", {})}
