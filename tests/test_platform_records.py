"""ENG-03: read platform data correctly.

The Build List check: "Unit tests read one of each record type and return the
expected values, including a follows record with text ids." The documents below
copy the shapes found on the platform database on 29 Sep 2026.
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from bson import ObjectId

from reco.config import IGNORED_PLATFORM_DATA, PLATFORM_COLLECTIONS
from reco.platform import records, sources
from reco.platform.categories import CategoryVocabulary, ProductCategoryIndex, canonical_name
from reco.platform.ids import time_of

VOCAB = CategoryVocabulary(
    canonical=["Fashion & Apparel", "Electronics", "Home & Living", "Shoes & Footwear"],
    # Even with a legacy entry present, ENG-03 matches by name only.
    legacy_map={"Fashion": "Fashion & Apparel"},
)
UTC = timezone.utc
T = datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
UID = ObjectId("6a3a6df8bac0b9eb430edc7c")
PID = ObjectId("6a5a7b814834d0026569a2d1")
PRODUCT = ObjectId("6a5a79b94834d0026569a19f")
CATEGORY = ObjectId("6ab48d468844dddd68a1223e")


# --- helpers -------------------------------------------------------------------------


def test_time_comes_from_the_field_when_present() -> None:
    assert time_of({"_id": ObjectId(), "created_at": T}, "created_at") == T


def test_a_missing_time_is_read_from_the_id() -> None:
    oid = ObjectId.from_datetime(T)
    assert time_of({"_id": oid}, "created_at") == T
    assert time_of({"_id": str(oid)}, "created_at") == T  # text _id too


def test_a_naive_time_is_taken_as_utc() -> None:
    assert time_of({"created_at": datetime(2026, 9, 20, 10, 30)}, "created_at") == T


@pytest.mark.parametrize("stored", ["Activate", "activate", " ACTIVATE "])
def test_status_is_compared_ignoring_case(stored: str) -> None:
    assert records.status_is(stored, "activate")


def test_different_status_words_stay_different() -> None:
    """products.status 'Activate' vs posts.Product_status 'Activated' (ENG-03)."""
    assert not records.status_is("Activated", "activate")


def test_categories_match_by_name_only() -> None:
    assert canonical_name(VOCAB, "  fashion  &  APPAREL ") == "Fashion & Apparel"
    assert canonical_name(VOCAB, "Fashion") is None  # not one of the 23 by name: dropped


# --- one of each record type ------------------------------------------------------


def test_user() -> None:
    doc = {
        "_id": UID, "status": "Active", "city": "Chennai", "DOB": "2001-04-12",
        "accountIsPublic": True, "interest": ["Fashion & Apparel", "Cricket"],
        "addNew_Interest": ["ignored"], "interestScores": {"ignored": 99},
        "password": "never-read", "timestamp": T,
    }
    user = records.parse_user(doc, VOCAB)

    assert user.user_id == "6a3a6df8bac0b9eb430edc7c"
    assert user.is_active and user.city == "Chennai"
    assert user.date_of_birth == date(2001, 4, 12)
    assert user.account_is_public
    assert user.declared_interests == ["Fashion & Apparel"]  # "Cricket" dropped
    assert user.created_at == T
    assert "password" not in user.model_dump()


def test_business() -> None:
    doc = {
        "_id": ObjectId(), "user_id": "6a3a6df8bac0b9eb430edc7c", "category": "electronics",
        "status": "Inactive", "accountIsPublic": False, "timestamp": T,
    }
    business = records.parse_business(doc, VOCAB)

    assert business.owner_user_id == "6a3a6df8bac0b9eb430edc7c"
    assert business.category == "Electronics" and business.category_supplied == "electronics"
    assert not business.is_active and not business.account_is_public


def test_follow_with_text_ids() -> None:
    """The record the Build List's check names: follows stores ids as text."""
    doc = {
        "_id": ObjectId(), "userId": "6a3a6df8bac0b9eb430edc7c",
        "followingId": "6a5a78e94834d0026569a0e9", "userReference": "User",
        "followingReference": "businessRegister", "createdAt": T,
    }
    follow = records.parse_follow(doc)

    assert follow.follower_id == "6a3a6df8bac0b9eb430edc7c"
    assert follow.followed_id == "6a5a78e94834d0026569a0e9"
    assert follow.followed_kind == "business"
    assert follow.created_at == T


