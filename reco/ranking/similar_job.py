"""M2 retrieval method two, the nightly job. ENG-14.

    python -m reco.jobs similar_posts

1. The pool: the eligible posts of the last retrieval.post_age_days (30), at most
   retrieval.similar_max_posts (5,000), the most recent first; each gets its vector
   (reco.ranking.similar.post_vector).
2. Each user's profile from their last retrieval.similar_engaged_posts (50) engaged
   posts (the engine's copies of postevents, and of orders for purchases made from a
   post: Nisha, 16 Oct 2026), weighted by the ENG-10 action weights and the
   interest.half_life_days (30) decay. A user with fewer than
   retrieval.similar_min_engaged (3) engaged posts gets no list.
3. The top retrieval.similar_top_stored (200) pool posts per user by cosine, leaving
   out the posts the profile was built from (Nisha, 16 Oct 2026), written
   to ml_user_candidates as one ENG-07 batch (run_batch): requests read only the
   batch marked current (reco.store.candidates.read_user_candidates).

Engaged posts may be older than 30 days or no longer eligible: their vector is built
by the same rule (the pool's rules decide what can be recommended, not what a
user's taste is read from). Posts the platform no longer has have no vector.

Post types outside retrieval.post_types are counted under "other" and reported in
the job's log line (Kala, 16 Oct 2026).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from reco.config import Settings, live
from reco.config.accounts import test_account_ids
from reco.jobs.batches import run_batch
from reco.platform import fetch
from reco.platform.readers import vocabulary
from reco.platform.records import PostRecord
from reco.ranking import similar
from reco.store import candidates, writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.job")

_IDS_PER_READ = 500


async def _read_chunked(settings: Settings, kind: str, ids: list[str]) -> list[Any]:
    found: list[Any] = []
    for start in range(0, len(ids), _IDS_PER_READ):
        found += await fetch.read_where(settings, kind, "_id", ids[start:start + _IDS_PER_READ])
    return found


async def _authors(settings: Settings, ids: set[str]) -> dict[str, Any]:
    """An author may be a user or a business account (as in reco.eligibility.apply)."""
    wanted = sorted(i for i in ids if i)
    users, businesses = await asyncio.gather(_read_chunked(settings, "user", wanted),
                                             _read_chunked(settings, "business", wanted))
    return {**{u.user_id: u for u in users}, **{b.business_id: b for b in businesses}}


def data_window(anchor: datetime) -> dict[str, datetime]:
    return {"from": anchor - timedelta(days=live.current().retrieval.post_age_days), "to": anchor}


async def compute(settings: Settings, anchor: datetime) -> tuple[dict[str, list[tuple[str, float]]], dict[str, Any]]:
    """Every user's top list ({user_id: [(post_id, score), ...]}) and the counts to report."""
    tunables = live.current()
    retrieval = tunables.retrieval
    names = vocabulary(settings).canonical
    post_types = retrieval.post_types
    since = anchor - timedelta(days=retrieval.post_age_days)
    report: dict[str, Any] = {}

    def vector(post: PostRecord, types: Counter, unlisted: Counter) -> similar.Vector:
        kind, listed = similar.post_type_of(post.post_type_detailed, post.post_type, post_types)
        types[kind] += 1
        if not listed:
            unlisted[similar.raw_type_of(post.post_type_detailed, post.post_type)] += 1
        return similar.post_vector(post.categories, kind, similar.days_between(post.created_at, anchor), names, post_types)

    # 1. The pool.
    recent = await fetch.read_posts_since(settings, since)
    authors = await _authors(settings, {p.author_id for p in recent})
    left_out: Counter = Counter()
    eligible: list[PostRecord] = []
    for post in recent:
        why = similar.post_is_eligible(post, authors.get(post.author_id))
        if why:
            left_out[why] += 1
        else:
            eligible.append(post)
    pool_posts = eligible[:retrieval.similar_max_posts]  # newest first already
    types: Counter = Counter()
    unlisted: Counter = Counter()
    vectors = {p.post_id: vector(p, types, unlisted) for p in pool_posts}
    pool = [similar.PoolPost.of(p.post_id, p.created_at, vectors[p.post_id]) for p in pool_posts]
    report.update(posts_read=len(recent), posts_left_out=dict(left_out), posts_eligible=len(eligible),
                  pool=len(pool), post_types=dict(types), unlisted_post_types=dict(unlisted))
    if unlisted:
        logger.warning("post types not in retrieval.post_types, counted as other",
                       extra={"job": candidates.JOB, "unlisted_post_types": dict(unlisted)})

    # 2. The profiles.
    rows = await candidates.read_engaged_rows(settings)
    engaged_ids = sorted({str(r["post_id"]) for r in rows if r.get("post_id")})
    known = {p.post_id: p for p in recent}
    missing = [pid for pid in engaged_ids if pid not in known]
    for start in range(0, len(missing), _IDS_PER_READ):
        known |= await fetch.read_posts(settings, missing[start:start + _IDS_PER_READ])
    weights = tunables.interest.weights.model_dump()
    tests = test_account_ids(anchor.date())

    # Purchases made from a post (ENG-10's rules, as M1: ENG-30 points 7 and 10).
    current, why = await writers.return_requests_current(
        settings, anchor, tunables.commerce.return_request_current_hours)
    if not current:
        logger.warning("return-request copy not current; similar posts run on the last good copy", extra={"why": why})
    orders = await writers.read_order_copies(settings)
    bought_ids = sorted({str(o["post_id"]) for o in orders if o.get("post_id")} - set(known))
    for start in range(0, len(bought_ids), _IDS_PER_READ):
        known |= await fetch.read_posts(settings, bought_ids[start:start + _IDS_PER_READ])
    seed = {pid for pid, p in known.items() if p.is_seed}
    statuses = tunables.lists.order_status
    purchases, purchase_skipped = similar.kept_purchases(
        orders, anchor=anchor, reversed_statuses=(statuses.cancelled, statuses.rejected, statuses.returned),
        open_requests=await writers.read_open_return_orders(settings), seed_posts=seed, test_accounts=tests)
    read = similar.engaged_by_user(
        rows, anchor=anchor, weights=weights, half_life_days=tunables.interest.half_life_days,
        qualified_view_ms=tunables.events.qualified_view_seconds * 1000,
        seed_posts=seed, test_accounts=tests, purchases=purchases,
    )
    read.skipped.update(purchase_skipped)
    report.update(purchases=len(purchases), return_requests="current" if current else why)
    engaged_vectors: dict[str, similar.Vector] = dict(vectors)
    profile_types: Counter = Counter()
    profile_unlisted: Counter = Counter()
    for pid in {pid for posts in read.by_user.values() for pid in posts}:
        if pid not in engaged_vectors and pid in known and known[pid].created_at is not None:
            engaged_vectors[pid] = vector(known[pid], profile_types, profile_unlisted)

    # 3. The lists.
    lists: dict[str, list[tuple[str, float]]] = {}
    too_few = 0
    for user_id in sorted(read.by_user):
        profile = similar.user_profile(read.by_user[user_id], engaged_vectors,
                                       last_posts=retrieval.similar_engaged_posts,
                                       min_engaged=retrieval.similar_min_engaged)
        if profile is None:
            too_few += 1
            continue
        used = set(similar.last_engaged(read.by_user[user_id], engaged_vectors, retrieval.similar_engaged_posts))
        top = similar.top_similar(profile, pool, retrieval.similar_top_stored, exclude=used)
        if top:
            lists[user_id] = top
    report.update(engaged_only_unlisted_post_types=dict(profile_unlisted), engaged_rows=len(rows), engaged_skipped=dict(read.skipped), users_engaged=len(read.by_user),
                  users_too_few_engaged=too_few, users_listed=len(lists))
    return lists, report


async def run(settings: Settings, anchor: datetime | None = None) -> dict[str, Any]:
    """Compute and write one batch; it becomes current only once complete."""
    anchor = anchor or utc_now()
    window = data_window(anchor)
    report: dict[str, Any] = {}

    async def work(job_run_id: str) -> int:
        lists, counts = await compute(settings, anchor)
        report.update(counts)
        computed_at = utc_now()
        common = {"method": candidates.METHOD, "slot": candidates.SLOT, "job_run_id": job_run_id,
                  "model_version": settings.model_version, "config_version": live.current().config_version,
                  "computed_at": computed_at, "data_window": window}
        rows = [{"user_id": user_id, "post_id": post_id, "score": score, "rank": rank, **common}
                for user_id, top in lists.items() for rank, (post_id, score) in enumerate(top, start=1)]
        return await candidates.write_user_candidates(settings, rows)

    record = await run_batch(settings, job=candidates.JOB, slot=candidates.SLOT, method=candidates.METHOD,
                             collection=candidates.COLLECTION, data_window=window, work=work)
    report.update(job_run_id=record["_id"], rows_written=record["rows_written"])
    return report
