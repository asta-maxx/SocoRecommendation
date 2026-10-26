"""ENG-17: M5, the product ranker, both methods.

The Build List's check: "Both methods serve on test. Hand-computed lift for three
pairs matches." And ENG-22's checks for M5: 6 (adjusted lift matches hand-computed
values), 7 (cart-based results are labelled intent), 9 (a product with no
co-purchase pair still returns a full list, and the fallback step used is
recorded), 10 (a batch older than 48 hours is stale and the ladder takes over),
11 (the context product, and anything already in the cart, never appear).

    hand-computed lift, three pairs        test_hand_computed_lift_for_three_pairs
    at least 2 co-purchases                test_a_pair_needs_at_least_two_co_purchases
    labelled intent                        test_cart_rows_are_labelled_intent
    the fallback order and its step        test_method_two_falls_back_to_method_one_and_records_the_step, ...
    context and cart never appear          test_the_context_product_and_the_cart_never_appear
    exactly limit                          test_a_list_is_exactly_limit_when_enough_are_eligible
    both methods serve, on a database      test_the_product_ranker_end_to_end_on_a_database
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from reco.eligibility.rules import Viewer
from reco.platform.records import VariantRecord
from reco.ranking import products
from reco.slots.assignment import Assignment
from reco.slots.product import bought_together as two
from reco.slots.product import job, ladder
from reco.slots.product import similarity as one

NOW = datetime(2026, 10, 17, 2, tzinfo=timezone.utc)
WEIGHTS = {"category": 0.35, "cross_sell": 0.20, "price_band": 0.15, "popularity": 0.20, "same_seller": 0.10}


def item(pid: str, *, leaf: str | None = "L1", seller: str | None = "S1", cross: tuple[str, ...] = (),
         price: float | None = 100.0, popularity: int = 0, top: str | None = "T1", created: float = 0.0) -> one.ProductItem:
    return one.ProductItem(pid, seller, top, leaf, frozenset(cross), price, popularity, created)


# --- method one: attribute similarity -----------------------------------------------------------


def test_the_weights_are_the_settings_sheets() -> None:
    from reco.config import live

    assert live.current().product.weights.model_dump() == WEIGHTS
    assert live.current().product.price_band_fraction == 0.30
    assert live.current().product.lift_strength == 10 and live.current().product.min_co_purchases == 2
    assert live.current().product.basket_source == "cart"  # APP-22 has not passed


def test_each_component_and_the_score_by_hand() -> None:
    viewed = item("V", cross=("X",), price=100)
    x = item("X", price=125)  # same category, on the cross-sell list, 125 within +-30%, same seller
    y = item("Y", leaf="L2", seller="S2", price=131)  # 131 is outside the band
    z = item("Z", leaf=None, price=70)  # no category: left out; 70 is exactly on the band's edge

    px = one.components(viewed, x, popularity=1.0, price_band=0.30)
    assert px == {"category": 1.0, "cross_sell": 1.0, "price_band": 1.0, "popularity": 1.0, "same_seller": 1.0}
    assert one.weighted(px, WEIGHTS) == pytest.approx(1.0)
    py = one.components(viewed, y, popularity=0.5, price_band=0.30)
    assert py == {"category": 0.0, "cross_sell": 0.0, "price_band": 0.0, "popularity": 0.5, "same_seller": 0.0}
    assert one.weighted(py, WEIGHTS) == pytest.approx(0.20 * 0.5)
    pz = one.components(viewed, z, popularity=0.0, price_band=0.30)
    assert pz["category"] is None and pz["price_band"] == 1.0
    # Category missing: the other four rescale over 0.65. (0.15 + 0.10) / 0.65.
    assert one.weighted(pz, WEIGHTS) == pytest.approx(0.25 / 0.65)


def test_missing_components_are_left_out_and_the_weights_rescale() -> None:
    viewed = item("V", cross=(), price=None)  # no cross-sell list, no price
    candidate = item("C", price=50)
    parts = one.components(viewed, candidate, popularity=0.25, price_band=0.30)
    assert parts["cross_sell"] is None and parts["price_band"] is None
    # category 0.35 x 1 + popularity 0.20 x 0.25 + seller 0.10 x 1, over 0.65.
    assert one.weighted(parts, WEIGHTS) == pytest.approx((0.35 + 0.05 + 0.10) / 0.65)
    assert one.weighted({c: None for c in WEIGHTS}, WEIGHTS) == 0.0


def test_the_price_is_the_lowest_among_active_variants() -> None:
    def v(price, status="active"):
        return VariantRecord(variant_id="v", product_id="p", seller_id=None, price=price, list_price=None, stock=1,
                             status=status, is_active=status == "active")

    assert one.lowest_active_price([v(300), v(120), v(90, "inactive"), v(None)]) == 120
    assert one.lowest_active_price([v(90, "inactive")]) is None
    assert one.in_price_band(100, 130, 0.30) is True and one.in_price_band(100, 130.5, 0.30) is False
    assert one.in_price_band(None, 100, 0.30) is None


def test_popularity_is_a_percentile_ties_counted_half() -> None:
    assert one.popularity_percentiles({"a": 0, "b": 5, "c": 5, "d": 9}) == {"a": 0.0, "b": 0.5, "c": 0.5, "d": 1.0}
    assert one.popularity_percentiles({"only": 3}) == {"only": 0.5}


def test_method_one_never_lists_the_viewed_product_and_keeps_the_best() -> None:
    viewed = item("V", cross=("B",))
    sellable = [viewed, item("A", leaf="L2", popularity=1), item("B", leaf="L2"), item("C", popularity=1),
                item("D", popularity=0)]
    pct = one.popularity_percentiles({i.product_id: i.popularity for i in sellable})
    top = one.top_similar(viewed, sellable, pct, weights=WEIGHTS, price_band=0.30, limit=3)
    assert [s.product_id for s in top] == ["C", "D", "B"]
    assert all(s.product_id != "V" for s in one.top_similar(viewed, sellable, pct, weights=WEIGHTS, price_band=0.3,
                                                             limit=10))


def test_popularity_counts_clicks_and_add_to_carts_not_test_accounts() -> None:
    rows = [{"product_id": "p1", "user_id": "u1", "event_type": "product_click", "created_at": NOW - timedelta(days=1)},
            {"product_id": "p1", "user_id": "u2", "event_type": "add_to_cart", "created_at": NOW - timedelta(days=2)},
            {"product_id": "p2", "user_id": "tester", "event_type": "click", "created_at": NOW - timedelta(days=1)},
            {"product_id": "p2", "user_id": "u1", "event_type": "click", "created_at": NOW + timedelta(hours=1)}]
    counts, skipped = job.popularity_counts(rows, anchor=NOW, tests={"tester"})
    assert counts == {"p1": 2} and skipped == {"test_account": 1, "no_time_or_future": 1}


def test_step_two_lists_are_by_top_level_category_most_popular_first() -> None:
    items = [item("a", top="T1", popularity=1, created=5), item("b", top="T1", popularity=3),
             item("c", top="T1", popularity=1, created=9), item("d", top="T2"), item("e", top=None)]
    lists = job.category_lists(items, limit=10)
    assert {k: [i.product_id for i in v] for k, v in lists.items()} == {"T1": ["b", "c", "a"], "T2": ["d"]}


# --- method two: bought together ----------------------------------------------------------------

#: Ten baskets. By hand: N = 10; n_A = 6, n_B = 4, n_C = 5, n_D = 3, n_E = 2;
#: A&B 3 times, A&C 3, C&D 2, B&C 1, B&D 1, A&E 1.
BASKETS = [frozenset(b) for b in ("AB", "AB", "ABC", "AC", "AC", "BD", "CD", "CD", "E", "AE")]


def test_hand_computed_lift_for_three_pairs() -> None:
    """The Build List's check (ENG-22 check 6). lift = n_AB x N / (n_A x n_B);
    adjusted = (n x lift + 10) / (n + 10).

        A&B  lift = 3 x 10 / (6 x 4) = 1.25        adjusted = (3 x 1.25 + 10) / 13 = 13.75 / 13 = 55/52
        A&C  lift = 3 x 10 / (6 x 5) = 1           adjusted = (3 + 10) / 13 = 1
        C&D  lift = 2 x 10 / (5 x 3) = 4/3         adjusted = (2 x 4/3 + 10) / 12 = 38/36 = 19/18
    """
    assert two.lift(3, 6, 4, 10) == pytest.approx(1.25)
    assert two.lift(3, 6, 5, 10) == pytest.approx(1.0)
    assert two.lift(2, 5, 3, 10) == pytest.approx(4 / 3)
    lists, counts = two.bought_together(BASKETS, strength=10, min_co_purchases=2, limit=100)
    assert counts.total == 10 and counts.single["A"] == 6 and counts.pairs[("A", "B")] == 3
    a = {p.product_id: p for p in lists["A"]}
    assert a["B"].score == pytest.approx(55 / 52) and a["B"].lift == pytest.approx(1.25) and a["B"].co_purchases == 3
    assert a["C"].score == pytest.approx(1.0)
    assert {p.product_id: p.score for p in lists["C"]} == pytest.approx({"D": 19 / 18, "A": 1.0})
    assert [p.product_id for p in lists["A"]] == ["B", "C"]  # 55/52 above 1
    assert [p.product_id for p in lists["C"]] == ["D", "A"]  # 19/18 above 1


def test_a_pair_needs_at_least_two_co_purchases() -> None:
    lists, counts = two.bought_together(BASKETS, strength=10, min_co_purchases=2, limit=100)
    assert counts.pairs[("B", "C")] == counts.pairs[("B", "D")] == counts.pairs[("A", "E")] == 1
    assert [p.product_id for p in lists["B"]] == ["A"]  # not C or D: once each
    assert [p.product_id for p in lists["D"]] == ["C"]
    assert "E" not in lists  # E's only pair is once: no list, the request falls back


def test_a_partner_must_be_sellable_and_lists_are_capped() -> None:
    lists, _ = two.bought_together(BASKETS, strength=10, min_co_purchases=2, limit=1, allowed={"A", "C"})
    assert [p.product_id for p in lists["A"]] == ["C"] and [p.product_id for p in lists["B"]] == ["A"]
    assert "C" in lists and [p.product_id for p in lists["C"]] == ["A"]


def test_checkout_baskets_leave_out_cancelled_and_rejected_and_count_incognito() -> None:
    orders = [
        {"checkout_id": "k1", "product_id": "A", "status": "Delivered"},
        {"checkout_id": "k1", "product_id": "B", "status": "Returned"},  # only Cancelled and Rejected are left out
        {"checkout_id": "k1", "product_id": "B", "status": "Shipped"},  # the same product twice counts once
        {"checkout_id": "k2", "product_id": "A", "status": "cancelled"},  # ignoring case
        {"checkout_id": "k2", "product_id": "C", "status": "Rejected"},
        {"checkout_id": "k3", "product_id": "C", "status": "Pending", "is_incognito": True},  # incognito counts
        {"checkout_id": None, "product_id": "D", "status": "Delivered"},
    ]
    baskets, skipped = two.checkout_baskets(orders, left_out=("Cancelled", "Rejected"))
    assert baskets == [frozenset("AB"), frozenset("C")]
    assert skipped == {"cancelled_or_rejected": 2, "no_checkout_id": 1}


def test_cart_baskets_are_one_per_owner() -> None:
    def line(user, product):
        return SimpleNamespace(user_id=user, product_id=product)

    baskets, skipped = two.cart_baskets([line("u1", "A"), line("u1", "B"), line("u1", "A"), line("u2", "C"),
                                         line(None, "D"), line("u3", None)])
    assert baskets == [frozenset("AB"), frozenset("C")] and skipped == {"no_owner": 1, "no_product": 1}


def test_cart_rows_are_labelled_intent() -> None:
    """ENG-22 check 7: until APP-22 passes, method two runs over carts, labelled intent."""
    assert two.LABELS == {"cart": "intent", "checkout": "checkout"}
    lists, _ = two.bought_together(BASKETS, strength=10, min_co_purchases=2, limit=100)
    common = {"job_run_id": "r1", "method": "bought_together"}
    rows = job.method_two_rows({"together": lists, "categories": {}}, common, two.LABELS["cart"], "cart")
    assert rows and all(r["label"] == "intent" and r["basket_source"] == "cart" for r in rows)
    assert all("buyer_id" not in r and "user_id" not in r for r in rows)  # no buyer is ever named


# --- the fallback order -----------------------------------------------------------------------------


def test_the_fallback_order_for_each_method() -> None:
    names = {"method_one": "attribute_similarity", "method_two": "bought_together"}
    assert ladder.ladder("bought_together", **names) == ("own", "product_step_1", "product_step_2", "product_step_3")
    assert ladder.ladder("attribute_similarity", **names) == ("own", "product_step_2", "product_step_3")


def test_the_step_recorded_is_the_first_fallback_step_used() -> None:
    assert ladder.reported_step(["own"]) is None
    assert ladder.reported_step(["own", "product_step_2", "product_step_3"]) == "product_step_2"
    filled = ladder.fill([("own", []), ("product_step_1", ["x", "y"]), ("product_step_2", ["z"])], 2, set())
    assert filled.product_ids == ["x", "y"] and filled.fallback_step == "product_step_1" and not filled.method_served
    assert "product_step_2" not in filled.added  # never reached: the list was full


def test_fill_dedupes_and_excludes() -> None:
    filled = ladder.fill([("own", ["a", "ctx", "b"]), ("product_step_2", ["b", "cart", "c", "d"])], 3, {"ctx", "cart"})
    assert filled.product_ids == ["a", "b", "c"] and filled.added == {"own": 2, "product_step_2": 1}
    assert filled.fallback_step == "product_step_2" and filled.method_served


# --- the request (no database: every read is stubbed) -------------------------------------------------


def assignment(method: str) -> Assignment:
    which = "method_two" if method == "bought_together" else "method_one"
    return Assignment("product_ranking", method, which, 1, "1")


@pytest.fixture
def platform(monkeypatch):
    """A stand-in for the reads: STATE says what each batch holds, what is eligible,
    what is newest, and what the viewer has in the cart."""
    state = {
        "batches": {"attribute_similarity": "b1", "bought_together": "b2"},
        "lists": {},  # (batch, context) -> [ids]
        "categories": {},  # (batch, top-level category) -> [ids]
        "newest": [f"n{k}" for k in range(1, 31)],
        "ineligible": set(),
        "cart": frozenset(),
        "reads": [],
    }

    async def viewer(settings, user_id):
        return Viewer(user_id=user_id, in_cart=state["cart"])

    async def current_batch(settings, method, now, hours):
        batch = state["batches"].get(method)
        return (batch, "current") if batch else (None, "no current batch")

    async def product_list(settings, batch, context):
        state["reads"].append(("list", batch))
        return list(state["lists"].get((batch, context), []))

    async def category_list(settings, batch, category):
        state["reads"].append(("category", batch, category))
        return list(state["categories"].get((batch, category), []))

    async def read_where(settings, kind, field, ids):
        return [SimpleNamespace(product_id=i, category_id="T1") for i in ids]

    async def read_newest(settings, kind, limit, skip=0):
        return [SimpleNamespace(product_id=i) for i in state["newest"][skip:skip + limit]]

    async def eligible(settings, rows, viewer, request_id, cache):
        return [r for r in rows if r.product_id not in state["ineligible"]]

    monkeypatch.setattr(products, "viewer_context", viewer)
    monkeypatch.setattr(products.store, "current_batch", current_batch)
    monkeypatch.setattr(products.store, "read_product_list", product_list)
    monkeypatch.setattr(products.store, "read_category_list", category_list)
    monkeypatch.setattr(products.fetch, "read_where", read_where)
    monkeypatch.setattr(products.fetch, "read_newest", read_newest)
    monkeypatch.setattr(products, "eligible_products", eligible)
    return state


async def build(method: str, limit: int = 3, page: int = 1, context: str = "ctx"):
    from reco.config import Settings

    return await products.product_candidates(Settings(), page, limit, context, "u1", "r1", assignment(method))


async def test_the_assigned_methods_own_list_serves_first(platform) -> None:
    platform["lists"] = {("b2", "ctx"): ["t1", "t2", "t3", "t4", "t5", "t6"], ("b1", "ctx"): ["s1"]}
    built = await build("bought_together")
    assert [c.item_id for c in built.candidates] == ["t1", "t2", "t3", "t4", "t5", "t6"]
    assert built.fallback_step is None and built.detail["method_served"] is True
    assert built.detail["label"] == "intent" and built.detail["ordering"] == "eng17_product_ranker"
    assert all(c.item_type == "product" and c.post_id is None and c.product_id == c.item_id for c in built.candidates)


async def test_method_two_falls_back_to_method_one_and_records_the_step(platform) -> None:
    """ENG-22 check 9: no co-purchase pair, still a full list, and the step recorded."""
    platform["lists"] = {("b1", "ctx"): [f"s{k}" for k in range(1, 9)]}
    built = await build("bought_together")
    assert [c.item_id for c in built.candidates] == [f"s{k}" for k in range(1, 7)]
    assert built.fallback_step == "product_step_1" and built.detail["method_served"] is False
    assert built.detail["steps_used"] == {"product_step_1": 6}


async def test_then_the_top_level_category_then_newest(platform) -> None:
    platform["lists"] = {("b1", "ctx"): ["s1"]}
    platform["categories"] = {("b2", "T1"): ["c1", "c2"]}
    built = await build("bought_together")
    assert [c.item_id for c in built.candidates] == ["s1", "c1", "c2", "n1", "n2", "n3"]
    assert built.fallback_step == "product_step_1"
    assert built.detail["steps_used"] == {"product_step_1": 1, "product_step_2": 2, "product_step_3": 3}

    platform["lists"] = {}
    built = await build("bought_together")
    assert built.fallback_step == "product_step_2" and [c.item_id for c in built.candidates][:2] == ["c1", "c2"]

    platform["categories"] = {}
    built = await build("bought_together")
    assert built.fallback_step == "product_step_3" and len(built.candidates) == 6  # never empty


async def test_method_one_with_no_list_takes_steps_two_and_three(platform) -> None:
    platform["categories"] = {("b1", "T1"): ["c1"]}
    built = await build("attribute_similarity")
    assert [c.item_id for c in built.candidates] == ["c1", "n1", "n2", "n3", "n4", "n5"]
    assert built.fallback_step == "product_step_2" and "label" not in built.detail
    assert not any(r[0] == "list" and r[1] == "b2" for r in platform["reads"])  # method two's batch never read


async def test_no_current_batch_falls_to_newest(platform) -> None:
    platform["batches"] = {}
    built = await build("bought_together")
    assert built.fallback_step == "product_step_3" and len(built.candidates) == 6
    assert built.detail["batch"] == {"job_run_id": None, "why": "no current batch"}


async def test_the_context_product_and_the_cart_never_appear(platform) -> None:
    """ENG-22 check 11, Kala 16 Oct: the context product and every product in the
    viewer's cart are left out of every step."""
    platform["cart"] = frozenset({"t2", "c1", "n1"})
    platform["lists"] = {("b2", "ctx"): ["ctx", "t1", "t2"], ("b1", "ctx"): ["ctx", "t2", "s1"]}
    platform["categories"] = {("b2", "T1"): ["c1", "ctx", "c2"]}
    platform["newest"] = ["ctx", "n1", "n2", "n3", "n4"]
    built = await build("bought_together", limit=10)
    ids = [c.item_id for c in built.candidates]
    assert ids == ["t1", "s1", "c2", "n2", "n3", "n4"]
    assert not {"ctx", "t2", "c1", "n1"} & set(ids)


