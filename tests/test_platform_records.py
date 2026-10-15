"""ENG-03 (Build List v1.3): read platform data correctly.

The Build List check: "Unit tests read one of each record type and return the
expected values, including a follows record with text ids, a businessRegister
actor, a product post on a platform feed list, and an order with a status log
and a return request." ENG-29 replaces the status log with tracking_info, the
platform's order history. Document shapes copy the platform rows seen on 1 Oct 2026.
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from bson import ObjectId

from reco.config import IGNORED_PLATFORM_DATA, PLATFORM_COLLECTIONS
from reco.config.tunables import OrderStatusValues
from reco.platform import records, sources
from reco.platform.categories import CategoryVocabulary, ProductCategoryIndex, canonical_name
from reco.platform.ids import time_of
from reco.platform.native_events import NATIVE_EVENTS, engine_surface

VOCAB = CategoryVocabulary(
    canonical=["Fashion & Apparel", "Electronics", "Home & Living", "Shoes & Footwear", "Books & Education"],
    legacy_map={"Fashion": "Fashion & Apparel"},  # never consulted: ENG-03 matches by name
)
UTC = timezone.utc
T = datetime(2026, 9, 24, 11, 33, 57, 792000, tzinfo=UTC)
UID = ObjectId("6a3a6df8bac0b9eb430edc7c")
BIZ = ObjectId("6a5a78e94834d0026569a0e9")
PID = ObjectId("6a3fe727cce0b0785136e86a")
PRODUCT = ObjectId("6a5a79b94834d0026569a19f")
CATEGORY = ObjectId("6ab48d468844dddd68a1223e")


# --- helpers -------------------------------------------------------------------------


def test_time_comes_from_the_field_when_present() -> None:
    assert time_of({"_id": ObjectId(), "created_at": T}, "created_at") == T


def test_a_missing_time_is_read_from_the_id() -> None:
    oid = ObjectId.from_datetime(datetime(2026, 9, 20, 10, 30, tzinfo=UTC))
    assert time_of({"_id": oid}, "created_at") == datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
    assert time_of({"_id": str(oid)}, "created_at") == datetime(2026, 9, 20, 10, 30, tzinfo=UTC)


@pytest.mark.parametrize("stored", ["Activate", "activate", " ACTIVATE "])
def test_status_is_compared_ignoring_case(stored: str) -> None:
    assert records.status_is(stored, "activate")


@pytest.mark.parametrize("stored,kind", [("user", "user"), ("businessRegister", "business"), ("BUSINESSREGISTER", "business"), (None, "unknown")])
def test_actor_kind_comes_from_user_model(stored, kind: str) -> None:
    assert records.actor_kind(stored) == kind


def test_categories_match_by_name_then_the_category_map_never_the_legacy_map() -> None:
    assert canonical_name(VOCAB, "  fashion  &  APPAREL ") == "Fashion & Apparel"
    assert canonical_name(VOCAB, "Fashion") is None  # not by name, no map entry: dropped
    assert canonical_name(VOCAB, "Fashion", {"fashion": "Fashion & Apparel"}) == "Fashion & Apparel"
    assert canonical_name(VOCAB, "Books", {"books": "Not a category"}) is None  # map target must be one of the 23


# --- the native event map and surfaces (Capture Register sheet 4, F02) --------------------


def test_sheet_4_lists_26_native_types() -> None:
    assert len(NATIVE_EVENTS) == 26


@pytest.mark.parametrize(
    "event_type,code,scored",
    [("impression", "E2", False), ("click", "E3", True), ("product_click", "E3", True), ("view", None, True),
     ("unlike", "E9", True), ("repost", "E9", False), ("add_to_cart", "E4", True), ("remove_from_cart", "E4", False),
     ("purchase", "E5", True), ("feedback", "E13", True), ("search", None, False)],
)
def test_native_types_map_to_e_codes(event_type: str, code, scored: bool) -> None:
    entry = NATIVE_EVENTS[event_type]
    assert (entry.code, entry.scored) == (code, scored)


@pytest.mark.parametrize("native,engine", [("home_for_you", "feed"), ("product_detail", "product"), ("cart", "product"),
                                           ("post_detail", None), ("following", None)])
def test_native_surfaces_map_to_engine_surfaces(native: str, engine) -> None:
    assert engine_surface(native) == engine


# --- one of each record type ---------------------------------------------------------


def test_user() -> None:
    doc = {"_id": UID, "status": "Active", "city": "Chennai", "DOB": "2001-04-12", "accountIsPublic": True,
           "interest": ["Fashion & Apparel", "Cricket"], "addNew_Interest": ["x"], "interestScores": {"x": 1},
           "password": "never-read", "timestamp": T}
    user = records.parse_user(doc, VOCAB)

    assert user.user_id == str(UID) and user.is_active and user.city == "Chennai"
    assert user.date_of_birth == date(2001, 4, 12)
    assert user.declared_interests == ["Fashion & Apparel"]
    assert "password" not in user.model_dump()


def test_business() -> None:
    doc = {"_id": BIZ, "user_id": str(UID), "category": "electronics", "status": "Inactive",
           "accountIsPublic": False, "timestamp": T}
    business = records.parse_business(doc, VOCAB)

    assert business.owner_user_id == str(UID) and business.category == "Electronics"
    assert not business.is_active and not business.account_is_public


def test_follow_with_text_ids() -> None:
    """The check's first case: follows stores ids as text."""
    doc = {"_id": ObjectId(), "userId": str(UID), "followingId": str(BIZ), "userReference": "User",
           "followingReference": "businessRegister", "createdAt": T}
    follow = records.parse_follow(doc)

    assert (follow.follower_id, follow.followed_id, follow.followed_kind) == (str(UID), str(BIZ), "business")


