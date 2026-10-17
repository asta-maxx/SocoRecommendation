"""ENG-16: M8 promoter score, both methods; ENG-30 points 1, 2 and 8.

The Build List's check: "Scores exist for every eligible promoter, both methods,
with confidence. A test promoter with a confirmed case scores half. A sale through
a repost counts for the original author; a self-purchase through a store the buyer
owns counts for nobody; an order with an open return request is not a completed
sale, and becomes one once the request ends without a return and the window has
passed; a Returned order counts as fully returned (partial refunds are not
modelled); an account with only reposts is not scored."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from reco.platform.people import People, promoter_of
from reco.slots.promoter import sales
from reco.slots.promoter.score import (
    PromoterInput,
    PromoterSettings,
    follower_band,
    percentile_ranks,
    rescaled,
    score_promoters,
)

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
WEIGHTS = {"reach": 0.20, "content_quality": 0.20, "consistency": 0.10, "net_commerce": 0.25, "conversion": 0.15,
           "sales_quality": 0.10}
SETTINGS = PromoterSettings(WEIGHTS)
RULES = sales.SaleRules()


# --- ENG-30 points 1 and 2 -----------------------------------------------------------------------


@dataclass
class Store:
    business_id: str
    owner_user_id: str | None


def test_a_store_and_its_owner_are_one_person() -> None:
    people = People.of([Store("s1", "u1"), Store("s2", "u1"), Store("s3", None)])
    assert people.person_of("s1") == "u1" and people.person_of("u1") == "u1" and people.person_of("s3") == "s3"
    assert people.same_person("s1", "s2") and people.same_person("u1", "s2")
    assert not people.same_person("u2", "s1") and not people.same_person(None, "s1")


def test_the_promoter_is_promoter_id_else_the_posts_author() -> None:
    authors = {"p1": "author"}
    assert promoter_of({"promoter_id": "pid", "post_id": "p1"}, authors) == "pid"
    assert promoter_of({"promoter_id": None, "post_id": "p1"}, authors) == "author"
    assert promoter_of({"post_id": None}, authors) is None


# --- ENG-30 point 8 and the completed sale -------------------------------------------------------


@dataclass
class Product:
    return_window_days: float | None = None
    return_applicable: bool | None = None


def test_the_return_window() -> None:
    assert sales.return_window_days(Product(10, True), 7) == (10.0, False)
    assert sales.return_window_days(Product(10, False), 7) == (0.0, False)  # not returnable: 0
    assert sales.return_window_days(Product(None, None), 7) == (7.0, True)  # missing: the fallback, logged
    assert sales.return_window_days(None, 7) == (7.0, True)


def order(status="Delivered", delivered_days=None, created_days=30, **fields) -> dict:
    return {"order_id": fields.pop("order_id", "o1"), "status": status, "created_at": NOW - timedelta(days=created_days),
            "delivered_at": NOW - timedelta(days=delivered_days) if delivered_days is not None else None, **fields}


def outcome(o, window=7, open_requests=frozenset()):
    return sales.sale_outcome(o, now=NOW, window_days=window, rules=RULES, open_requests=open_requests)


def test_completed_only_after_the_window_plus_2_days() -> None:
    assert outcome(order(delivered_days=9)) == "completed"  # 7 + 2 passed
    assert outcome(order(delivered_days=8.9)) == "in_return_window"
    assert outcome(order(delivered_days=2), window=0) == "completed"  # not returnable: the buffer only


def test_an_open_return_request_is_not_a_completed_sale_until_it_ends() -> None:
    assert outcome(order(delivered_days=20), open_requests={"o1"}) == "open_return_request"
    assert outcome(order(delivered_days=20)) == "completed"  # the request ended without a return


def test_returned_cancelled_rejected_and_conflicts() -> None:
    assert outcome(order("Returned", delivered_days=20)) == "returned"  # in full: partial refunds not modelled
    assert outcome(order("cancelled")) == "cancelled" and outcome(order("Rejected")) == "rejected"
    assert outcome(order(delivered_days=20, history_conflict=True)) == "history_conflict"
    assert outcome(order(delivered_days=None)) == "history_conflict"  # Delivered with no Delivered event
    assert sales.FINAL == {"completed", "cancelled", "rejected", "returned"}


def test_an_order_still_open_after_14_days_is_not_completed() -> None:
    assert outcome(order("Shipped", created_days=15)) == "not_completed"
    assert outcome(order("Shipped", created_days=3)) == "in_progress"


# --- the scoring -----------------------------------------------------------------------------------


def promoter(pid, cat="Pets", views=100, reach=50, engaged=10, weeks=4, followers=10, **kw) -> PromoterInput:
    return PromoterInput(pid, "user", cat, followers, views, reach, engaged, weeks, kw.pop("views_90", views), **kw)


def test_percentiles_and_a_group_of_one() -> None:
    assert percentile_ranks({"a": 1, "b": 3, "c": 2}) == {"a": 0.0, "c": 0.5, "b": 1.0}
    assert percentile_ranks({"a": 1, "b": 1}) == {"a": 0.5, "b": 0.5}
    assert percentile_ranks({"only": 9}) == {"only": 0.5}


def test_at_launch_the_weights_rescale_to_40_40_20() -> None:
    launch = rescaled(WEIGHTS, ("reach", "content_quality", "consistency"))
    assert launch == pytest.approx({"reach": 0.4, "content_quality": 0.4, "consistency": 0.2})
    scored = score_promoters([promoter("a"), promoter("b", reach=10)], settings=SETTINGS, commerce_on=False)
    assert set(scored["a"].weights) == {"reach", "content_quality", "consistency"}


def test_method_one_pulls_toward_the_category_average_with_confidence() -> None:
    ps = [promoter("a", views=500, reach=300), promoter("b", views=100, reach=20), promoter("c", views=300, reach=100)]
    scored = score_promoters(ps, settings=SETTINGS, commerce_on=False)
    a = scored["a"]
    n = 5.0  # 500 qualified views / 100
    assert a.n == n and a.confidence == pytest.approx(n / (n + 20))
    assert a.method_one.score == pytest.approx((n * a.own + 20 * a.category_average) / (n + 20))
    assert a.category_average == pytest.approx(sum(s.own for s in scored.values()) / 3)
    assert "low_confidence" in a.flags  # n below 20
    assert score_promoters([promoter("x", views=2500), promoter("y")], settings=SETTINGS,
                           commerce_on=False)["x"].flags.count("low_confidence") == 0


def test_method_two_cohort_falls_back_to_category_then_everyone() -> None:
    small = score_promoters([promoter("a"), promoter("b", reach=1)], settings=SETTINGS, commerce_on=False)
    assert small["a"].method_two.group == "all" and "small_cohort" in small["a"].flags
    many = [promoter(f"p{k}", reach=k) for k in range(25)]
    banded = score_promoters(many, settings=SETTINGS, commerce_on=False)
    assert banded["p24"].method_two.group == "band" and banded["p24"].method_two.score == 1.0
    mixed = [promoter(f"p{k}", reach=k, followers=5000 if k % 2 else 10) for k in range(25)]
    assert score_promoters(mixed, settings=SETTINGS, commerce_on=False)["p1"].method_two.group == "category"
    assert all(s.confidence == s.n / (s.n + 20) for s in banded.values())  # method two stores method one's confidence


def test_follower_bands() -> None:
    bands = (1000, 10000)
    assert [follower_band(f, bands) for f in (999, 1000, 10000, 10001)] == [
        "under_1000", "1000_to_10000", "1000_to_10000", "over_10000"]


def test_no_peers_uses_0_5_and_is_marked() -> None:
    scored = score_promoters([promoter("alone", cat="Gaming"), promoter("a"), promoter("b")], settings=SETTINGS,
                             commerce_on=False)
    alone = scored["alone"]
    assert alone.category_average == 0.5 and "no_peer_group" in alone.flags
    assert set(alone.percentiles.values()) == {0.5}


def test_no_qualified_views_is_not_scored() -> None:
    scored = score_promoters([promoter("a"), promoter("none", views=0, reach=0)], settings=SETTINGS, commerce_on=False)
    assert "none" not in scored


def test_a_confirmed_restriction_halves_both_methods() -> None:
    plain = score_promoters([promoter("a"), promoter("b", reach=5)], settings=SETTINGS, commerce_on=False)
    halved = score_promoters([promoter("a", trust_halved=True), promoter("b", reach=5)], settings=SETTINGS,
                             commerce_on=False)
    assert halved["a"].method_one.score == pytest.approx(plain["a"].method_one.score * 0.5)
    assert halved["a"].method_two.score == pytest.approx(plain["a"].method_two.score * 0.5)
    assert "trust_halved" in halved["a"].flags


def test_commerce_components_once_their_data_exists() -> None:
    ps = [promoter("a", completed_value=900, completed_count=3, final_count=4, bad_count=1),
          promoter("b", completed_value=100, completed_count=1, final_count=1)]
    scored = score_promoters(ps, settings=SETTINGS, commerce_on=True)
    a = scored["a"]
    assert a.raw["net_commerce"] == 900 and a.raw["conversion"] == pytest.approx(3 / 100 * 1000)
    assert a.raw["sales_quality"] == pytest.approx(0.75) and sum(a.weights.values()) == pytest.approx(1)
    assert a.percentiles["net_commerce"] == 1.0 and a.percentiles["sales_quality"] == 0.0


# --- on a database: the Build List's check ---------------------------------------------------------


@pytest.mark.mongo
async def test_the_promoter_job_on_a_database(store) -> None:
    from bson import ObjectId
    from pymongo import AsyncMongoClient

    from reco.slots.promoter import job
    from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri

    settings = store
    now = datetime.now(timezone.utc)
    client = AsyncMongoClient(_test_uri())
    platform, engine = client[TEST_PLATFORM_DB], client[TEST_DB]
    platform_names = ("users", "businessregisters", "posts", "products", "follows", "followers")
    engine_names = ("ml_events", "ml_orders", "ml_return_requests", "ml_sync_state", "ml_measurements",
                    "ml_fraud_cases", "ml_promoter_scores", "ml_promoter_scores_monthly", "ml_job_runs")
    for name in platform_names:
        await platform[name].delete_many({})
    for name in engine_names:
        await engine[name].delete_many({})

    a, r, b, c, young, v1, v2, buyer1, buyer2 = (ObjectId() for _ in range(9))
    s = ObjectId()  # a store owned by b
    old = now - timedelta(days=60)
    await platform["users"].insert_many([{"_id": u, "timestamp": old} for u in (a, r, b, c, v1, v2, buyer1, buyer2)]
                                        + [{"_id": young, "timestamp": now - timedelta(days=5)}])
    await platform["businessregisters"].insert_one({"_id": s, "user_id": str(b), "status": "Active", "timestamp": old,
                                                    "category": "Home & Living"})

    def post(author, cat, days=10, **extra):
        return {"_id": ObjectId(), "userId": author, "timestamp": now - timedelta(days=days), "categories": [cat], **extra}

    pa, ps, pc, py = post(a, "Pets"), post(s, "Home & Living"), post(c, "Gaming"), post(young, "Pets")
    rp = post(r, "Pets", days=5, isRepost=True, repostDetails={"originalPostId": pa["_id"]})
    await platform["posts"].insert_many([pa, ps, pc, py, rp])
    product = ObjectId()
    await platform["products"].insert_one({"_id": product, "deliveryConfig": {"returnWindow": 7, "isReturnApplicable": True}})

    def view(viewer, p):
        return {"_id": ObjectId(), "kind": "postevent", "event_type": "view", "user_id": str(viewer), "post_id": str(p["_id"]),
                "dwell_ms": 5000, "created_at": now - timedelta(days=2), "undone_at": None, "undo_of": None}

    await engine["ml_events"].insert_many([view(v1, pa), view(v2, pa), view(v1, ps), view(v1, pc), view(v2, pc),
                                           view(v1, py), view(v1, rp)])

    def copy(order_id, buyer_id, p, status, value, delivered_days=20):
        return {"_id": order_id, "order_id": order_id, "buyer_id": str(buyer_id), "post_id": str(p["_id"]),
                "promoter_id": str(p["userId"]), "product_id": str(product), "value": value, "status": status,
                "is_returned": status == "Returned", "history_conflict": False,
                "delivered_at": now - timedelta(days=delivered_days), "created_at": now - timedelta(days=25)}

    await engine["ml_orders"].insert_many([
        copy("o1", buyer1, rp, "Delivered", 100),  # through R's repost: credited to A
        copy("o2", buyer1, pa, "Returned", 40),  # returned in full
        copy("o3", buyer2, pa, "Delivered", 70),  # an open return request
        copy("o4", b, ps, "Delivered", 500),  # b buys through b's own store: nobody
    ])
    await engine["ml_return_requests"].insert_one({"_id": "rr3", "order_id": "o3", "is_active": True})
    await engine["ml_sync_state"].insert_one({"_id": "returnrequests", "last_run": {"outcome": "succeeded", "finished_at": now}})
    await engine["ml_measurements"].insert_one({"measure": "sync_reconciliation", "source": "returnrequests",
                                                "day": now.date().isoformat(), "passed": True})

    async def rows(method):
        """The current batch only: the batch it replaced is kept for requests still reading it."""
        from reco.store.writers import current_job_run_id

        batch = await current_job_run_id(settings, "promoter", method)
        return {row["promoter_id"]: row for row in
                await engine["ml_promoter_scores"].find({"method": method, "job_run_id": batch}).to_list(None)}

    try:
        report = await job.run(settings, now)
        one, two = job.methods()
        first, first_two = await rows(one), await rows(two)
        # Every eligible promoter, both methods, with confidence; reposts-only and young accounts are not.
        assert set(first) == set(first_two) == {str(a), str(s), str(c)}
        assert all(0 <= row["confidence"] <= 1 for row in first.values())
        assert report["not_scored"]["only_reposts"] == 1 and report["not_scored"]["younger_than_14_days"] == 1
        # A sale through the repost counts for A, the original author; the Returned order counts as returned.
        assert first[str(a)]["components"]["net_commerce"] == 100
        assert first[str(a)]["components"]["sales_quality"] == pytest.approx(0.5)  # o1 completed, o2 returned
        # The self-purchase through b's own store counts for nobody.
        assert first[str(s)]["components"]["net_commerce"] == 0 and report["orders_skipped"]["self_purchase"] == 1
        assert report["order_outcomes"]["open_return_request"] == 1

        # The request ends without a return (the window has passed): o3 becomes a completed sale.
        # And C gets a confirmed case that led to a restriction (level 3): C scores half.
        await engine["ml_return_requests"].update_one({"_id": "rr3"}, {"$set": {"is_active": False}})
        await engine["ml_fraud_cases"].insert_one({"account_id": str(c), "outcome": "confirmed", "level_recorded": 3,
                                                   "decided_at": now - timedelta(days=1), "in_force_until": None})
        await job.run(settings, now)
        second, second_two = await rows(one), await rows(two)
        assert second[str(a)]["components"]["net_commerce"] == 170
        assert second[str(c)]["score"] == pytest.approx(first[str(c)]["score"] * 0.5)
        assert second_two[str(c)]["score"] == pytest.approx(first_two[str(c)]["score"] * 0.5)
        assert "trust_halved" in second[str(c)]["flags"]

        # Copy not current: the job does not run and the batches stay.
        await engine["ml_measurements"].update_many({}, {"$set": {"passed": False}})
        skipped = await job.run(settings, now)
        assert skipped["skipped"] == "return-request copy not current" and await rows(one) == second
    finally:
        for name in platform_names:
            await platform[name].delete_many({})
        for name in engine_names:
            await engine[name].delete_many({})
        await client.close()
