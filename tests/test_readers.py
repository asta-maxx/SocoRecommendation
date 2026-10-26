"""The two adapters against a live MongoDB.

The claim under test: a demo row and a postevent row are structurally different
documents, and both arrive at the methods as the same `Event`. If this passes,
the methods never need to know which source they are reading -- which is what
makes one engine serve both the demonstration and production.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio

from reco.config import Settings
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.platform.readers import (
    read_declared_interests,
    read_order_creation_times,
    read_user_events,
)
from reco.slots.interest.events import EventType
from reco.store.scores import utc_now
from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri

pytestmark = pytest.mark.mongo

EVENTS = "ml_test_events"
POSTS = "ml_test_posts"
USERS = "ml_test_users"
ORDERS = "ml_test_orders"


def _settings(shape: str) -> Settings:
    return Settings(
        app_mongo_uri=_test_uri(),
        app_mongo_db=TEST_PLATFORM_DB,
        ml_mongo_uri=_test_uri(),
        ml_mongo_db=TEST_DB,
        model_version="test-1.0.0",
        data_profile="demo",
        event_shape=shape,
        events_collection=EVENTS,
        posts_collection=POSTS,
        users_collection=USERS,
        orders_collection=ORDERS,
    )


@pytest_asyncio.fixture
async def sources():
    """Both source shapes, seeded side by side in the ml_ namespace."""
    settings = _settings("flat")
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable (db={settings.ml_mongo_db}): {type(exc).__name__}")

    db = store_conn.ml_db(settings)
    for name in (EVENTS, POSTS, USERS, ORDERS):
        await db[name].drop()
    try:
        yield db
    finally:
        for name in (EVENTS, POSTS, USERS, ORDERS):
            await db[name].drop()
        await platform_conn.close_client()
        await store_conn.close_client()


async def test_both_shapes_produce_the_same_event(sources) -> None:
    """The point of the adapters.

    A demo row carries `categories` on the event. A postevent carries a
    `post_id` and nothing else -- the category is a join away. Swapping the
    collection name would not have made these compatible.
    """
    when = utc_now() - timedelta(days=3)

    await sources[EVENTS].insert_one(
        {
            "user_id": "u1",
            "event_type": "view",
            "categories": ["Fashion & Apparel"],
            "timestamp": when,
            "view_duration_seconds": 7.5,
            "weight": 2,  # written for the data checks; must be ignored
        }
    )
    await sources[POSTS].insert_one(
        {"_id": "p1", "categories": ["Fashion & Apparel"]}
    )
    await sources[EVENTS].insert_one(
        {
            "user_id": "u2",
            "event_type": "view",
            "post_id": "p1",
            "created_at": when,
            "view_duration_seconds": 7.5,
        }
    )

    flat, _ = await read_user_events(_settings("flat"), "u1")
    joined, _ = await read_user_events(_settings("postevent"), "u2")

    assert len(flat) == 1 and len(joined) == 1
    assert flat[0].categories == joined[0].categories == ["Fashion & Apparel"]
    assert flat[0].event_type is joined[0].event_type is EventType.VIEW
    assert flat[0].view_duration_seconds == joined[0].view_duration_seconds == 7.5
    assert flat[0].timestamp == joined[0].timestamp


async def test_row_weight_never_reaches_the_engine(sources) -> None:
    """If it did, P-06 would stop being configuration and the config layer would
    be decorative -- silently.
    """
    await sources[EVENTS].insert_one(
        {
            "user_id": "u1",
            "event_type": "purchase",
            "categories": ["Electronics"],
            "timestamp": utc_now() - timedelta(days=1),
            "weight": 999,
        }
    )

    events, _ = await read_user_events(_settings("flat"), "u1")

    assert not hasattr(events[0], "weight")
    assert "weight" not in events[0].model_dump()


async def test_unresolvable_post_is_dropped_and_counted(sources) -> None:
    """A postevent whose post has no categories resolves to nothing.

    Dropped, and counted toward the unresolved-category rate -- which is a
    separate number from anything else that was dropped.
    """
    await sources[POSTS].insert_one({"_id": "p2", "categories": []})
    await sources[EVENTS].insert_many(
        [
            {
                "user_id": "u3",
                "event_type": "click",
                "post_id": "p2",
                "created_at": utc_now() - timedelta(days=1),
            },
            {
                "user_id": "u3",
                "event_type": "click",
                "post_id": "missing-post",
                "created_at": utc_now() - timedelta(days=1),
            },
        ]
    )

    events, stats = await read_user_events(_settings("postevent"), "u3")

    assert events == []
    assert stats.read == 2
    assert stats.unresolved_category == 2
    assert stats.unresolved_category_rate == 1.0


async def test_missing_and_future_timestamps_are_counted_separately(sources) -> None:
    """A missing timestamp is a problem in the event writer; a future one is a
    clock problem. One combined 'dropped' number would hide both.
    """
    await sources[EVENTS].insert_many(
        [
            {"user_id": "u4", "event_type": "view", "categories": ["Books & Education"]},
            {
                "user_id": "u4",
                "event_type": "view",
                "categories": ["Books & Education"],
                "timestamp": utc_now() + timedelta(days=2),
            },
        ]
    )

    events, stats = await read_user_events(_settings("flat"), "u4")

    assert events == []
    assert stats.missing_timestamp == 1
    assert stats.future_timestamp == 1
    assert stats.unresolved_category == 0


async def test_multi_category_post_keeps_every_category(sources) -> None:
    """Full weight to each, so the reader must not collapse them."""
    await sources[POSTS].insert_one(
        {"_id": "p3", "categories": ["Fashion & Apparel", "Home & Living"]}
    )
    await sources[EVENTS].insert_one(
        {
            "user_id": "u5",
            "event_type": "click",
            "post_id": "p3",
            "created_at": utc_now() - timedelta(days=1),
        }
    )

    events, _ = await read_user_events(_settings("postevent"), "u5")

    assert events[0].categories == ["Fashion & Apparel", "Home & Living"]


async def test_sub_threshold_views_are_not_dropped_by_the_reader(sources) -> None:
    """P-02 is a tunable. A reader that filtered on it would be making a scoring
    decision, and changing P-02 would then require a different reader.
    """
    await sources[EVENTS].insert_one(
        {
            "user_id": "u6",
            "event_type": "view",
            "categories": ["Books & Education"],
            "timestamp": utc_now() - timedelta(days=1),
            "view_duration_seconds": 0.5,
        }
    )

    events, stats = await read_user_events(_settings("flat"), "u6")

    assert len(events) == 1
    assert events[0].view_duration_seconds == 0.5
    assert stats.dropped == 0


async def test_declared_interests_come_from_the_user_record(sources) -> None:
    """P-25's source is the `interest` array, not interestScores -- addInterest
    seeds that map with 10 per declared category and event tracking increments
    the same map, so the two are fused there and cannot be decomposed.
    """
    await sources[USERS].insert_one(
        {"_id": "u7", "interest": ["fashion & apparel", "books"]}
    )

    interests = await read_declared_interests(_settings("flat"), "u7")

    assert interests == ["fashion & apparel", "books"]


async def test_declared_interests_for_unknown_user_is_empty(sources) -> None:
    assert await read_declared_interests(_settings("flat"), "nobody") == []


async def test_order_creation_times_are_read_for_reversal_aging(sources) -> None:
    """The reversal is aged from the ORIGINAL order's creation.

    A cancellation is always more recent than the order it cancels, so it decays
    less, so it is always larger -- aged from the cancellation the user ends up
    below someone who never ordered.
    """
    # Truncated to milliseconds: BSON dates carry no microseconds, so a
    # round-tripped timestamp is not equal to the one that went in. Irrelevant
    # to decay at day scale, but it will bite any test that compares exactly.
    created = (utc_now() - timedelta(days=12)).replace(microsecond=421000)
    await sources[ORDERS].insert_one(
        {"_id": "o1", "created_at": created, "order_status": "Cancelled"}
    )

    times = await read_order_creation_times(_settings("flat"), ["o1", "missing"])

    assert list(times) == ["o1"]
    assert times["o1"] == created
    assert times["o1"].tzinfo is not None


async def test_events_come_back_newest_first(sources) -> None:
    now = utc_now()
    await sources[EVENTS].insert_many(
        [
            {
                "user_id": "u8",
                "event_type": "view",
                "categories": ["Books & Education"],
                "timestamp": now - timedelta(days=days),
            }
            for days in (10, 1, 5)
        ]
    )

    events, _ = await read_user_events(_settings("flat"), "u8")

    assert [e.timestamp for e in events] == sorted(
        (e.timestamp for e in events), reverse=True
    )


async def test_contract_row_reads_straight_through(sources) -> None:
    """A row built to EVENT_CONTRACT.md must be readable with no translation.

    This is the join between the two halves: the generator writes DemoEventRow,
    the engine reads Event, and nothing in between renames a field.
    """
    from reco.platform.demo_event_contract import DemoEventRow

    row = DemoEventRow(
        user_id="u10",
        event_type="product_view",
        categories=["Fashion & Apparel"],
        timestamp=utc_now() - timedelta(days=2),
        weight=2,
        view_duration_seconds=7.5,
    )
    await sources[EVENTS].insert_one(row.model_dump())

    events, stats = await read_user_events(_settings("flat"), "u10")

    assert stats.dropped == 0
    assert events[0].categories == ["Fashion & Apparel"]
    assert events[0].view_duration_seconds == 7.5
    assert not events[0].is_reversal


async def test_purchase_reversal_row_is_read_as_a_reversal(sources) -> None:
    """`purchase_reversal` is a row type, not a flag. The reader turns it into a
    purchase marked as reversing, carrying the order_id it must be aged from.
    """
    from reco.platform.demo_event_contract import DemoEventRow

    row = DemoEventRow(
        user_id="u11",
        event_type="purchase_reversal",
        categories=["electronics"],
        timestamp=utc_now() - timedelta(days=5),
        weight=-20,
        order_id="order-42",
    )
    await sources[EVENTS].insert_one(row.model_dump())

    events, _ = await read_user_events(_settings("flat"), "u11")

    assert events[0].event_type is EventType.PURCHASE
    assert events[0].is_reversal
    assert events[0].order_id == "order-42"


async def test_unknown_event_type_is_dropped_not_assumed_a_view(sources) -> None:
    await sources[EVENTS].insert_one(
        {
            "user_id": "u9",
            "event_type": "share",
            "categories": ["Books & Education"],
            "timestamp": utc_now() - timedelta(days=1),
        }
    )

    events, stats = await read_user_events(_settings("flat"), "u9")

    assert events == []
    assert stats.unknown_event_type == 1