async def test_the_filters_apply_to_every_step(platform) -> None:
    platform["ineligible"] = {"t1", "s1", "c1", "n1"}
    platform["lists"] = {("b2", "ctx"): ["t1", "t2"], ("b1", "ctx"): ["s1", "s2"]}
    platform["categories"] = {("b2", "T1"): ["c1", "c2"]}
    built = await build("bought_together", limit=3)
    assert [c.item_id for c in built.candidates] == ["t2", "s2", "c2", "n2", "n3", "n4"]


async def test_a_list_is_exactly_limit_when_enough_are_eligible(platform) -> None:
    from reco.ranking import serving

    platform["lists"] = {("b2", "ctx"): ["t1", "t2"]}
    built = await build("bought_together", limit=5)

    async def nothing_failed(settings, items, viewer, request_id, cache=None):
        return set()

    serving_recheck = serving.recheck
    serving.recheck = nothing_failed
    try:
        page = await serving.page_after_recheck(None, built, 1, 5, "r1")
        assert len(page) == 5
        page_two = await serving.page_after_recheck(None, built, 2, 5, "r1")
        assert len(page_two) == 5 and not {c.item_id for c in page} & {c.item_id for c in page_two}
    finally:
        serving.recheck = serving_recheck
    platform["newest"] = ["n1"]  # fewer eligible products than limit: fewer, never padded
    built = await build("bought_together", limit=5)
    assert [c.item_id for c in built.candidates] == ["t1", "t2", "n1"]


