"""ENG-13: the method-one pool (quotas), and ENG-30 point 3 (reposts led to their original).

The Build List's check: "The pool size is 300 or fewer, quotas are within 1 item,
and there are no duplicates."
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from reco.platform import reposts
from reco.platform.records import PostRecord
from reco.platform.reposts import original_of, resolve_originals
from reco.ranking import quotas
from reco.ranking.quotas import QUOTA_SOURCES, build_pool, interleave
from reco.ranking.sources import SourceItem, SourceResult

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
SHARES = {"interest": 0.4, "follows": 0.3, "trending": 0.2, "popular": 0.1}


def items(source: str, n: int, prefix: str | None = None, start: int = 0) -> list[SourceItem]:
    prefix = prefix or source[0]
    return [SourceItem(f"{prefix}{k}", "post", source, float(n - k), NOW - timedelta(minutes=k), f"{prefix}{k}")
            for k in range(start, start + n)]


def full(n: int = 400) -> dict[str, list[SourceItem]]:
    return {s: items(s, n) for s in QUOTA_SOURCES}


def check(pool, size: int = 300) -> None:
    """The Build List's check, as code."""
    assert len(pool.items) <= size
    keys = [i.item_id for i in pool.items]
    assert len(keys) == len(set(keys))
    for s in QUOTA_SOURCES:
        assert abs(pool.taken[s] - pool.quotas[s]) <= 1


def post(post_id: str, **fields) -> PostRecord:
    values = dict(post_id=post_id, author_id="a", created_at=NOW, categories=["Pets"], categories_dropped=[],
                  post_type="normal", post_type_detailed=None, is_hidden=False, visibility="public",
                  compliance_status=None, product_status=None, age_group=None, is_repost=False, product_ids=[])
    values.update(fields)
    return PostRecord(**values)


# --- quotas and the interleave ------------------------------------------------------------------


def test_quotas_are_the_shares_of_300_and_sum_exactly() -> None:
    assert quotas.quotas(300, SHARES) == {"interest": 120, "follows": 90, "trending": 60, "popular": 30}
    odd = quotas.quotas(7, SHARES)
    assert sum(odd.values()) == 7 and all(abs(odd[s] - 7 * SHARES[s]) < 1 for s in QUOTA_SOURCES)


def test_the_shares_are_the_setting(settings) -> None:
    assert quotas.shares_in_force() == SHARES


def test_a_full_pool_is_300_in_the_proportions_with_every_source_tag() -> None:
    pool = interleave(full(), 300, SHARES)
    check(pool)
    assert len(pool.items) == 300 and pool.taken == {"interest": 120, "follows": 90, "trending": 60, "popular": 30}
    assert all(i.item_id[0] == i.source[0] for i in pool.items)  # each keeps its own source's tag


def test_round_robin_keeps_the_proportions_in_every_prefix() -> None:
    """ENG-15 cuts by this order, so the quotas must hold all the way down."""
    pool = interleave(full(), 300, SHARES)
    assert [i.source for i in pool.items[:10]] == [
        "interest", "follows", "trending", "interest", "follows", "popular", "interest", "trending", "follows", "interest"]
    for cut in (10, 50, 200):
        head = pool.items[:cut]
        for s in QUOTA_SOURCES:
            assert abs(sum(1 for i in head if i.source == s) - cut * SHARES[s]) <= 1


def test_each_source_keeps_its_own_order() -> None:
    pool = interleave(full(), 300, SHARES)
    follows = [i.item_id for i in pool.items if i.source == "follows"]
    assert follows == [f"f{k}" for k in range(90)]


def test_a_short_source_passes_its_share_to_the_next_in_order() -> None:
    lists = full()
    lists["follows"] = items("follows", 10)
    pool = interleave(lists, 300, SHARES)
    check(pool)
    assert len(pool.items) == 300
    assert pool.taken["follows"] == 10 and pool.taken["trending"] == 60 + 80  # follows' 80 go to trending
    assert pool.taken["interest"] == 120 and pool.taken["popular"] == 30


def test_a_short_share_moves_on_again_when_the_next_source_is_short_too() -> None:
    lists = full()
    lists["follows"] = items("follows", 10)
    lists["trending"] = items("trending", 70)
    pool = interleave(lists, 300, SHARES)
    check(pool)
    assert pool.taken == {"interest": 120, "follows": 10, "trending": 70, "popular": 100}


