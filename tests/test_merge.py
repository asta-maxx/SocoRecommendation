"""ENG-15: merging the two retrieval methods into the shortlist.

The Build List's check: "The shortlist has 200 or fewer items and no duplicates."
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from reco.ranking import merge as merging
from reco.ranking.merge import METHOD_ONE, METHOD_TWO, merge, percentiles
from reco.ranking.quotas import QUOTA_SOURCES, interleave
from reco.ranking.sources import SourceItem, SourceResult

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
SHARES = {"interest": 0.4, "follows": 0.3, "trending": 0.2, "popular": 0.1}


def items(source: str, n: int, prefix: str | None = None, score=lambda k, n: float(n - k)) -> list[SourceItem]:
    prefix = prefix or source[0]
    return [SourceItem(f"{prefix}{k}", "post", source, score(k, n), NOW - timedelta(minutes=k), f"{prefix}{k}")
            for k in range(n)]


def setup(n_one: int = 400, n_similar: int = 200, similar_prefix: str = "s"):
    lists = {s: items(s, n_one) for s in QUOTA_SOURCES}
    similar = items("similar", n_similar, similar_prefix, score=lambda k, n: 1 - k / (n + 1))
    sources = SourceResult(items={**lists, "similar": similar})
    return sources, interleave(lists, 300, SHARES), similar


def check(shortlist, size: int = 200) -> None:
    ids = [i.item_id for i in shortlist.items]
    assert len(ids) <= size and len(ids) == len(set(ids))


# --- percentiles ---------------------------------------------------------------------------------


def test_percentiles_run_0_to_1_within_a_source() -> None:
    got = percentiles([SourceItem(f"p{k}", "post", "popular", float(v)) for k, v in enumerate([10, 50, 30, 20, 40])])
    assert got == {"p0": 0.0, "p3": 0.25, "p2": 0.5, "p4": 0.75, "p1": 1.0}


def test_ties_share_a_percentile_and_one_item_is_1() -> None:
    got = percentiles([SourceItem(f"p{k}", "post", "trending", float(v)) for k, v in enumerate([5, 5, 9])])
    assert got["p0"] == got["p1"] == 0.25 and got["p2"] == 1.0
    assert percentiles([SourceItem("only", "post", "follows", 3.0)]) == {"only": 1.0}
    assert percentiles([]) == {}


def test_view_counts_and_cosines_become_comparable() -> None:
    """A view count is not a cosine: only percentiles are compared."""
    sources, pool, similar = setup()
    shortlist = merge(pool, sources, similar, 200)
    assert all(0.0 <= i.percentile <= 1.0 for i in shortlist.items)
    best = {i.sources[0]: i.percentile for i in shortlist.items if i.item_id.endswith("0") and len(i.item_id) == 2}
    assert best == {"interest": 1.0, "follows": 1.0, "trending": 1.0, "popular": 1.0, "similar": 1.0}


# --- the merge and the cut -----------------------------------------------------------------------


def test_the_shortlist_is_200_with_no_duplicates() -> None:
    sources, pool, similar = setup()
    shortlist = merge(pool, sources, similar, 200)
    check(shortlist)
    assert len(shortlist.items) == 200


def test_both_methods_for_everyone_in_proportion_to_their_sizes() -> None:
    """Q8 (16 Oct, to confirm): 300 to 200 gives 3 to 2, about 120 and 80 of 200."""
    sources, pool, similar = setup()
    shortlist = merge(pool, sources, similar, 200)
    methods = [i.method for i in shortlist.items]
    assert methods.count(METHOD_ONE) == 120 and methods.count(METHOD_TWO) == 80
    assert methods[:5] == [METHOD_ONE, METHOD_TWO, METHOD_ONE, METHOD_TWO, METHOD_ONE]


def test_the_cut_follows_the_interleaved_order_so_the_quotas_survive() -> None:
    sources, pool, similar = setup()
    shortlist = merge(pool, sources, similar, 200)
    one = [i for i in shortlist.items if i.method == METHOD_ONE]
    assert [i.item_id for i in one] == [i.item_id for i in pool.items[: len(one)]]  # not re-sorted by score
    for s in QUOTA_SOURCES:
        assert abs(sum(1 for i in one if i.sources[0] == s) - len(one) * SHARES[s]) <= 1


def test_no_method_two_list_means_the_pool_alone() -> None:
    sources, pool, _ = setup()
    shortlist = merge(pool, sources, [], 200)
    assert [i.item_id for i in shortlist.items] == [i.item_id for i in pool.items[:200]]


def test_no_pool_means_the_method_two_list_alone() -> None:
    _, _, similar = setup()
    empty = interleave({s: [] for s in QUOTA_SOURCES}, 300, SHARES)
    shortlist = merge(empty, SourceResult(items={"similar": similar}), similar, 200)
    assert [i.item_id for i in shortlist.items] == [i.item_id for i in similar]


def test_a_duplicate_keeps_the_higher_percentile_and_both_tags() -> None:
    sources, pool, similar = setup(similar_prefix="i")  # method two offers interest's posts
    shortlist = merge(pool, sources, similar, 200)
    check(shortlist)
    both = [i for i in shortlist.items if "similar" in i.sources and "interest" in i.sources]
    assert both and shortlist.duplicates > 0
    i0 = next(i for i in shortlist.items if i.item_id == "i0")
    assert i0.sources == ["interest", "similar"] and i0.percentile == 1.0
    pct_interest, pct_similar = percentiles(sources.items["interest"]), percentiles(similar)
    assert all(i.percentile == max(pct_interest[i.item_id], pct_similar[i.item_id]) for i in both)
    assert any(pct_interest[i.item_id] != pct_similar[i.item_id] for i in both)  # so "the higher" is tested


def test_a_merged_repost_keeps_its_percentile() -> None:
    repost = SourceItem("rp", "post", "follows", 9.0, NOW, "orig")
    lists = {"interest": [], "follows": [repost, SourceItem("f1", "post", "follows", 1.0, NOW, "f1")],
             "trending": [], "popular": []}
    pool = interleave(lists, 300, SHARES)
    shortlist = merge(pool, SourceResult(items=lists), [], 200)
    assert [(i.item_id, i.percentile) for i in shortlist.items] == [("orig", 1.0), ("f1", 0.0)]


def test_pool_sizes_per_source_are_logged(monkeypatch, settings, caplog) -> None:
    sources, pool, similar = setup()

    async def run(settings, user_id, profile, viewer, request_id, time_limit_ms):
        return sources, pool

    async def keep(settings, offered, viewer, request_id):
        return offered

    monkeypatch.setattr(merging, "pool_for_user", run)
    monkeypatch.setattr(merging, "eligible_similar", keep)
    import asyncio

    with caplog.at_level(logging.INFO, logger="reco.retrieval"):
        shortlist = asyncio.run(merging.shortlist_for_user(settings, "u1", None, viewer=object(), request_id="r9"))
    line = next(r for r in caplog.records if r.getMessage() == "shortlist")
    assert line.request_id == "r9" and line.pool_sizes == {
        "interest": 120, "follows": 90, "trending": 60, "popular": 30, "similar": 200}
    assert line.shortlist_size == len(shortlist.items) == 200


def test_the_cap_is_the_setting(settings) -> None:
    from reco.config import live

    assert live.current().retrieval.shortlist_size == 200


# --- method two through the filters --------------------------------------------------------------


async def test_method_two_goes_through_the_filters(monkeypatch, settings, caplog) -> None:
    from tests.test_quotas import post

    similar = items("similar", 4, "s")
    platform = {i.item_id: post(i.item_id) for i in similar if i.item_id != "s3"}

    async def read_where(settings, kind, field, ids):
        return [platform[i] for i in ids if i in platform]

    async def eligible(settings, posts, viewer, request_id=None, cache=None):
        return [p for p in posts if p.post_id != "s1"]

    monkeypatch.setattr(merging.fetch, "read_where", read_where)
    monkeypatch.setattr(merging, "eligible_posts", eligible)
    with caplog.at_level(logging.INFO, logger="reco.retrieval"):
        kept = await merging.eligible_similar(settings, similar, None, "r1")
    assert [i.item_id for i in kept] == ["s0", "s2"]
    assert any(getattr(r, "rule", None) == "missing" and r.item_id == "s3" for r in caplog.records)


# --- on a database: the Build List's check -------------------------------------------------------


@pytest.mark.mongo
async def test_the_shortlist_on_a_database(store) -> None:
    """Index, method-two list and pool on a database, merged: 200 or fewer, no duplicates,
    a blocked author's similar post filtered out."""
    from bson import ObjectId
    from pymongo import AsyncMongoClient

    from reco.eligibility.apply import viewer_context
    from reco.fallback.profile import RUNG_DESCRIPTION, CategoryShare, Profile, Rung
    from reco.jobs.batches import run_batch
    from reco.ranking import post_index
    from reco.store import candidates
    from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri

    settings = store
    now = datetime.now(timezone.utc)
    client = AsyncMongoClient(_test_uri())
    platform, engine = client[TEST_PLATFORM_DB], client[TEST_DB]
    names = ("posts", "users", "businessregisters", "follows", "followers")
    engine_names = ("ml_item_state", "ml_events", "ml_job_runs", "ml_user_candidates")
    for name in names:
        await platform[name].delete_many({})
    for name in engine_names:
        await engine[name].delete_many({})
    viewer, friend, stranger, blocked = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    await platform["users"].insert_many([{"_id": u, "status": "Active", "accountIsPublic": True}
                                         for u in (viewer, friend, stranger, blocked)])
    await platform["follows"].insert_one({"_id": ObjectId(), "userId": str(viewer), "followingId": str(friend),
                                          "followingReference": "user"})
    await platform["followers"].insert_one({"_id": ObjectId(), "follower_id": viewer, "user_id": str(blocked),
                                            "status": "blocked", "isBlocked": True})

    def doc(author, cat, hours):
        return {"_id": ObjectId(), "userId": author, "timestamp": now - timedelta(hours=hours), "categories": [cat],
                "visibility": "public"}

    pets = [doc(stranger, "Pets", k + 1) for k in range(150)]
    friends = [doc(friend, "Electronics", k + 1) for k in range(100)]
    other = [doc(stranger, "Gaming", k + 1) for k in range(120)]
    bad = doc(blocked, "Gaming", 1)
    await platform["posts"].insert_many(pets + friends + other + [bad])
    await engine["ml_events"].insert_many([
        {"_id": ObjectId(), "kind": "postevent", "event_type": "view", "user_id": f"v{k}", "post_id": str(p["_id"]),
         "dwell_ms": 4000, "created_at": now - timedelta(hours=2), "undone_at": None}
        for k, p in enumerate(pets[:40] + other[:40])])
    stored = [bad, *other[:50], *pets[:10]]  # similar: a blocked author's post, new posts, and pool duplicates

    async def work(job_run_id):
        rows = [{"user_id": str(viewer), "post_id": str(p["_id"]), "score": 1 - k / 100, "rank": k + 1,
                 "method": "similar_posts", "slot": "retrieval", "job_run_id": job_run_id,
                 "model_version": settings.model_version, "config_version": "6", "computed_at": now,
                 "data_window": {"from": now - timedelta(days=30), "to": now}} for k, p in enumerate(stored)]
        await engine["ml_user_candidates"].insert_many(rows)
        return len(rows)

    profile = Profile(user_id=str(viewer), categories=[CategoryShare(category="Pets", share=1.0)], rung=Rung.PERSONALISED,
                      rung_description=RUNG_DESCRIPTION[Rung.PERSONALISED], personalised=True,
                      model_version=settings.model_version)
    try:
        await post_index.refresh(settings)
        await candidates.ensure_candidate_indexes(settings)
        await run_batch(settings, job="similar_posts", slot="retrieval", method="similar_posts",
                        collection="ml_user_candidates", data_window={"from": now - timedelta(days=30), "to": now}, work=work)
        who = await viewer_context(settings, str(viewer))
        shortlist = await merging.shortlist_for_user(settings, str(viewer), profile, who, "req", time_limit_ms=5000)
        ids = [i.item_id for i in shortlist.items]
        assert len(ids) == 200 and len(ids) == len(set(ids))
        assert str(bad["_id"]) not in ids and shortlist.excluded_method_two == 1
        assert shortlist.pool_sizes["similar"] == len(stored) - 1
        assert any(len(i.sources) == 2 for i in shortlist.items)  # a pool post also in the similar list
        assert {i.method for i in shortlist.items} == {METHOD_ONE, METHOD_TWO}
    finally:
        for name in names:
            await platform[name].delete_many({})
        for name in engine_names:
            await engine[name].delete_many({})
        await client.close()