# --- the request path and the nightly list -----------------------------------------------------------


async def test_the_product_surface_reports_the_step(monkeypatch, settings) -> None:
    from reco.api import recommendations as api
    from reco.ranking import serving
    from tests.conftest import put_in_force
    from tests.test_recommendations import LIVE, TOKEN, call, feed

    settings = settings.model_copy(update={"ingest_token": TOKEN})
    records = []

    async def product_list(settings, page, limit, context, user_id, request_id, a):
        assert a.slot == "product_ranking"
        made = [serving.Candidate(f"p{n}", "product", None, f"p{n}", rank=n) for n in range(1, 11)]
        return serving.Built(Viewer(user_id=user_id), made, {}, 10, fallback_step="product_step_1",
                             detail={"ordering": products.ORDERING, "steps_used": {"product_step_1": 10},
                                     "method_served": False, "batch": {"job_run_id": "b2", "why": "current"},
                                     "label": "intent"})

    async def record(settings, doc):
        records.append(doc)

    async def nothing_failed(settings, items, viewer, request_id, cache=None):
        return set()

    monkeypatch.setattr(api.product_ranker, "product_candidates", product_list)
    monkeypatch.setattr(serving, "recheck", nothing_failed)
    monkeypatch.setattr(api.writers, "record_served_list", record)
    put_in_force(LIVE)
    status, body = await call(settings, feed(surface="product", context_item_id="6a062d0f75f362743de14269", limit=5))
    assert status == 200 and body["fallback_step"] == "product_step_1" and len(body["items"]) == 5
    entry = records[0]["slot_methods"][0]
    assert entry["slot"] == "product_ranking" and entry["fallback_step"] == "product_step_1"
    assert entry["method_served"] is False and entry["label"] == "intent"
    assert entry["steps_used"] == {"product_step_1": 10}
    assert records[0]["ordering"] == products.ORDERING and records[0]["fallback_step"] == "product_step_1"