def test_popular_short_wraps_round_to_interest() -> None:
    """The pack names no source after popular; decided 16 Oct 2026: wrap to interest."""
    lists = full()
    lists["popular"] = items("popular", 5)
    pool = interleave(lists, 300, SHARES)
    assert pool.taken == {"interest": 145, "follows": 90, "trending": 60, "popular": 5}


def test_when_every_source_is_short_the_pool_is_smaller() -> None:
    lists = {s: items(s, 20) for s in QUOTA_SOURCES}
    pool = interleave(lists, 300, SHARES)
    check(pool)
    assert len(pool.items) == 80 and set(pool.taken.values()) == {20}


def test_overlapping_short_sources_still_use_every_unique_post() -> None:
    """Regression, 16 Oct: trending and popular offer only interest's posts, and every
    source is short; the pool takes every unique post and the quotas match what each filled."""
    lists = {"interest": items("interest", 60, "x"), "follows": items("follows", 21),
             "trending": items("trending", 25, "x"), "popular": items("popular", 30, "x")}
    pool = interleave(lists, 300, SHARES)
    check(pool)
    assert len(pool.items) == 81 and pool.quotas == pool.taken


def test_no_sources_give_an_empty_pool() -> None:
    pool = interleave({s: [] for s in QUOTA_SOURCES}, 300, SHARES)
    assert pool.items == [] and sum(pool.taken.values()) == 0


def test_duplicates_are_removed_and_never_cost_a_place() -> None:
    lists = full()
    lists["trending"] = items("trending", 400, prefix="i")  # the same posts as interest
    pool = interleave(lists, 300, SHARES)
    check(pool)
    assert len(pool.items) == 300 and pool.duplicates > 0
    assert pool.taken["trending"] == 60  # trending skipped interest's posts and took its next


def test_a_repost_counts_as_its_original() -> None:
    original = SourceItem("orig", "post", "interest", 9.0, NOW, "orig")
    repost = SourceItem("rp", "post", "follows", 8.0, NOW, "orig")
    lists = {"interest": [original], "follows": [repost, *items("follows", 3)], "trending": [], "popular": []}
    pool = interleave(lists, 300, SHARES)
    assert [i.item_id for i in pool.items].count("orig") == 1 and "rp" not in [i.item_id for i in pool.items]
    alone = interleave({"interest": [], "follows": [repost], "trending": [], "popular": []}, 300, SHARES)
    assert [(i.item_id, i.source) for i in alone.items] == [("orig", "follows")]  # merged, tag kept
    assert alone.reposts_merged == {"orig": "rp"}


def test_pool_size_is_the_setting() -> None:
    pool = interleave(full(), 100, SHARES)
    check(pool, 100)
    assert pool.taken == {"interest": 40, "follows": 30, "trending": 20, "popular": 10}


# --- the filters before and after ---------------------------------------------------------------


@pytest.fixture
def platform(monkeypatch):
    """Posts on a pretend platform; ENG-08 stood in by a set of failing posts."""
    state = {"posts": {}, "failing": set()}

    async def read_where(settings, kind, field, ids):
        return [state["posts"][i] for i in ids if i in state["posts"]]

    async def eligible(settings, posts, viewer, request_id=None, cache=None):
        return [p for p in posts if p.post_id not in state["failing"]]

    monkeypatch.setattr(quotas.fetch, "read_where", read_where)
    monkeypatch.setattr(quotas, "eligible_posts", eligible)
    return state


async def test_filters_apply_before_quotas(platform, settings) -> None:
    lists = full(200)
    platform["posts"] = {i.item_id: post(i.item_id) for s in lists for i in lists[s]}
    platform["failing"] = {f"f{k}" for k in range(150)}
    pool = await build_pool(settings, SourceResult(items=lists), viewer=None, request_id="r1")
    check(pool)
    assert len(pool.items) == 300 and pool.excluded_before == 150
    assert not {i.item_id for i in pool.items} & platform["failing"]
    assert pool.taken["follows"] == 50 and pool.taken["trending"] == 100  # follows short after the filter