def test_postevent_from_a_businessregister_actor() -> None:
    """The check's second case: user_model says the actor id is in businessregisters."""
    doc = {"_id": ObjectId(), "event_type": "like", "user_id": BIZ, "user_model": "businessRegister",
           "post_id": PID, "influencer_id": UID, "is_self": False, "event_id": "abc:like", "created_at": T}
    event = records.parse_postevent(doc)

    assert event.actor == "business" and event.user_id == str(BIZ)
    assert (event.event_code, event.scored) == ("E9", True)
    assert event.event_id == "abc:like"  # opaque, kept as written


def test_a_product_post_on_a_platform_feed_list() -> None:
    """The check's third case, as seen on the platform: a feed click with post_id,
    item_type product and no item_id is a post card showing a product."""
    doc = {"_id": ObjectId(), "event_type": "click", "post_id": PID, "product_id": None, "item_type": "product",
           "surface": "home_for_you", "position": 1, "request_id": "req_d7c99e1dbc10",
           "event_id": "click_6a3fe727cce0b0785136e86a_1790249631561402_204564", "user_id": UID,
           "user_model": "user", "created_at": T}
    event = records.parse_postevent(doc)

    assert event.surface == "feed" and event.event_code == "E3"
    assert event.item_id == str(PID) and event.post_id == str(PID)
    assert event.product_id is None  # a post id is never read as a product id
    assert event.request_id == "req_d7c99e1dbc10" and event.position == 1


def test_a_product_card_on_the_product_surface_is_a_product() -> None:
    doc = {"_id": ObjectId(), "event_type": "impression", "item_id": PRODUCT, "item_type": "product",
           "surface": "product_detail", "position": 2, "request_id": "r1", "user_id": UID}
    event = records.parse_postevent(doc)

    assert event.surface == "product" and (event.item_id, event.product_id) == (str(PRODUCT), str(PRODUCT))
    assert event.post_id is None and not event.is_page_visit


def test_a_post_page_impression_is_a_page_visit() -> None:
    event = records.parse_postevent({"_id": ObjectId(), "event_type": "impression", "post_id": PID,
                                     "item_type": "post", "surface": "post_detail", "user_id": UID})
    assert event.is_page_visit and event.surface is None


def test_undo_fields_dwell_and_own_posts_are_kept() -> None:
    original = records.parse_postevent({"_id": ObjectId(), "event_type": "like", "post_id": PID, "user_id": UID,
                                        "undone_at": T, "is_self": True, "dwell_ms": None, "created_at": T})
    undo = records.parse_postevent({"_id": ObjectId(), "event_type": "unlike", "post_id": PID, "user_id": UID,
                                    "undo_of": original.source_id, "created_at": T})
    view = records.parse_postevent({"_id": ObjectId(), "event_type": "view", "post_id": PID, "user_id": UID,
                                    "dwell_ms": 4200, "view_duration_seconds": 4.2})

    assert original.undone_at == T and original.is_self
    assert undo.undo_of == original.source_id
    assert view.dwell_ms == 4200.0 and view.event_code is None and view.scored