def test_the_job_runs_nightly_after_promoter() -> None:
    from reco.jobs.__main__ import JOBS
    from reco.jobs.scheduler import NIGHTLY

    assert "product_ranking" in JOBS
    assert NIGHTLY[NIGHTLY.index("promoter") + 1] == "product_ranking" and NIGHTLY[-1] == "reconcile_sync"


# --- MongoDB: the job and the request end to end -------------------------------------------------------


@pytest.mark.mongo
async def test_the_product_ranker_end_to_end_on_a_database(store) -> None:
    """Both methods written as current batches; both serve through the request path;
    the cart's products and the context product never appear; a pair seen once is
    no pair; a stale batch is not read."""
    from bson import ObjectId
    from pymongo import AsyncMongoClient

    from reco.jobs.__main__ import JOBS
    from reco.slots.assignment import assign
    from reco.store import product_scores
    from reco.store.scores import utc_now
    from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri, put_in_force
    from tests.test_recommendations import LIVE, TOKEN, call, feed

    settings = store.model_copy(update={"ingest_token": TOKEN})
    now = utc_now()
    client = AsyncMongoClient(_test_uri())
    platform, engine = client[TEST_PLATFORM_DB], client[TEST_DB]
    platform_names = ("users", "businessregisters", "products", "productvariants", "carts", "categories", "follows",
                      "followers")
    engine_names = ("ml_events", "ml_orders", "ml_product_scores", "ml_job_runs")
    for name in platform_names:
        await platform[name].delete_many({})
    for name in engine_names:
        await engine[name].delete_many({})
    try:
        seller, other_seller = ObjectId(), ObjectId()
        await platform["businessregisters"].insert_many([
            {"_id": seller, "status": "Active", "accountIsPublic": True},
            {"_id": other_seller, "status": "Active", "accountIsPublic": True}])
        top, leaf, leaf2 = ObjectId(), ObjectId(), ObjectId()
        ids = {name: ObjectId() for name in "ABCDEFGH"}

        def product(name, minutes, *, by=seller, category=leaf, **extra):
            return {"_id": ids[name], "createdBy": by, "createdAt": now - timedelta(minutes=minutes),
                    "status": "Activate", "availability": {"inStock": True}, "categoryPathIds": [top, category],
                    "basicInfo": {"categoryId": category}, "crossSellProducts": [], **extra}

        await platform["products"].insert_many([
            product("A", 10, crossSellProducts=[ids["F"]]), product("B", 9), product("C", 8, category=leaf2),
            product("D", 7, by=other_seller), product("E", 6), product("F", 5, category=leaf2),
            product("G", 4, availability={"inStock": False}),  # not sellable: never listed
            product("H", 3, by=other_seller, category=leaf2),
        ])
        prices = {"A": 100, "B": 120, "C": 500, "D": 200, "E": 1000, "F": 110, "G": 100, "H": 100}
        await platform["productvariants"].insert_many([
            {"_id": ObjectId(), "productId": ids[n], "salePrice": p, "quantity": 5, "reservedStock": 0, "status": "active"}
            for n, p in prices.items()])

        # Carts (method two, "intent"): A&B in 3 carts, A&C in 2, B&D once. Plus the viewer's cart.
        shoppers = [str(ObjectId()) for _ in range(6)]
        viewer = next(u for u in (str(ObjectId()) for _ in range(500))
                      if assign("product_ranking", u).method == "bought_together")
        viewer_one = next(u for u in (str(ObjectId()) for _ in range(500))
                          if assign("product_ranking", u).method == "attribute_similarity")
        cart = [(shoppers[0], "AB"), (shoppers[1], "AB"), (shoppers[2], "ABC"), (shoppers[3], "AC"), (shoppers[4], "BD"),
                (shoppers[5], "E"), (viewer, "C"), (viewer_one, "C")]
        await platform["carts"].insert_many([
            {"_id": ObjectId(), "user_id": ObjectId(u), "userModel": "user", "product_id": ids[n], "quantity": 1,
             "timestamp": now - timedelta(days=1)} for u, names in cart for n in names])
        # Popularity: E clicked three times, D added to a cart once.
        await engine["ml_events"].insert_many([
            *({"_id": ObjectId(), "kind": "postevent", "event_type": "product_click", "product_id": str(ids["E"]),
               "user_id": shoppers[0], "created_at": now - timedelta(days=2), "undone_at": None, "undo_of": None}
              for _ in range(3)),
            {"_id": ObjectId(), "kind": "postevent", "event_type": "add_to_cart", "product_id": str(ids["D"]),
             "user_id": shoppers[1], "created_at": now - timedelta(days=2), "undone_at": None, "undo_of": None},
            {"_id": ObjectId(), "kind": "postevent", "event_type": "product_click", "product_id": str(ids["D"]),
             "user_id": shoppers[1], "created_at": now - timedelta(days=40), "undone_at": None, "undo_of": None},
        ])

        await JOBS["product_ranking"](settings)

        runs = await engine["ml_job_runs"].find({"job": "product_ranking"}).to_list(None)
        assert {r["method"] for r in runs} == {"attribute_similarity", "bought_together"}
        assert all(r["outcome"] == "succeeded" and r["is_current"] for r in runs)
        rows = await engine["ml_product_scores"].find({}).to_list(None)
        assert all(r["slot"] == "product_ranking" and r["job_run_id"] and r["computed_at"] and r["config_version"]
                   and r["model_version"] for r in rows)
        assert str(ids["G"]) not in {r["product_id"] for r in rows}  # out of stock: never listed
        together = [r for r in rows if r["list"] == "bought_together"]
        assert together and all(r["label"] == "intent" for r in together)
        a_list = sorted((r for r in together if r["context_product_id"] == str(ids["A"])), key=lambda r: r["rank"])
        # 8 carts (6 shoppers + 2 viewers); n_A = 4, n_B = 4, n_C = 4 (ABC, AC, and the viewers' two); A&B 3, A&C 2.
        # A&B: lift 3 x 8 / 16 = 1.5, adjusted (4.5 + 10) / 13. A&C: lift 2 x 8 / 16 = 1, adjusted 1.
        assert [r["product_id"] for r in a_list] == [str(ids["B"]), str(ids["C"])]
        assert a_list[0]["score"] == pytest.approx(14.5 / 13) and a_list[1]["score"] == pytest.approx(1.0)
        assert not [r for r in together if r["context_product_id"] == str(ids["D"])]  # B&D once: no pair
        a_similar = sorted((r for r in rows if r["list"] == "similar" and r["context_product_id"] == str(ids["A"])),
                           key=lambda r: r["rank"])
        assert a_similar[0]["product_id"] == str(ids["B"])  # same category, seller and price band
        category = sorted((r for r in rows if r["list"] == "category_popular" and r["method"] == "bought_together"),
                          key=lambda r: r["rank"])
        assert [r["product_id"] for r in category[:2]] == [str(ids["E"]), str(ids["D"])]  # 3 clicks, then 1 add

        put_in_force(LIVE)
        # Method two, viewing A, with C in the cart: B (its own list), then step 1.
        status, body = await call(settings, feed(user_id=viewer, surface="product", context_item_id=str(ids["A"]),
                                                 limit=5))
        served = [i["item_id"] for i in body["items"]]
        assert status == 200 and served[0] == str(ids["B"]) and len(served) == 5
        assert str(ids["A"]) not in served and str(ids["C"]) not in served and str(ids["G"]) not in served
        assert body["fallback_step"] == "product_step_1"  # its own list held only B (C is in the cart)
        record = await engine["ml_events"].find_one({"request_id": body["request_id"]})
        entry = record["slot_methods"][0]
        assert entry["method"] == "bought_together" and entry["label"] == "intent" and entry["method_served"] is True
        assert record["served_items"] == body["items"]
        # Method two, viewing E (no pair): a full list from step 1, the step recorded.
        status, body = await call(settings, feed(user_id=viewer, surface="product", context_item_id=str(ids["E"]),
                                                 limit=5))
        assert body["fallback_step"] == "product_step_1" and len(body["items"]) == 5
        # Method one, viewing A: its own list, no fallback.
        status, body = await call(settings, feed(user_id=viewer_one, surface="product", context_item_id=str(ids["A"]),
                                                 limit=3))
        assert body["fallback_step"] is None and [i["item_id"] for i in body["items"]][0] == str(ids["B"])
        assert body["policy_id"].endswith(".product_ranking-attribute_similarity")

        # A batch older than 48 hours is stale: the ladder takes over (ENG-22 check 10).
        await engine["ml_job_runs"].update_many({"job": "product_ranking"},
                                                {"$set": {"finished_at": now - timedelta(hours=49)}})
        assert (await product_scores.current_batch(settings, "attribute_similarity", utc_now(), 48))[0] is None
        status, body = await call(settings, feed(user_id=viewer_one, surface="product", context_item_id=str(ids["A"]),
                                                 limit=3))
        assert status == 200 and body["fallback_step"] == "product_step_3" and len(body["items"]) == 3

        # Once APP-22 passes: checkout baskets, labelled checkout.
        await engine["ml_job_runs"].delete_many({})
        await engine["ml_orders"].insert_many([
            {"_id": ObjectId(), "checkout_id": "k1", "product_id": str(ids["A"]), "status": "Delivered"},
            {"_id": ObjectId(), "checkout_id": "k1", "product_id": str(ids["H"]), "status": "Delivered",
             "is_incognito": True},
            {"_id": ObjectId(), "checkout_id": "k2", "product_id": str(ids["A"]), "status": "Shipped"},
            {"_id": ObjectId(), "checkout_id": "k2", "product_id": str(ids["H"]), "status": "Pending"},
            {"_id": ObjectId(), "checkout_id": "k3", "product_id": str(ids["A"]), "status": "Cancelled"},
            {"_id": ObjectId(), "checkout_id": "k3", "product_id": str(ids["B"]), "status": "Cancelled"},
        ])
        put_in_force({**LIVE, "product.basket_source": "checkout"})
        await JOBS["product_ranking"](settings)
        rows = await engine["ml_product_scores"].find({"list": "bought_together"}).to_list(None)
        assert {(r["context_product_id"], r["product_id"]) for r in rows} == {(str(ids["A"]), str(ids["H"])),
                                                                            (str(ids["H"]), str(ids["A"]))}
        # 2 baskets (k3 cancelled), both A&H: lift = 2 x 2 / (2 x 2) = 1, adjusted 1.
        assert all(r["label"] == "checkout" and r["score"] == pytest.approx(1.0) for r in rows)
    finally:
        for name in platform_names:
            await platform[name].delete_many({})
        for name in engine_names:
            await engine[name].delete_many({})
        await client.close()