def test_follow_with_objectid_ids_reads_the_same() -> None:
    doc = {"_id": ObjectId(), "userId": UID, "followingId": PID, "followingReference": "User"}
    follow = records.parse_follow(doc)

    assert (follow.follower_id, follow.followed_kind) == ("6a3a6df8bac0b9eb430edc7c", "user")


@pytest.mark.parametrize("author", ["6a3a6df8bac0b9eb430edc7c", UID])
def test_post(author) -> None:
    """posts.userId is text on some documents and ObjectId on others."""
    doc = {
        "_id": PID, "userId": author, "timestamp": T, "categories": ["fashion & apparel", "Menswear"],
        "postType": "product", "isHidden": False, "visibility": "public", "Product_status": "Activated",
        "ageGroup": "All", "isRepost": False, "feedScore": 999, "productId": PRODUCT, "products": [],
    }
    post = records.parse_post(doc, VOCAB)

    assert post.author_id == "6a3a6df8bac0b9eb430edc7c"
    assert post.created_at == T
    assert post.categories == ["Fashion & Apparel"] and post.categories_dropped == ["Menswear"]
    assert (post.post_type, post.visibility, post.product_status) == ("product", "public", "Activated")
    assert post.product_ids == [str(PRODUCT)]
    assert "feedScore" not in post.model_dump()


def test_post_with_no_time_reads_it_from_the_id() -> None:
    oid = ObjectId.from_datetime(T)
    post = records.parse_post({"_id": oid, "userId": UID, "categories": []}, VOCAB)
    assert post.created_at == T


def test_postevent() -> None:
    doc = {
        "_id": ObjectId(), "post_id": PID, "user_id": UID, "event_type": "View",
        "view_duration_seconds": 4.5, "product_id": None, "created_at": T,
    }
    event = records.parse_postevent(doc)

    assert (event.user_id, event.post_id) == (str(UID), str(PID))
    assert event.event_type == "view" and event.view_duration_seconds == 4.5
    assert event.created_at == T and event.product_id is None


def test_order() -> None:
    doc = {
        "_id": ObjectId(), "user_id": UID, "seller_id": ObjectId(), "product_id": PRODUCT, "post_id": PID,
        "checkout_id": "58e9b6b2-762a-48db-b013-67449ba06fa5", "total_price": 2299, "quantity": 1,
        "order_status": "Rejected", "isIncognitoMode": False, "return_type": "No Return",
        "reason_code": "out_of_stock", "created_at": T,
    }
    order = records.parse_order(doc)

    assert order.value == 2299.0  # total_price, not totalAmount
    assert order.status == "Rejected" and order.created_at == T
    assert order.checkout_id == "58e9b6b2-762a-48db-b013-67449ba06fa5"
    assert order.return_type is None  # "No Return" is not a return
    assert not order.return_requested and not order.is_incognito
    assert order.reason_code == "out_of_stock"


def test_cart_line() -> None:
    doc = {"_id": ObjectId(), "user_id": UID, "product_id": PRODUCT, "variant_id": ObjectId(),
           "post_id": PID, "quantity": 2, "timestamp": T}
    line = records.parse_cart_line(doc)

    assert line.product_id == str(PRODUCT) and line.quantity == 2
    assert line.request_id is None  # DB-05 not built yet
    assert line.added_at == T


