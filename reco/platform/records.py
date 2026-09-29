"""Platform records, read correctly. ENG-03.

One parse function per record kind turns a raw platform document into a clean,
typed record. Every rule ENG-03 sets is applied here, once, so no model ever
reads a raw platform field:

  - IDs: every id becomes its 24-character text form, whichever way it is stored
    (follows and posts.userId hold text; users, postevents, orders and products
    hold ObjectIds).
  - Field names: the ENG-03 field map -- order value orders.total_price, order
    time orders.created_at, post time posts.timestamp, product time
    products.createdAt, event time postevents.created_at, price
    productvariants.salePrice (originalPrice is the list price), stock
    quantity - reservedStock, seller products.createdBy, and so on. A missing
    time is read from the record's _id.
  - Categories: a post's categories matched by name to the 23; a product's
    through the categories tree (ProductCategoryIndex). Unmapped ones dropped.
  - Status fields: compared ignoring case (status_is).

Parsing is pure -- no database -- so every rule is testable on a dict. The async
readers in reco.platform.fetch apply these to documents read from the platform.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from reco.platform.categories import (
    CategoryVocabulary,
    ProductCategoryIndex,
    canonical_name,
    post_categories,
)
from reco.platform.ids import as_utc, maybe_str, time_of, to_str


def status_is(value: Any, expected: str) -> bool:
    """ENG-03: status fields are compared ignoring case (and surrounding spaces).

    'Activate', 'activate ' and 'ACTIVATE' are one value. Different words stay
    different: products.status 'Activate' and posts.Product_status 'Activated'
    are each compared with their own expected value.
    """
    return isinstance(value, str) and value.strip().lower() == expected.strip().lower()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _date(value: Any) -> date | None:
    """users.DOB is stored as text; accept ISO dates and d-m-Y / d/m/Y."""
    parsed = as_utc(value)
    if parsed is not None:
        return parsed.date()
    if isinstance(value, str):
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [text for text in (maybe_str(v) for v in values if not isinstance(v, dict)) if text]


class _Record(BaseModel):
    model_config = {"frozen": True}


# --- people -----------------------------------------------------------------------


class UserRecord(_Record):
    user_id: str
    status: str | None
    is_active: bool  # users.status, ignoring case (E-08)
    city: str | None  # users.city
    date_of_birth: date | None  # users.DOB (E-11)
    account_is_public: bool  # accountIsPublic (E-05)
    declared_interests: list[str]  # users.interest, matched to the 23
    created_at: datetime | None  # users.timestamp, else _id


def parse_user(doc: dict[str, Any], vocabulary: CategoryVocabulary) -> UserRecord:
    return UserRecord(
        user_id=to_str(doc["_id"]),
        status=doc.get("status"),
        is_active=status_is(doc.get("status"), "active"),
        city=doc.get("city") or None,
        date_of_birth=_date(doc.get("DOB")),
        account_is_public=doc.get("accountIsPublic") is not False,
        declared_interests=post_categories(vocabulary, doc.get("interest")).resolved,
        created_at=time_of(doc, "timestamp"),
    )


class BusinessRecord(_Record):
    business_id: str
    owner_user_id: str | None
    category: str | None  # businessregisters.category, matched to the 23
    category_supplied: str | None
    status: str | None
    is_active: bool
    account_is_public: bool
    created_at: datetime | None


def parse_business(doc: dict[str, Any], vocabulary: CategoryVocabulary) -> BusinessRecord:
    return BusinessRecord(
        business_id=to_str(doc["_id"]),
        owner_user_id=maybe_str(doc.get("user_id")),
        category=canonical_name(vocabulary, doc.get("category")),
        category_supplied=doc.get("category"),
        status=doc.get("status"),
        is_active=status_is(doc.get("status"), "active"),
        account_is_public=doc.get("accountIsPublic") is not False,
        created_at=time_of(doc, "timestamp"),
    )


class FollowRecord(_Record):
    follower_id: str  # follows.userId (text)
    followed_id: str  # follows.followingId (text)
    followed_kind: Literal["user", "business", "unknown"]  # followingReference
    created_at: datetime | None  # follows.createdAt, else _id


def parse_follow(doc: dict[str, Any]) -> FollowRecord:
    reference = str(doc.get("followingReference") or "").strip().lower()
    kind = "user" if reference == "user" else "business" if reference == "businessregister" else "unknown"
    return FollowRecord(
        follower_id=to_str(doc["userId"]),
        followed_id=to_str(doc["followingId"]),
        followed_kind=kind,
        created_at=time_of(doc, "createdAt"),
    )


# --- content and activity ------------------------------------------------------------


class PostRecord(_Record):
    post_id: str
    author_id: str  # posts.userId (text or ObjectId)
    created_at: datetime | None  # posts.timestamp, else _id
    categories: list[str]  # matched by name to the 23
    categories_dropped: list[str]
    post_type: str | None  # posts.postType
    post_type_detailed: str | None  # posts.postTypeDetailed, where it exists
    is_hidden: bool  # E-04
    visibility: str | None  # E-04: must be 'public'
    product_status: str | None  # posts.Product_status (E-06)
    age_group: str | None  # posts.ageGroup (E-11)
    is_repost: bool
    product_ids: list[str]


def parse_post(doc: dict[str, Any], vocabulary: CategoryVocabulary) -> PostRecord:
    categories = post_categories(vocabulary, doc.get("categories"))
    product_ids = _ids(doc.get("products"))
    if doc.get("productId") and maybe_str(doc.get("productId")) not in product_ids:
        product_ids.insert(0, maybe_str(doc.get("productId")))
    return PostRecord(
        post_id=to_str(doc["_id"]),
        author_id=to_str(doc["userId"]),
        created_at=time_of(doc, "timestamp"),
        categories=categories.resolved,
        categories_dropped=categories.dropped,
        post_type=doc.get("postType"),
        post_type_detailed=doc.get("postTypeDetailed"),
        is_hidden=bool(doc.get("isHidden")),
        visibility=doc.get("visibility"),
        product_status=doc.get("Product_status"),
        age_group=doc.get("ageGroup"),
        is_repost=bool(doc.get("isRepost")),
        product_ids=product_ids,
    )


class PostEventRecord(_Record):
    event_id: str
    user_id: str | None
    post_id: str | None
    event_type: str | None  # postevents.event_type, lower case
    created_at: datetime | None  # postevents.created_at, else _id
    view_duration_seconds: float | None
    product_id: str | None
    order_id: str | None


def parse_postevent(doc: dict[str, Any]) -> PostEventRecord:
    event_type = doc.get("event_type")
    return PostEventRecord(
        event_id=to_str(doc["_id"]),
        user_id=maybe_str(doc.get("user_id")),
        post_id=maybe_str(doc.get("post_id")),
        event_type=event_type.strip().lower() if isinstance(event_type, str) else None,
        created_at=time_of(doc, "created_at"),
        view_duration_seconds=_number(doc.get("view_duration_seconds")),
        product_id=maybe_str(doc.get("product_id")),
        order_id=maybe_str(doc.get("order_id")),
    )


# --- commerce ---------------------------------------------------------------------


class OrderRecord(_Record):
    order_id: str
    buyer_id: str | None
    seller_id: str | None
    product_id: str | None
    post_id: str | None
    promoter_id: str | None
    checkout_id: str | None
    request_id: str | None
    value: float | None  # orders.total_price (not totalAmount)
    quantity: float | None
    status: str | None  # orders.order_status: the only status the engine reads
    created_at: datetime | None  # orders.created_at, else _id
    is_incognito: bool  # orders.isIncognitoMode
    return_requested: bool
    return_requested_at: datetime | None
    return_type: str | None  # null when there is no return ('No Return' is not a return)
    reason_code: str | None
    cancelled_by: str | None


def parse_order(doc: dict[str, Any]) -> OrderRecord:
    return_type = doc.get("return_type")
    if isinstance(return_type, str) and return_type.strip().lower() in {"no return", "no returns", ""}:
        return_type = None
    return OrderRecord(
        order_id=to_str(doc["_id"]),
        buyer_id=maybe_str(doc.get("user_id")),
        seller_id=maybe_str(doc.get("seller_id")),
        product_id=maybe_str(doc.get("product_id")),
        post_id=maybe_str(doc.get("post_id")),
        promoter_id=maybe_str(doc.get("promoter_id")),
        checkout_id=doc.get("checkout_id") or None,
        request_id=doc.get("request_id") or None,
        value=_number(doc.get("total_price")),
        quantity=_number(doc.get("quantity")),
        status=doc.get("order_status"),
        created_at=time_of(doc, "created_at"),
        is_incognito=bool(doc.get("isIncognitoMode")),
        return_requested=bool(doc.get("return_requested")),
        return_requested_at=as_utc(doc.get("return_requested_at")),
        return_type=return_type,
        reason_code=doc.get("reason_code") or None,
        cancelled_by=doc.get("cancelled_by") or None,
    )


class CartLineRecord(_Record):
    user_id: str | None
    product_id: str | None
    variant_id: str | None
    post_id: str | None
    quantity: float | None
    request_id: str | None  # DB-05: empty until built, and when not reached from a list
    added_at: datetime | None  # carts.timestamp, else _id


def parse_cart_line(doc: dict[str, Any]) -> CartLineRecord:
    return CartLineRecord(
        user_id=maybe_str(doc.get("user_id")),
        product_id=maybe_str(doc.get("product_id")),
        variant_id=maybe_str(doc.get("variant_id")),
        post_id=maybe_str(doc.get("post_id")),
        quantity=_number(doc.get("quantity")),
        request_id=doc.get("request_id") or None,
        added_at=time_of(doc, "timestamp"),
    )


class ProductRecord(_Record):
    product_id: str
    seller_id: str | None  # products.createdBy
    created_at: datetime | None  # products.createdAt, else _id
    status: str | None
    is_active: bool  # products.status 'Activate', ignoring case (E-07)
    in_stock: bool  # availability.inStock
    category_id: str | None  # basicInfo.categoryId
    category: str | None  # its top name, if one of the 23
    cross_sell_ids: list[str]


def parse_product(doc: dict[str, Any], categories: ProductCategoryIndex) -> ProductRecord:
    basic = doc.get("basicInfo") if isinstance(doc.get("basicInfo"), dict) else {}
    availability = doc.get("availability") if isinstance(doc.get("availability"), dict) else {}
    category_id = maybe_str(basic.get("categoryId"))
    return ProductRecord(
        product_id=to_str(doc["_id"]),
        seller_id=maybe_str(doc.get("createdBy")),
        created_at=time_of(doc, "createdAt"),
        status=doc.get("status"),
        is_active=status_is(doc.get("status"), "activate"),
        in_stock=availability.get("inStock") is True,
        category_id=category_id,
        category=categories.category_of(category_id),
        cross_sell_ids=_ids(doc.get("crossSellProducts")),
    )


class VariantRecord(_Record):
    variant_id: str
    product_id: str | None
    seller_id: str | None  # productvariants.sellerId
    price: float | None  # productvariants.salePrice
    list_price: float | None  # productvariants.originalPrice
    stock: float | None  # quantity - reservedStock
    status: str | None
    is_active: bool


def parse_variant(doc: dict[str, Any]) -> VariantRecord:
    quantity = _number(doc.get("quantity"))
    reserved = _number(doc.get("reservedStock")) or 0.0
    return VariantRecord(
        variant_id=to_str(doc["_id"]),
        product_id=maybe_str(doc.get("productId")),
        seller_id=maybe_str(doc.get("sellerId")),
        price=_number(doc.get("salePrice")),
        list_price=_number(doc.get("originalPrice")),
        stock=None if quantity is None else quantity - reserved,
        status=doc.get("status"),
        is_active=status_is(doc.get("status"), "active"),
    )


class CategoryRecord(_Record):
    category_id: str
    name: str | None
    level: int | None
    path: list[str]
    parent_id: str | None
    top_level: str | None  # the first name in its path, if one of the 23


def parse_category(doc: dict[str, Any], vocabulary: CategoryVocabulary) -> CategoryRecord:
    path = [p for p in doc.get("path") or [] if isinstance(p, str)]
    level = doc.get("level")
    return CategoryRecord(
        category_id=to_str(doc["_id"]),
        name=doc.get("name"),
        level=level if isinstance(level, int) else None,
        path=path,
        parent_id=maybe_str(doc.get("parent")),
        top_level=canonical_name(vocabulary, path[0] if path else doc.get("name")),
    )


# --- the old recommendation event collections (read before the switch date) ---------


class LegacyRequestRecord(_Record):
    request_id: str | None
    user_id: str | None
    surface: str | None
    policy_id: str | None
    candidate_ids: list[str]
    at: datetime | None  # server_ts, else _id


def parse_legacy_request(doc: dict[str, Any]) -> LegacyRequestRecord:
    return LegacyRequestRecord(
        request_id=doc.get("request_id") or None,
        user_id=maybe_str(doc.get("user_id")),
        surface=doc.get("surface"),
        policy_id=doc.get("policy_id"),
        candidate_ids=_ids(doc.get("candidate_ids")),
        at=time_of(doc, "server_ts"),
    )


class LegacyImpressionRecord(_Record):
    request_id: str | None
    user_id: str | None
    item_id: str | None
    item_type: str | None
    position: int | None
    dwell_ms: float | None
    is_exploration: bool
    at: datetime | None  # server_ts, else _id


def parse_legacy_impression(doc: dict[str, Any]) -> LegacyImpressionRecord:
    position = doc.get("position")
    return LegacyImpressionRecord(
        request_id=doc.get("request_id") or None,
        user_id=maybe_str(doc.get("user_id")),
        item_id=maybe_str(doc.get("item_id")),
        item_type=doc.get("item_type"),
        position=position if isinstance(position, int) else None,
        dwell_ms=_number(doc.get("dwell_ms")),
        is_exploration=bool(doc.get("is_exploration")),
        at=time_of(doc, "server_ts"),
    )


class LegacyClickRecord(_Record):
    request_id: str | None
    user_id: str | None
    item_id: str | None
    item_type: str | None
    position: int | None
    at: datetime | None  # server_ts, else _id


def parse_legacy_click(doc: dict[str, Any]) -> LegacyClickRecord:
    position = doc.get("position")
    return LegacyClickRecord(
        request_id=doc.get("request_id") or None,
        user_id=maybe_str(doc.get("user_id")),
        item_id=maybe_str(doc.get("item_id")),
        item_type=doc.get("item_type"),
        position=position if isinstance(position, int) else None,
        at=time_of(doc, "server_ts"),
    )


class ContentFeedbackRecord(_Record):
    """E13, fields F60 to F65 (Capture Register)."""

    user_id: str | None
    target_id: str | None
    target_type: str | None  # post, product or author
    feedback_type: str | None  # not_interested, hide, report or mute_author
    request_id: str | None
    at: datetime | None  # server_ts, else _id


def parse_legacy_content_feedback(doc: dict[str, Any]) -> ContentFeedbackRecord:
    feedback = doc.get("feedback_type")
    return ContentFeedbackRecord(
        user_id=maybe_str(doc.get("user_id")),
        target_id=maybe_str(doc.get("target_id")),
        target_type=doc.get("target_type"),
        feedback_type=feedback.strip().lower() if isinstance(feedback, str) else None,
        request_id=doc.get("request_id") or None,
        at=time_of(doc, "server_ts"),
    )


#: Every record kind, for the readers and the ENG-03 check.
RECORD_KINDS: tuple[str, ...] = (
    "user", "business", "post", "postevent", "follow", "order", "cart_line",
    "product", "variant", "category",
    "legacy_request", "legacy_impression", "legacy_click", "legacy_content_feedback",
)
