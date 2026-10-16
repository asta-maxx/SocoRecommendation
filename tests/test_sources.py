"""ENG-12: candidate sources (and the post index they read).

The Build List's check: "On test load, each source returns within its limit, and
drops are logged." The rules of each source are tested here without a database;
the post index and the sources on MongoDB below; the timing on test load is
checklist line 12.x on the test server.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient

from reco.ranking import sources
from reco.ranking.sources import run_sources, top_categories
from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri, put_in_force

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
HOME, PETS, ELEC = "Home & Living", "Pets", "Electronics"


def row(post: str, author: str = "a1", cats=(HOME,), hours: float = 1, views: int = 0) -> dict:
    return {"post_id": post, "author_id": author, "categories": list(cats), "created_at": NOW - timedelta(hours=hours),
            "qualified_views_7d": views}


@pytest.fixture
def index(monkeypatch):
    from reco.store import item_state

    state = {"rows": [], "batch": "b1", "slow": set(), "similar": []}

    async def batch(settings):
        return state["batch"]

    async def pause(name):
        if name in state["slow"]:
            await asyncio.sleep(0.2)

    async def by_categories(settings, b, cats, since, limit):
        await pause("interest")
        return [r for r in state["rows"] if set(r["categories"]) & set(cats) and r["created_at"] >= since][:limit]

    async def by_authors(settings, b, authors, since, limit):
        await pause("follows")
        return [r for r in state["rows"] if r["author_id"] in authors and r["created_at"] >= since][:limit]

    async def most_viewed(settings, b, since, limit, categories=None):
        await pause("trending" if categories is not None else "popular")
        rows = [r for r in state["rows"] if r["qualified_views_7d"] > 0 and r["created_at"] >= since
                and (categories is None or set(r["categories"]) & set(categories))]
        return rows[:limit]

    async def similar(settings, user_id):
        await pause("similar")
        return state["similar"]

    monkeypatch.setattr(item_state, "current_batch", batch)
    monkeypatch.setattr(item_state, "read_by_categories", by_categories)
    monkeypatch.setattr(item_state, "read_by_authors", by_authors)
    monkeypatch.setattr(item_state, "read_most_viewed", most_viewed)
    monkeypatch.setattr(sources, "_similar_reader", similar)
    return state


async def run(settings, top=((HOME, 0.6), (PETS, 0.4)), follows=frozenset({"a2"}), **kw):
    return await run_sources(settings, "u1", list(top), follows, "req1", NOW, **kw)


def test_top_five_categories_by_share() -> None:
    shares = {"A": 0.1, "B": 0.3, "C": 0.05, "D": 0.2, "E": 0.15, "F": 0.2, "G": 0.0}
    assert [c for c, _ in top_categories(shares)] == ["B", "D", "F", "E", "A"]


async def test_interest_scores_by_the_best_category_share(index, settings) -> None:
    index["rows"] = [row("p1", cats=(PETS,)), row("p2", cats=(HOME, PETS)), row("p3", cats=(ELEC,)),
                     row("p4", cats=(HOME,), hours=5)]
    items = (await run(settings)).items["interest"]
    assert [(i.item_id, i.source_score) for i in items] == [("p2", 0.6), ("p4", 0.6), ("p1", 0.4)]  # ties: newer first
    assert all(i.item_type == "post" and i.source == "interest" for i in items)


async def test_follows_are_the_followed_authors_posts_newest_first(index, settings) -> None:
    index["rows"] = [row("p1", author="a2", hours=3), row("p2", author="a3"), row("p3", author="a2", hours=1)]
    assert [i.item_id for i in (await run(settings)).items["follows"]] == ["p3", "p1"]
    assert (await run(settings, follows=frozenset())).items["follows"] == []


async def test_trending_is_popular_limited_to_the_top_categories(index, settings) -> None:
    """Kala, 16 Oct: a plain count of qualified views over 7 days; ties newest first."""
    index["rows"] = [row("p1", cats=(ELEC,), views=50), row("p2", cats=(HOME,), views=5, hours=2),
                     row("p3", cats=(PETS,), views=5, hours=1), row("p4", cats=(HOME,), views=0)]
    result = await run(settings)
    assert [(i.item_id, i.source_score) for i in result.items["trending"]] == [("p3", 5.0), ("p2", 5.0)]
    assert [i.item_id for i in result.items["popular"]] == ["p1", "p3", "p2"]


async def test_only_posts_from_the_last_30_days(index, settings) -> None:
    index["rows"] = [row("old", hours=24 * 31, views=9), row("new", views=1)]
    result = await run(settings)
    assert [i.item_id for i in result.items["popular"]] == ["new"] and [i.item_id for i in result.items["interest"]] == ["new"]


async def test_a_source_over_its_limit_is_dropped_and_logged(index, settings, caplog) -> None:
    index["rows"] = [row("p1", views=3)]
    index["slow"] = {"trending"}
    with caplog.at_level(logging.WARNING, logger="reco.retrieval"):
        result = await run(settings, time_limit_ms=50)
    assert result.dropped == ["trending"] and result.items["trending"] == []
    assert [i.item_id for i in result.items["popular"]] == ["p1"]  # the others still answer
    assert any(getattr(r, "source", None) == "trending" and r.request_id == "req1" for r in caplog.records)


async def test_the_limit_is_the_setting(index, settings) -> None:
    index["slow"] = {"follows"}
    put_in_force({"retrieval": {"source_time_limit_ms": 40}})
    assert (await run(settings)).dropped == ["follows"]


async def test_the_similar_list_is_read_in_parallel(index, settings) -> None:
    index["similar"] = [{"post_id": "s1", "score": 0.9, "rank": 1}, {"post_id": "s2", "score": 0.7, "rank": 2}]
    items = (await run(settings)).items["similar"]
    assert [(i.item_id, i.source, i.source_score) for i in items] == [("s1", "similar", 0.9), ("s2", "similar", 0.7)]


async def test_no_index_yet_means_empty_sources(index, settings) -> None:
    index["batch"] = None
    index["rows"] = [row("p1", views=3)]
    result = await run(settings)
    assert all(result.items[s] == [] for s in ("interest", "follows", "trending", "popular"))


# --- on a database --------------------------------------------------------------------------


@pytest.mark.mongo
async def test_the_post_index_and_the_sources_on_a_database(store) -> None:
    """The index: recent posts only, seed posts left out, 7-day qualified views without
    test accounts; the sources read it."""
    from reco.ranking import post_index
    from reco.store import item_state

    settings = store
    now = datetime.now(timezone.utc)
    client = AsyncMongoClient(_test_uri())
    platform, engine = client[TEST_PLATFORM_DB], client[TEST_DB]
    for name in ("ml_item_state", "ml_events", "ml_job_runs"):
        await engine[name].delete_many({})
    await platform["posts"].delete_many({})
    author, other = ObjectId(), ObjectId()
    fresh, pets, old, seed, repost = ObjectId(), ObjectId(), ObjectId(), ObjectId(), ObjectId()
    await platform["posts"].insert_many([
        {"_id": fresh, "userId": author, "timestamp": now - timedelta(days=1), "categories": [HOME]},
        {"_id": pets, "userId": other, "timestamp": now - timedelta(days=2), "categories": [PETS]},
        {"_id": old, "userId": author, "timestamp": now - timedelta(days=40), "categories": [HOME]},
        {"_id": seed, "userId": author, "timestamp": now - timedelta(days=1), "categories": [HOME], "_seedTag": "s"},
        # ENG-30 point 3: a recent repost of a post older than the window leads to it
        {"_id": repost, "userId": other, "timestamp": now - timedelta(days=3), "categories": [HOME],
         "isRepost": True, "repostDetails": {"originalPostId": old}},
    ])
    tester = str(ObjectId())
    put_in_force({"lists.test_accounts": [{"account_id": tester, "reason": "t", "changed_by": "Allen",
                                           "expiry": date.today() + timedelta(days=7)}]})
    views = [("v1", fresh), ("v2", fresh), (tester, fresh), ("v1", pets)]
    await engine["ml_events"].insert_many([
        {"_id": ObjectId(), "kind": "postevent", "event_type": "view", "user_id": u, "post_id": str(p), "dwell_ms": 4000,
         "created_at": now - timedelta(hours=3), "undone_at": None} for u, p in views])
    try:
        result = await post_index.refresh(settings)
        assert result["posts"] == 3 and result["seed_posts_left_out"] == 1 and result["reposts"] == {"resolved": 1}
        rows = {r["post_id"]: r for r in await engine["ml_item_state"].find({"kind": "post"}).to_list(None)}
        assert set(rows) == {str(fresh), str(pets), str(repost)}
        assert rows[str(repost)]["original_id"] == str(old) and rows[str(fresh)]["original_id"] == str(fresh)
        assert rows[str(fresh)]["qualified_views_7d"] == 2  # the test account's view left out

        found = await run_sources(settings, "u1", [(HOME, 0.7)], frozenset({str(other)}), "req", now, time_limit_ms=5000)
        assert [i.item_id for i in found.items["interest"]] == [str(fresh), str(repost)]
        assert [i.key for i in found.items["interest"]] == [str(fresh), str(old)]  # a repost counts as its original
        assert [i.item_id for i in found.items["follows"]] == [str(pets), str(repost)]
        assert [i.item_id for i in found.items["trending"]] == [str(fresh)]
        assert [i.item_id for i in found.items["popular"]] == [str(fresh), str(pets)]
        assert not found.dropped and set(found.ms) == set(sources.SOURCES)
    finally:
        await platform["posts"].delete_many({})
        for name in ("ml_item_state", "ml_events", "ml_job_runs"):
            await engine[name].delete_many({})
        await client.close()