def test_category_and_product_via_the_tree() -> None:
    """A product maps through basicInfo.categoryId to the first name in the category's path."""
    category_doc = {"_id": CATEGORY, "name": "Shirts", "level": 1, "parent": ObjectId(),
                    "path": ["Fashion & Apparel", "Shirts"]}
    unmapped_doc = {"_id": ObjectId(), "name": "Shirts", "level": 1, "path": ["Menswear", "Shirts"]}
    index = ProductCategoryIndex.build(VOCAB, [category_doc, unmapped_doc])

    category = records.parse_category(category_doc, VOCAB)
    assert category.top_level == "Fashion & Apparel" and category.level == 1

    product = records.parse_product(
        {"_id": PRODUCT, "createdBy": UID, "createdAt": T, "status": "Activate",
         "availability": {"inStock": True}, "basicInfo": {"categoryId": CATEGORY},
         "crossSellProducts": [ObjectId("6ab49026cd852e74c6869e82")]},
        index,
    )
    assert product.seller_id == str(UID) and product.created_at == T
    assert product.is_active and product.in_stock
    assert product.category == "Fashion & Apparel"
    assert product.cross_sell_ids == ["6ab49026cd852e74c6869e82"]

    orphan = records.parse_product(
        {"_id": ObjectId(), "status": "draft", "basicInfo": {"categoryId": unmapped_doc["_id"]}}, index
    )
    assert orphan.category is None and not orphan.is_active and not orphan.in_stock


def test_variant() -> None:
    doc = {"_id": ObjectId(), "productId": PRODUCT, "sellerId": UID, "salePrice": 1099,
           "originalPrice": 1499, "quantity": 5, "reservedStock": 2, "status": "active"}
    variant = records.parse_variant(doc)

    assert (variant.price, variant.list_price) == (1099.0, 1499.0)
    assert variant.stock == 3.0  # quantity - reservedStock
    assert variant.is_active and variant.product_id == str(PRODUCT)


def test_legacy_request_impression_click_and_feedback() -> None:
    request = records.parse_legacy_request(
        {"_id": ObjectId(), "request_id": "r1", "surface": "feed", "user_id": UID,
         "policy_id": "wave1a_v1", "candidate_ids": [str(PID)], "server_ts": T})
    impression = records.parse_legacy_impression(
        {"_id": ObjectId(), "request_id": "r1", "item_id": PID, "item_type": "post", "position": 1,
         "dwell_ms": 2400, "is_exploration": False, "user_id": UID, "server_ts": T})
    click = records.parse_legacy_click(
        {"_id": ObjectId(), "request_id": "r1", "item_id": PID, "item_type": "post", "position": 1,
         "user_id": UID, "server_ts": T})
    feedback = records.parse_legacy_content_feedback(
        {"_id": ObjectId(), "user_id": UID, "target_id": PID, "target_type": "post",
         "feedback_type": "Not_Interested", "request_id": None, "server_ts": T})

    assert request.candidate_ids == [str(PID)] and request.at == T
    assert (impression.position, impression.dwell_ms, impression.item_id) == (1, 2400.0, str(PID))
    assert click.request_id == "r1" and click.at == T
    assert feedback.feedback_type == "not_interested" and feedback.request_id is None


def test_every_record_kind_has_a_parser_and_a_collection() -> None:
    for kind in records.RECORD_KINDS:
        assert hasattr(records, f"parse_{kind}"), kind
        assert kind in PLATFORM_COLLECTIONS, kind


# --- one source per kind of data, and the switch --------------------------------------


@pytest.mark.parametrize(
    "kind,source",
    [("order", "order"), ("return", "order"), ("cancellation", "order"), ("view", "postevent"),
     ("like", "postevent"), ("post_add_to_cart", "postevent"), ("follow", "follow"),
     ("add_to_cart_with_list", "ml_events")],
)
def test_each_kind_has_exactly_one_source(kind: str, source: str) -> None:
    assert sources.source_of(kind) == source


@pytest.mark.parametrize("kind", ["order_placed", "order_state_changed", "social_interaction"])
def test_stored_events_are_not_read_in_wave_1a(kind: str) -> None:
    with pytest.raises(ValueError, match="not read in Wave 1A"):
        sources.source_of(kind)


SWITCH = date(2026, 10, 10)


@pytest.mark.parametrize("kind", ["request", "impression", "click", "content_feedback"])
def test_switched_kinds_read_old_collections_before_the_switch_and_ml_events_from_it(kind: str) -> None:
    assert sources.source_of(kind, date(2026, 10, 9), SWITCH) == "legacy"
    assert sources.source_of(kind, SWITCH, SWITCH) == "ml_events"
    assert sources.source_of(kind, date(2026, 12, 1), None) == "legacy"  # no switch date yet