async def test_filters_apply_after_to_the_original_a_repost_brings(platform, settings) -> None:
    repost = SourceItem("rp", "post", "follows", 1.0, NOW, "orig")
    lists = {"interest": items("interest", 5), "follows": [repost, *items("follows", 5)], "trending": [], "popular": []}
    platform["posts"] = {i.item_id: post(i.item_id) for s in lists for i in lists[s]}
    platform["posts"]["orig"] = post("orig", author_id="blocked")
    platform["failing"] = {"orig"}  # the repost passes, its original does not
    pool = await build_pool(settings, SourceResult(items=lists), viewer=None)
    ids = [i.item_id for i in pool.items]
    assert "orig" not in ids and "rp" not in ids and pool.excluded_after == 1
    assert len(ids) == 10  # rebuilt without it, still full from what is left


async def test_a_post_no_longer_on_the_platform_is_excluded_and_logged(platform, settings, caplog) -> None:
    lists = {"interest": items("interest", 3), "follows": [], "trending": [], "popular": []}
    platform["posts"] = {"i0": post("i0"), "i2": post("i2")}
    with caplog.at_level(logging.INFO, logger="reco.retrieval"):
        pool = await build_pool(settings, SourceResult(items=lists), viewer=None, request_id="r2")
    assert [i.item_id for i in pool.items] == ["i0", "i2"]
    assert any(getattr(r, "rule", None) == "missing" and r.item_id == "i1" for r in caplog.records)


# --- ENG-30 point 3: the repost chain -----------------------------------------------------------


def chain(*links: tuple[str, str | None]) -> dict[str, PostRecord]:
    """(post, the post it reshares or None for an original)."""
    return {p: post(p, is_repost=parent is not None, repost_of=parent) for p, parent in links}


def test_a_chain_leads_to_the_original() -> None:
    known = chain(("c", "b"), ("b", "a"), ("a", None))
    assert original_of("c", known, 10) == ("a", None)
    assert original_of("a", known, 10) == ("a", None)


def test_a_broken_chain_has_no_original() -> None:
    assert original_of("b", {**chain(("b", "a")), "a": None}, 10) == (None, reposts.MISSING_POST)
    assert original_of("b", {"b": post("b", is_repost=True, repost_of=None)}, 10) == (None, reposts.MISSING_LINK)
    assert original_of("b", chain(("b", "a"), ("a", "b")), 10) == (None, reposts.LOOP)


def test_a_chain_longer_than_the_limit_stops() -> None:
    links = [(f"p{k}", f"p{k - 1}") for k in range(1, 13)] + [("p0", None)]
    known = chain(*links)
    assert original_of("p10", known, 10) == ("p0", None)
    assert original_of("p11", known, 10) == (None, reposts.TOO_LONG)


def test_the_limit_is_the_setting(settings) -> None:
    from reco.config import live

    assert live.current().commerce.repost_chain_max_steps == 10


async def test_resolve_reads_parents_level_by_level_and_logs_breaks(monkeypatch, settings, caplog) -> None:
    platform = chain(("b", "a"), ("a", None), ("x", "gone"))
    reads = []

    async def read_where(settings, kind, field, ids):
        reads.append(sorted(ids))
        return [platform[i] for i in ids if i in platform]

    monkeypatch.setattr(reposts.fetch, "read_where", read_where)
    given = [post("c", is_repost=True, repost_of="b"), post("y", is_repost=True, repost_of="x"), post("z")]
    with caplog.at_level(logging.WARNING, logger="reco.reposts"):
        originals, report, _ = await resolve_originals(settings, given)
    assert originals == {"c": "a", "y": None, "z": "z"}
    assert report == {"resolved": 1, "missing_post": 1}
    assert reads == [["b", "x"], ["a", "gone"]]  # one read per level
    assert any(getattr(r, "post_id", None) == "y" and r.reason == "missing_post" for r in caplog.records)


def test_a_post_reads_its_repost_link() -> None:
    from bson import ObjectId

    from reco.config import Settings
    from reco.platform.readers import vocabulary
    from reco.platform.records import parse_post

    original = ObjectId()
    doc = {"_id": ObjectId(), "userId": ObjectId(), "timestamp": NOW, "isRepost": True,
           "repostDetails": {"originalPostId": original}}
    record = parse_post(doc, vocabulary(Settings()))
    assert record.is_repost and record.repost_of == str(original)
    assert parse_post({**doc, "isRepost": False, "repostDetails": None}, vocabulary(Settings())).repost_of is None