def test_order_with_history_and_a_return_request() -> None:
    """The check's fourth case, as ENG-30 (v1.4) replaces it: the history is
    tracking_info mapped to events; a return is order_status Returned, timed by
    return_info.returned_at. A 'Return requested' event alone returns nothing."""
    later = T + timedelta(days=29)
    doc = {"_id": ObjectId(), "user_id": UID, "userModel": "user", "seller_id": BIZ, "product_id": PRODUCT,
           "variant_id": ObjectId(), "checkout_id": "58e9b6b2-762a-48db-b013-67449ba06fa5", "total_price": 2299,
           "order_status": "Returned", "buyer_approval_status": "Approved", "isIncognitoMode": True,
           "return_info": {"reason": "Arrived damaged or broken", "recorded_by": "seller", "returned_at": later},
           "tracking_info": [{"status": "Order created by Rahul", "timestamp": T, "_id": ObjectId()},
                             {"status": "Delivered (Urban Vogue Fashion Studio)", "timestamp": T, "_id": ObjectId()},
                             {"status": "Return requested (RET-115A15BF)", "timestamp": later, "_id": ObjectId()},
                             {"status": "Returned to seller", "timestamp": later, "_id": ObjectId()}],
           "created_at": T, "updated_at": later}
    order = records.parse_order(doc)

    assert order.is_returned and order.returned_at == later and order.delivered_at == T
    assert [e.stage for e in order.tracking] == ["created", "delivered", "return_request", "returned"]
    requested_only = {**doc, "order_status": "Delivered", "return_info": {"returned_at": None, "reason": None}}
    assert not records.parse_order(requested_only).is_returned  # a request is not a return
    assert records.parse_order(requested_only).returned_at is None  # return_info with nulls means nothing
    assert order.value == 2299.0 and order.variant_id and order.checkout_id.startswith("58e9")
    assert order.is_incognito and order.buyer_actor == "user"  # purchase privacy only: still read


@pytest.mark.parametrize(
    "status,approval,who",
    [("Cancelled", None, "buyer"), ("Rejected", "Rejected By Seller", "seller"), ("Rejected", "Rejected", "buyer"),
     ("Delivered", None, None)],
)
def test_who_cancelled_is_worked_out(status: str, approval, who) -> None:
    """DS-017 v2.5 section 6.4: cancelled_by is worked out, not stored."""
    order = records.parse_order({"_id": ObjectId(), "order_status": status, "buyer_approval_status": approval,
                                 "reason_code": "out_of_stock"})
    assert order.cancelled_by == who and order.cancel_reasons == {"reason_code": "out_of_stock"}


def test_the_stored_return_value_comes_from_the_settings() -> None:
    custom = OrderStatusValues(returned="Returned to store")
    doc = {"_id": ObjectId(), "order_status": "Returned to store"}
    assert records.parse_order(doc, custom).is_returned
    assert not records.parse_order(doc).is_returned


#: The opening words of every tracking_info text on the platform database, 15 Oct 2026.
REAL_HISTORY = {
    "Order created by Arun kuamr": "created", "Order Accepted By Seller": "accepted", "Confirmed by buyer": "confirmed",
    "Shipped by seller": "shipped", "Payment Completed": "payment", "Delivered (Urban Vogue Fashion Studio)": "delivered",
    "Return requested (RET-115A15BF)": "return_request", "Refund of \u20b96099 initiated": "refund",
    "Returned to seller": "returned", "Cancelled by seller": "cancelled",
}


def test_history_every_text_on_the_platform_maps() -> None:
    """ENG-30 check: every tracking_info text in the data maps (whole words, any case)."""
    from reco.config.tunables import TRACKING_STAGES

    assert {text: records.tracking_stage(text, TRACKING_STAGES) for text in REAL_HISTORY} == REAL_HISTORY
    assert records.tracking_stage("DELIVERED", TRACKING_STAGES) == "delivered"
    assert records.tracking_stage("Deliveredx today", TRACKING_STAGES) is None  # whole words only


