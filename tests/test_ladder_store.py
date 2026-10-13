"""ENG-09 against MongoDB: the counts and batches the ladder reads.

    the 5 qualified actions        test_qualified_actions_count_what_the_pack_counts
    rung 3 popularity, nightly     test_popularity_is_a_nightly_batch_without_test_accounts
    the declared and old scores    test_the_platform_reads_for_the_ladder
    all five rungs on real reads   test_one_user_per_rung_on_the_databases

Throwaway databases only (tests/conftest.py): the engine's TEST_DB and a
separate platform TEST_PLATFORM_DB.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient

from reco.fallback.profile import Rung
from reco.fallback.read_path import get_profile
from reco.platform import fetch
from reco.store import writers
from reco.store.scores import Method, utc_now
from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri, make_user_map, put_in_force

pytestmark = pytest.mark.mongo

NOW = utc_now()


def event(user: str, event_type: str, days_ago: float = 1, **fields) -> dict:
    return {"_id": ObjectId(), "kind": "postevent", "user_id": user, "event_type": event_type,
            "created_at": NOW - timedelta(days=days_ago), "undone_at": None, "undo_of": None,
            "post_id": fields.pop("post_id", "p1"), "dwell_ms": fields.pop("dwell_ms", None), **fields}


def order(buyer: str, days_ago: float = 1, **fields) -> dict:
    return {"_id": ObjectId(), "buyer_id": buyer, "created_at": NOW - timedelta(days=days_ago),
            "is_returned": False, "cancelled_at": None, **fields}


@pytest.fixture
async def dbs(store):
    """The engine and platform test databases, emptied before and after."""
    client = AsyncMongoClient(_test_uri())
    engine, platform = client[TEST_DB], client[TEST_PLATFORM_DB]
    names = ("ml_events", "ml_orders", "ml_measurements", "ml_job_runs")
    for name in names:
        await engine[name].delete_many({})
    for name in ("users", "posts", "follows"):
        await platform[name].delete_many({})
    try:
        yield store, engine, platform
    finally:
        for name in names:
            await engine[name].delete_many({})
        for name in ("users", "posts", "follows"):
            await platform[name].delete_many({})
        await client.close()


async def test_qualified_actions_count_what_the_pack_counts(dbs) -> None:
    settings, engine, _ = dbs
    since = NOW - timedelta(days=90)
    await engine["ml_events"].insert_many([
        event("u", "view", dwell_ms=3000, post_id="p1"),  # 1: a qualified view
        event("u", "view", dwell_ms=9000, post_id="p1"),  # same post: still 1
        event("u", "view", dwell_ms=2999, post_id="p2"),  # under 3 s: not qualified
        event("u", "like"),  # 2
        event("u", "like", undone_at=NOW),  # undone later: no
        event("u", "unlike", undo_of="x"),  # an undo row: no
        event("u", "feedback"),  # lowers a score; not an action that builds one
        event("u", "impression"),  # M1 doesn't use impressions
        event("u", "click", days_ago=91),  # outside 90 days
        event("someone else", "click"),
    ])
    await engine["ml_orders"].insert_many([
        order("u"),  # 3
        order("u", cancelled_at=NOW),  # cancelled: nets to zero
        order("u", is_returned=True),  # returned: nets to zero
    ])
    assert await writers.count_qualified_actions(settings, "u", since, 3000, 5) == 3

    await engine["ml_events"].insert_many([event("u", c) for c in ("save", "share", "comment", "add_to_cart")])
    assert await writers.count_qualified_actions(settings, "u", since, 3000, 5) == 5  # stops at 5


async def test_popularity_is_a_nightly_batch_without_test_accounts(dbs) -> None:
    from reco.jobs.__main__ import JOBS
    from reco.jobs.scheduler import NIGHTLY

    settings, engine, platform = dbs
    pets, books, both = ObjectId(), ObjectId(), ObjectId()
    await platform["posts"].insert_many([
        {"_id": pets, "userId": ObjectId(), "timestamp": NOW, "categories": ["Pets"]},
        {"_id": books, "userId": ObjectId(), "timestamp": NOW, "categories": ["books & education"]},
        {"_id": both, "userId": ObjectId(), "timestamp": NOW, "categories": ["Pets", "Not one of the 23"]},
    ])
    tester = str(ObjectId())
    put_in_force({"lists.test_accounts": [{"account_id": tester, "reason": "checks", "changed_by": "Allen",
                                           "expiry": date.today() + timedelta(days=7)}]})
    await engine["ml_events"].insert_many([
        event("a", "view", dwell_ms=4000, post_id=str(pets)),
        event("a", "view", dwell_ms=4000, post_id=str(pets)),  # once per viewer per post
        event("b", "view", dwell_ms=4000, post_id=str(pets)),
        event("a", "view", dwell_ms=4000, post_id=str(both)),
        event("c", "view", dwell_ms=4000, post_id=str(books)),
        event(tester, "view", dwell_ms=4000, post_id=str(books)),  # a test account: left out
        event("d", "view", dwell_ms=1000, post_id=str(books)),  # not qualified
        event("e", "view", dwell_ms=4000, post_id=str(books), days_ago=31),  # outside 30 days
    ])
    assert "popularity" in NIGHTLY

    await JOBS["popularity"](settings)

    rows = await writers.read_popularity(settings)
    assert [(r["category"], r["qualified_views"]) for r in rows] == [("Pets", 3), ("Books & Education", 1)]
    run = await engine["ml_job_runs"].find_one({"job": "popularity"})
    assert run["outcome"] == "succeeded" and run["is_current"] and run["rows_written"] == 2

    # A new run replaces the batch whole; a request reads only the current one.
    await engine["ml_events"].insert_one(event("f", "view", dwell_ms=4000, post_id=str(books)))
    await JOBS["popularity"](settings)
    assert [(r["category"], r["qualified_views"]) for r in await writers.read_popularity(settings)] == [
        ("Pets", 3), ("Books & Education", 2)]


async def test_the_platform_reads_for_the_ladder(dbs) -> None:
    settings, _, platform = dbs
    user = ObjectId()
    await platform["users"].insert_one({"_id": user, "status": "Active", "interest": ["Pets", "Fashion"],
                                        "interestScores": {"Pets": 20}})
    await platform["follows"].insert_many([
        {"userId": str(user), "followingId": str(ObjectId()), "followingReference": "businessRegister", "createdAt": NOW},
        {"userId": str(user), "followingId": str(ObjectId()), "followingReference": "businessRegister",
         "createdAt": NOW - timedelta(days=100)},  # outside 90 days
        {"userId": str(user), "followingId": str(ObjectId()), "followingReference": "user", "createdAt": NOW},
    ])
    record, extra = await fetch.read_user_with(settings, str(user), ("interestScores",))
    assert record.declared_interests == ["Pets"]  # "Fashion" isn't one of the 23
    assert extra == {"interestScores": {"Pets": 20}}
    assert await fetch.read_user_with(settings, str(ObjectId()), ("interestScores",)) == (None, {})
    assert await fetch.read_business_follows(settings, str(user), NOW - timedelta(days=90)) == 1


async def test_one_user_per_rung_on_the_databases(dbs) -> None:
    """The Build List's check, on real reads: test users for each rung get the right rung."""
    settings, engine, platform = dbs
    u1, u2, u3, u4 = (ObjectId() for _ in range(4))
    await platform["users"].insert_many([
        {"_id": u1, "status": "Active", "interest": []},
        {"_id": u2, "status": "Active", "interest": ["Pets"]},
        {"_id": u3, "status": "Active", "interest": []},
        {"_id": u4, "status": "Active", "interest": [], "interestScores": {"Pets": 5}},
    ])
    await engine["ml_events"].insert_many(
        [event(str(u1), "click") for _ in range(5)] + [event(str(u4), "click") for _ in range(5)]
    )
    await writers.upsert_user_scores(settings, str(u1), make_user_map(str(u1), {"Pets": 1.0}))
    await writers.upsert_user_scores(
        settings, str(u4), make_user_map(str(u4), {"Pets": 1.0}, computed_at=NOW - timedelta(hours=72))
    )

    rungs = {u: await get_profile(settings, str(u), Method.RECENCY_DECAY) for u in (u1, u2, u3, u4)}

    assert rungs[u1].rung is Rung.PERSONALISED and rungs[u1].fallback_step is None
    assert rungs[u2].fallback_step == "rung_2"
    assert rungs[u3].fallback_step == "rung_3_empty"  # no popularity batch yet
    assert rungs[u4].fallback_step == "rung_4" and rungs[u4].categories[0].category == "Pets"