# --- on a database: the Build List's check end to end -------------------------------------------


@pytest.mark.mongo
async def test_the_pool_on_a_database(store) -> None:
    """Index -> sources -> pool for a real viewer: 300 or fewer, quotas within 1, no
    duplicates; a blocked author filtered before, a hidden original filtered after."""
    from bson import ObjectId
    from pymongo import AsyncMongoClient

    from reco.eligibility.apply import viewer_context
    from reco.fallback.profile import CategoryShare, Profile, Rung, RUNG_DESCRIPTION
    from reco.ranking import post_index
    from reco.ranking.quotas import pool_for_user
    from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri

    settings = store
    now = datetime.now(timezone.utc)
    client = AsyncMongoClient(_test_uri())
    platform, engine = client[TEST_PLATFORM_DB], client[TEST_DB]
    names = ("posts", "users", "businessregisters", "follows", "followers")
    for name in names:
        await platform[name].delete_many({})
    for name in ("ml_item_state", "ml_events", "ml_job_runs"):
        await engine[name].delete_many({})
    viewer, friend, stranger, blocked = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    await platform["users"].insert_many([{"_id": u, "status": "Active", "accountIsPublic": True}
                                         for u in (viewer, friend, stranger, blocked)])
    await platform["follows"].insert_one({"_id": ObjectId(), "userId": str(viewer), "followingId": str(friend),
                                          "followingReference": "user"})
    await platform["followers"].insert_one({"_id": ObjectId(), "follower_id": viewer, "user_id": str(blocked),
                                            "status": "blocked", "isBlocked": True})

    def doc(author, cat, hours, **extra):
        return {"_id": ObjectId(), "userId": author, "timestamp": now - timedelta(hours=hours), "categories": [cat],
                "visibility": "public", **extra}

    posts = [doc(stranger, "Pets", k + 1) for k in range(60)] + [doc(friend, "Electronics", k + 1) for k in range(20)]
    posts += [doc(blocked, "Pets", 0.5) for _ in range(5)]
    hidden = doc(stranger, "Pets", 24 * 40, isHidden=True)
    posts += [hidden, doc(friend, "Pets", 0.2, isRepost=True, repostDetails={"originalPostId": hidden["_id"]})]
    await platform["posts"].insert_many(posts)
    await engine["ml_events"].insert_many([
        {"_id": ObjectId(), "kind": "postevent", "event_type": "view", "user_id": f"v{k}", "post_id": str(p["_id"]),
         "dwell_ms": 4000, "created_at": now - timedelta(hours=2), "undone_at": None}
        for k, p in enumerate(posts[:30])])
    profile = Profile(user_id=str(viewer), categories=[CategoryShare(category="Pets", share=1.0)], rung=Rung.PERSONALISED,
                      rung_description=RUNG_DESCRIPTION[Rung.PERSONALISED], personalised=True,
                      model_version=settings.model_version)
    try:
        await post_index.refresh(settings)
        who = await viewer_context(settings, str(viewer))
        # over the internet a source can take more than 20 ms; the limit is tested in test_sources
        found, pool = await pool_for_user(settings, str(viewer), profile, who, "req", time_limit_ms=5000)
        assert not found.dropped
        ids = [i.item_id for i in pool.items]
        assert len(ids) <= 300 and len(ids) == len(set(ids))
        assert all(abs(pool.taken[s] - pool.quotas[s]) <= 1 for s in QUOTA_SOURCES)
        blocked_posts = {str(p["_id"]) for p in posts if p["userId"] == blocked}
        assert not blocked_posts & set(ids) and pool.excluded_before >= 5  # filtered before
        assert str(hidden["_id"]) not in ids and pool.excluded_after == 1  # the repost's original, filtered after
        assert all(i.source in QUOTA_SOURCES for i in pool.items)
    finally:
        for name in names:
            await platform[name].delete_many({})
        for name in ("ml_item_state", "ml_events", "ml_job_runs"):
            await engine[name].delete_many({})
        await client.close()