def test_history_an_unknown_text_is_reported_not_guessed() -> None:
    doc = {"_id": ObjectId(), "order_status": "Delivered",
           "tracking_info": [{"status": "Delivered", "timestamp": T}, {"status": "Parcel lost in transit", "timestamp": T}]}
    order = records.parse_order(doc)
    assert order.history_unmatched == ["Parcel lost in transit"] and order.tracking[-1].stage is None


@pytest.mark.parametrize("text", ["Payment Completed", "Return requested (RET-1)", "Refund of \u20b9100"])
def test_history_payment_request_and_refund_leave_the_state(text: str) -> None:
    """ENG-30 point 5: a history event never changes the order's state."""
    doc = {"_id": ObjectId(), "order_status": "Delivered",
           "tracking_info": [{"status": "Delivered", "timestamp": T}, {"status": text, "timestamp": T + timedelta(hours=1)}]}
    order = records.parse_order(doc)
    assert order.status == "Delivered" and not order.is_returned and not order.is_reversed


def test_history_that_contradicts_itself_is_flagged() -> None:
    after = {"_id": ObjectId(), "order_status": "Returned", "tracking_info": [
        {"status": "Delivered", "timestamp": T}, {"status": "Returned to seller", "timestamp": T + timedelta(days=1)},
        {"status": "Delivered", "timestamp": T + timedelta(days=2)}]}
    missing = {"_id": ObjectId(), "order_status": "Delivered", "tracking_info": [{"status": "Order created by A", "timestamp": T}]}
    fine = {"_id": ObjectId(), "order_status": "Delivered", "tracking_info": [{"status": "Delivered", "timestamp": T}]}
    assert records.parse_order(after).history_conflict and records.parse_order(missing).history_conflict
    assert not records.parse_order(fine).history_conflict


def test_cart_line_carries_the_first_list() -> None:
    doc = {"_id": ObjectId(), "user_id": UID, "userModel": "user", "product_id": PRODUCT, "quantity": 2,
           "ml": {"request_id": "req_abc", "position": 3, "surface": "home_for_you"}, "timestamp": T}
    line = records.parse_cart_line(doc)
    assert line.request_id == "req_abc" and line.actor == "user" and line.quantity == 2


def test_served_list_fallback_is_any_policy_not_starting_with_cfg() -> None:
    doc = {"_id": ObjectId(), "request_id": "req_d7c99e1dbc10", "surface": "home_for_you", "user_id": BIZ,
           "userModel": "businessRegister", "policy_id": "wave1a_v1", "candidate_ids": [str(PID)], "server_ts": T}
    served = records.parse_served_list(doc)

    assert served.is_fallback and served.surface == "feed" and served.actor == "business"
    assert not records.parse_served_list({**doc, "policy_id": "cfg2.interest-1"}).is_fallback


def test_post_compliance_and_categories() -> None:
    doc = {"_id": PID, "userId": str(UID), "timestamp": T, "categories": ["fashion & apparel", "Menswear"],
           "compliance": {"status": "deranked"}, "visibility": "public", "isHidden": False, "feedScore": 9}
    post = records.parse_post(doc, VOCAB)
    assert post.compliance_status == "deranked" and post.categories == ["Fashion & Apparel"]
    assert "feedScore" not in post.model_dump()


def test_product_category_from_category_path_ids_and_the_tree() -> None:
    top = {"_id": CATEGORY, "name": "Fashion & Apparel", "level": 0, "path": ["Fashion & Apparel"]}
    index = ProductCategoryIndex.build(VOCAB, [top])
    product = records.parse_product({"_id": PRODUCT, "status": "Activate", "availability": {"inStock": True},
                                     "categoryPathIds": [CATEGORY, ObjectId()], "createdBy": UID}, index)
    legacy = records.parse_product({"_id": ObjectId(), "basicInfo": {"categoryId": CATEGORY}}, index)

    assert product.category == "Fashion & Apparel" and product.is_active and product.in_stock
    assert legacy.category == "Fashion & Apparel"  # no categoryPathIds yet: basicInfo.categoryId


