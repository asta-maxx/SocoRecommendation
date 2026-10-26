"""ENG-10: M1's inputs from the engine's copies (reco.slots.interest.copies).

The copies and the platform are stubbed, so each source rule is tested on its own.
The whole path on real databases is ENG-11's check script (scripts/check_m1.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from reco.config import Settings
from reco.slots.interest import copies
from reco.slots.interest.events import EventType

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
DAY = timedelta(days=1)


@pytest.fixture
def settings() -> Settings:
    return Settings(model_version="test")


@pytest.fixture
def world(monkeypatch):
    from reco.platform import fetch
    from reco.store import writers

    state = {"events": [], "orders": [], "follows": [], "users": ["u1", "u2"], "open_requests": set(), "seed": set(),
             "current": (True, "current"),
             "posts": {"home": ["Home & Living"], "pets": ["Pets"], "cricket": []},
             "products": {"gadget": "Electronics"}, "businesses": {"shop": "Pets", "odd": None}}

    async def records(settings, kind, query=None, limit=None):
        if kind == "user":
            return [SimpleNamespace(user_id=u, declared_interests=["Pets"] if u == "u2" else []) for u in state["users"]]
        return [SimpleNamespace(**f) for f in state["follows"]]

    async def posts(settings, ids):
        return {i: SimpleNamespace(post_id=i, categories=state["posts"].get(i, []), is_seed=i in state["seed"]) for i in ids}

    async def open_requests(settings):
        return set(state["open_requests"])

    async def current(settings, now, hours):
        return state["current"]

    async def product_categories(settings, ids):
        return {i: state["products"].get(i) for i in ids}

    async def business_categories(settings, ids):
        return {i: state["businesses"].get(i) for i in ids}

    async def event_copies(settings):
        return state["events"]

    async def order_copies(settings):
        return state["orders"]

    monkeypatch.setattr(fetch, "read_records", records)
    monkeypatch.setattr(fetch, "read_posts", posts)
    monkeypatch.setattr(writers, "read_open_return_orders", open_requests)
    monkeypatch.setattr(writers, "return_requests_current", current)
    monkeypatch.setattr(fetch, "read_product_categories", product_categories)
    monkeypatch.setattr(fetch, "read_business_categories", business_categories)
    monkeypatch.setattr(writers, "read_m1_event_copies", event_copies)
    monkeypatch.setattr(writers, "read_order_copies", order_copies)
    return state


def ev(kind: str, user: str = "u1", post: str | None = "home", days: float = 1, **fields) -> dict:
    return {"_id": f"{kind}-{len(fields)}-{days}-{post}", "user_id": user, "actor": "user", "event_type": kind,
            "post_id": post, "created_at": NOW - days * DAY, **fields}


def order(status: str = "Delivered", **fields) -> dict:
    return {"_id": "o1", "order_id": "o1", "buyer_id": "u1", "buyer_actor": "user", "product_id": "gadget",
            "status": status, "cancelled_at": None, "is_returned": False, "created_at": NOW - 2 * DAY, **fields}


async def inputs(settings):
    return await copies.read_inputs(settings, NOW)


def kinds(result, user: str = "u1") -> list[tuple[str, list[str]]]:
    return [(e.event_type.value, e.categories) for e in result.events_by_user.get(user, [])]


async def test_every_weighted_action_is_read_with_its_post_category(world, settings) -> None:
    world["events"] = [ev(k) for k in ("click", "product_click", "like", "save", "comment", "share", "add_to_cart")]
    got = kinds(await inputs(settings))
    assert sorted(k for k, _ in got) == ["cart", "click", "click", "comment", "like", "save", "share"]
    assert all(c == ["Home & Living"] for _, c in got)


async def test_a_row_with_no_user_model_counts_for_a_known_user(world, settings) -> None:
    """Older platform rows carry no user_model (actor "unknown"): the id decides."""
    world["events"] = [ev("like", actor="unknown"), ev("like", user="shop", actor="unknown"), ev("like", actor="business")]
    result = await inputs(settings)
    assert len(kinds(result)) == 1 and result.skipped["not_a_user"] == 2


async def test_undone_actions_and_undo_rows_count_nothing(world, settings) -> None:
    world["events"] = [ev("like", undone_at=NOW), ev("unlike", undo_of="x"), ev("save")]
    result = await inputs(settings)
    assert kinds(result) == [("save", ["Home & Living"])] and result.skipped["undone"] == 2


async def test_one_view_per_post_the_latest_qualified_one(world, settings) -> None:
    world["events"] = [ev("view", days=3, dwell_ms=4000), ev("view", days=1, dwell_ms=1000), ev("view", days=2, dwell_ms=5000),
                       ev("view", post="pets", days=1, dwell_ms=2000)]
    views = (await inputs(settings)).events_by_user["u1"]
    by_post = {tuple(v.categories): v for v in views}
    assert len(views) == 2
    assert by_post[("Home & Living",)].view_duration_seconds == 5.0  # qualified beats a newer unqualified one
    assert by_post[("Pets",)].view_duration_seconds == 2.0  # kept, for the method to count as below 3 s


async def test_feedback_not_interested_and_hide_only_and_never_on_an_author(world, settings) -> None:
    world["events"] = [ev("feedback", feedback_type="Hide"), ev("feedback", feedback_type="not_interested", days=2),
                       ev("feedback", feedback_type="mute_author", days=3), ev("feedback", feedback_type="report", days=4),
                       ev("feedback", post=None, feedback_type="hide", target_type="author", target_id="a", days=5),
                       ev("feedback", post=None, feedback_type="hide", target_type="post", target_id="pets", days=6)]
    result = await inputs(settings)
    assert kinds(result) == [("feedback", ["Home & Living"]), ("feedback", ["Home & Living"]), ("feedback", ["Pets"])]
    assert result.skipped["feedback_not_weighted"] == 2 and result.skipped["feedback_on_an_author"] == 1


async def test_a_product_action_takes_the_products_category(world, settings) -> None:
    world["events"] = [ev("add_to_cart", post=None, product_id="gadget")]
    assert kinds(await inputs(settings)) == [("cart", ["Electronics"])]


async def test_unmatched_categories_are_dropped_and_counted(world, settings) -> None:
    world["events"] = [ev("like", post="cricket"), ev("like", post=None)]
    result = await inputs(settings)
    assert kinds(result) == [] and result.read_stats.unresolved_category == 2


@pytest.mark.parametrize("change", [{"status": "Cancelled"}, {"status": "rejected"}, {"status": "Returned"}],
                         ids=["cancelled", "rejected", "returned"])
async def test_a_reversed_order_counts_nothing(world, settings, change) -> None:
    world["orders"] = [order(**change)]
    result = await inputs(settings)
    assert kinds(result) == [] and result.skipped["order_reversed"] == 1


async def test_only_the_order_state_reverses_a_purchase(world, settings) -> None:
    """v1.4 (ENG-30 points 5, 6): a history event never decides it. A 'Return requested'
    event or an old Return Requested flag on a Delivered order is not a reversal."""
    world["orders"] = [order("Delivered", is_returned=True, cancelled_at=NOW)]
    assert [k for k, _ in kinds(await inputs(settings))] == ["purchase"]


async def test_a_kept_order_is_a_purchase_at_its_creation_including_incognito(world, settings) -> None:
    world["orders"] = [order("Delivered", is_incognito=True)]
    (purchase,) = (await inputs(settings)).events_by_user["u1"]
    assert purchase.event_type is EventType.PURCHASE and purchase.categories == ["Electronics"]
    assert purchase.timestamp == NOW - 2 * DAY and purchase.order_id == "o1"


async def test_business_follows_on_the_businesss_category_or_nothing(world, settings) -> None:
    world["follows"] = [{"follower_id": "u1", "followed_id": "shop", "followed_kind": "business", "created_at": NOW - DAY},
                        {"follower_id": "u1", "followed_id": "odd", "followed_kind": "business", "created_at": NOW - DAY},
                        {"follower_id": "u1", "followed_id": "u2", "followed_kind": "user", "created_at": NOW - DAY}]
    result = await inputs(settings)
    assert kinds(result) == [("business_follow", ["Pets"])] and result.skipped["business_follow_no_category"] == 1


async def test_future_and_timeless_actions_are_dropped(world, settings) -> None:
    world["events"] = [ev("like", days=-1), {**ev("save"), "created_at": None}]
    stats = (await inputs(settings)).read_stats
    assert (stats.future_timestamp, stats.missing_timestamp) == (1, 1)


async def test_declared_interests_and_every_user_are_returned(world, settings) -> None:
    result = await inputs(settings)
    assert result.user_ids == ["u1", "u2"] and result.declared == {"u2": ["Pets"]}


# --- pack v1.4 (ENG-30 points 9, 10) and Kala's count (16 Oct) ---------------------------------


async def test_an_open_return_request_leaves_the_purchase_out_until_it_ends(world, settings) -> None:
    """ENG-30 point 10: out while the request is open; back when it ends without a return."""
    world["orders"] = [order("Delivered")]
    world["open_requests"] = {"o1"}
    result = await inputs(settings)
    assert kinds(result) == [] and result.skipped["order_open_return_request"] == 1
    world["open_requests"] = set()  # the request ended (isActive false), the order not Returned
    assert kinds(await inputs(settings)) == [("purchase", ["Electronics"])]


async def test_a_stale_return_request_copy_is_used_and_said(world, settings) -> None:
    world["current"] = (False, "the last reconciliation of returnrequests (2026-10-15) did not pass")
    world["orders"] = [order("Delivered")]
    world["open_requests"] = {"o1"}
    result = await inputs(settings)
    assert kinds(result) == [] and "did not pass" in result.return_requests  # the last good copy, logged


async def test_actions_on_seed_posts_are_left_out(world, settings) -> None:
    """ENG-30 point 9: a _seedTag post is test data."""
    world["seed"] = {"home"}
    world["events"] = [ev("like"), ev("like", post="pets", days=2)]
    world["orders"] = [order("Delivered", post_id="home", product_id=None)]
    result = await inputs(settings)
    assert kinds(result) == [("like", ["Pets"])] and result.skipped["seed_post"] == 2


async def test_qualified_actions_are_counted_kalas_way(world, settings) -> None:
    """Kala, 16 Oct (2a): views of 3 s+ (one per post), clicks, likes, saves, comments,
    shares, add-to-carts, kept orders and business follows, in the last 90 days; not
    feedback, impressions, undone actions, own-post actions or older ones. The total
    counts whatever the category; event_count is the same set per category."""
    world["events"] = [
        ev("view", dwell_ms=3000), ev("view", dwell_ms=5000, days=2),  # one view per post: 1
        ev("view", post="pets", dwell_ms=2999),  # under 3 s: no
        ev("click"), ev("product_click", days=3), ev("save"), ev("comment"), ev("share"), ev("add_to_cart"),  # 6
        ev("like", is_self=True),  # own post: neither scored nor counted (Kala, 16 Oct)
        ev("like", undone_at=NOW),  # undone: no
        ev("feedback", feedback_type="hide"),  # feedback: no
        ev("like", days=91),  # outside 90 days: no
        ev("like", post="cricket"),  # no category: still counted
    ]
    world["orders"] = [order("Delivered"), {**order("Cancelled"), "_id": "o2", "order_id": "o2"}]  # 1 kept
    world["follows"] = [{"follower_id": "u1", "followed_id": "shop", "followed_kind": "business", "created_at": NOW - DAY},
                        {"follower_id": "u1", "followed_id": "odd", "followed_kind": "business", "created_at": NOW - DAY}]
    result = await inputs(settings)
    assert result.qualified["u1"] == 1 + 6 + 1 + 1 + 2  # views, actions, uncategorised like, order, follows
    by_category = result.qualified_by_category["u1"]
    assert by_category == {"Home & Living": 7, "Electronics": 1, "Pets": 1}
    assert kinds(result).count(("like", ["Home & Living"])) == 1  # only the 91-day-old like: the own-post one isn't scored
    # Every category-level action belongs to the user's set, and the set's size is the count.
    ids = result.qualified_ids["u1"]
    assert len(ids) == result.qualified["u1"]
    assert all(cat_ids <= ids and len(cat_ids) == by_category[c] for c, cat_ids in result.qualified_ids_by_category["u1"].items())


async def test_only_liking_your_own_post_scores_and_counts_nothing(world, settings) -> None:
    """Kala's regression test (16 Oct): no declared interests, only likes on their own post:
    qualified_actions 0, and no M1 score contribution under either method."""
    world["events"] = [ev("like", is_self=True), ev("like", is_self=True, days=2)]
    result = await inputs(settings)
    assert result.qualified["u1"] == 0 and kinds(result) == [] and result.skipped["own_post"] == 2