def test_a_window_across_the_switch_reads_each_part_from_one_source() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = start + timedelta(days=90)
    parts = sources.spans(start, end, SWITCH)

    assert [p.source for p in parts] == ["legacy", "ml_events"]
    assert parts[0].start == start and parts[-1].end == end
    assert parts[0].end == parts[1].start == datetime(2026, 10, 10, tzinfo=UTC)  # no gap, no overlap


def test_with_no_switch_date_everything_is_old_collections() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    assert [p.source for p in sources.spans(start, start + timedelta(days=30), None)] == ["legacy"]


# --- ignored platform data --------------------------------------------------------------


def _code_strings(path: Path) -> list[tuple[int, str]]:
    """String values used in code: docstrings and comments don't count."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


@pytest.mark.parametrize("name", sorted(IGNORED_PLATFORM_DATA))
def test_ignored_platform_data_is_not_read(name: str) -> None:
    """ENG-03 'Ignored': addNew_Interest, userevents and feedScore never;
    interestScores only in the fallback ladder (the old delivered score)."""
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


# --- the readers, against a throwaway database ----------------------------------------


@pytest.fixture
async def platform_copy(settings):
    """Seeded copies of platform collections in the test databases. Never SOCO's."""
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

    # Seed through the engine client: the test platform database lives on the same
    # throwaway cluster, and the platform connection itself is read-only by design.
    seed = store_conn._client[settings.app_mongo_db]
    engine = store_conn.ml_db(settings)
    touched = [PLATFORM_COLLECTIONS[k] for k in ("follow", "category", "product", "legacy_click")]
    for name in touched:
        await seed[name].drop()
    await engine["ml_events"].delete_many({"event_name": "recommendation_click", "request_id": {"$regex": "^eng03-"}})
    try:
        yield seed, engine
    finally:
        for name in touched:
            await seed[name].drop()
        await engine["ml_events"].delete_many({"request_id": {"$regex": "^eng03-"}})
        await platform_conn.close_client()
        await store_conn.close_client()


@pytest.mark.mongo
async def test_read_records_parses_what_it_reads(settings, platform_copy) -> None:
    from reco.platform.fetch import read_records

    seed, _ = platform_copy
    await seed[PLATFORM_COLLECTIONS["follow"]].insert_one(
        {"userId": "6a3a6df8bac0b9eb430edc7c", "followingId": "6a5a78e94834d0026569a0e9",
         "followingReference": "User", "createdAt": T})
    await seed[PLATFORM_COLLECTIONS["category"]].insert_one(
        {"_id": CATEGORY, "name": "Shirts", "path": ["Fashion & Apparel", "Shirts"], "level": 1})
    await seed[PLATFORM_COLLECTIONS["product"]].insert_one(
        {"_id": PRODUCT, "status": "Activate", "availability": {"inStock": True},
         "basicInfo": {"categoryId": CATEGORY}, "createdBy": UID})

    [follow] = await read_records(settings, "follow")
    [product] = await read_records(settings, "product")

    assert follow.follower_id == "6a3a6df8bac0b9eb430edc7c" and follow.followed_kind == "user"
    assert product.category == "Fashion & Apparel"  # through the categories tree


@pytest.mark.mongo
async def test_read_switched_reads_each_day_from_exactly_one_source(settings, platform_copy) -> None:
    """A click on each side of the switch date, stored in BOTH places: each is read once."""
    from reco.platform.fetch import read_switched

    seed, engine = platform_copy
    before, after = datetime(2026, 10, 9, 12, tzinfo=UTC), datetime(2026, 10, 11, 12, tzinfo=UTC)
    for when, rid in ((before, "eng03-before"), (after, "eng03-after")):
        row = {"request_id": rid, "item_id": PID, "item_type": "post", "position": 1,
               "user_id": UID, "server_ts": when}
        await seed[PLATFORM_COLLECTIONS["legacy_click"]].insert_one(dict(row))
        await engine["ml_events"].insert_one({**row, "event_id": rid, "event_name": "recommendation_click"})

    clicks = await read_switched(
        settings, "click", datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC), SWITCH
    )

    assert sorted(c.request_id for c in clicks) == ["eng03-after", "eng03-before"]  # no double count