def test_variant() -> None:
    variant = records.parse_variant({"_id": ObjectId(), "productId": PRODUCT, "salePrice": 1099,
                                     "originalPrice": 1499, "quantity": 5, "reservedStock": 2, "status": "active"})
    assert (variant.price, variant.stock, variant.is_active) == (1099.0, 3.0, True)


def test_every_record_kind_has_a_parser_and_a_collection() -> None:
    for kind in records.RECORD_KINDS:
        assert hasattr(records, f"parse_{kind}"), kind
        assert kind in PLATFORM_COLLECTIONS, kind


def test_platform_collections_are_exactly_db_02s_read_list() -> None:
    """DB-02 (v1.3 Waits sheet; DS-017 v2.5 section 7): the login can read only these."""
    assert set(PLATFORM_COLLECTIONS.values()) == {
        "postevents", "orders", "recommendationrequests", "rec_serve_log", "posts", "users", "businessregisters",
        "products", "productvariants", "categories", "follows", "followers", "carts"}


# --- one source per kind of data; no event source switch -----------------------------------


@pytest.mark.parametrize(
    "kind,source",
    [("event", "ml_events"), ("served_list", "ml_events"), ("order", "ml_orders"), ("return", "ml_orders"),
     ("follow_graph", "follow"), ("block", "follower"), ("eligibility_state", "ml_item_state")],
)
def test_each_kind_has_exactly_one_source(kind: str, source: str) -> None:
    assert sources.source_of(kind) == source


def test_there_is_no_event_source_switch() -> None:
    assert not hasattr(sources, "spans") and not hasattr(sources, "SWITCHED")


# --- ignored platform data ---------------------------------------------------------------


def _code_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


@pytest.mark.parametrize("name", sorted(IGNORED_PLATFORM_DATA))
def test_ignored_platform_data_is_not_read(name: str) -> None:
    package = Path(records.__file__).resolve().parents[1]
    allowed = {"config"} | ({"fallback"} if name == "interestScores" else set())
    offenders = [
        f"{path.relative_to(package)}:{line}"
        for path in package.rglob("*.py")
        if path.relative_to(package).parts[0] not in allowed
        for line, value in _code_strings(path)
        if value == name or value.endswith("." + name)
    ]
    assert not offenders, f"{name} is read at {offenders} ({IGNORED_PLATFORM_DATA[name]})"


# --- the reader, against a throwaway database -------------------------------------------


@pytest.fixture
async def platform_copy(settings):
    from reco.platform import connection as platform_conn
    from reco.store import connection as store_conn

    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    seed = store_conn._client[settings.app_mongo_db]  # the throwaway test copy, never SOCO's
    touched = [PLATFORM_COLLECTIONS[k] for k in ("follow", "category", "product", "order")]
    for name in touched:
        await seed[name].drop()
    try:
        yield seed
    finally:
        for name in touched:
            await seed[name].drop()
        await platform_conn.close_client()
        await store_conn.close_client()


@pytest.mark.mongo
async def test_read_records_parses_what_it_reads(settings, platform_copy) -> None:
    from reco.platform.fetch import read_records

    await platform_copy[PLATFORM_COLLECTIONS["follow"]].insert_one(
        {"userId": str(UID), "followingId": str(BIZ), "followingReference": "User", "createdAt": T})
    await platform_copy[PLATFORM_COLLECTIONS["category"]].insert_one(
        {"_id": CATEGORY, "name": "Shoes & Footwear", "path": ["Shoes & Footwear"], "level": 0})
    await platform_copy[PLATFORM_COLLECTIONS["product"]].insert_one(
        {"_id": PRODUCT, "status": "Activate", "availability": {"inStock": True}, "categoryPathIds": [CATEGORY]})
    await platform_copy[PLATFORM_COLLECTIONS["order"]].insert_one(
        {"_id": ObjectId(), "order_status": "Returned", "tracking_info": [{"status": "Returned", "timestamp": T}]})

    [follow] = await read_records(settings, "follow")
    [product] = await read_records(settings, "product")
    [order] = await read_records(settings, "order")

    assert follow.followed_kind == "user" and product.category == "Shoes & Footwear" and order.is_returned
