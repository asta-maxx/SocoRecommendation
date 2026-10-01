"""Platform records, read correctly. ENG-03 (Build List v1.3), with ENG-29's adapters where noted.

One parse function per record kind turns a raw platform document into a clean,
typed record. Every rule ENG-03 sets is applied here, once, so no model ever
reads a raw platform field:

  - IDs: every id becomes its 24-character text form, whichever way it is stored.
    Event, request, session and checkout ids are opaque strings, kept as written
    (DS-017 v2.5 section 3). Actors are polymorphic: user_model (postevents) or
    userModel (orders, carts) says whether an id is a user or a businessRegister.
  - Field names (platform schema reference v4): order value orders.total_price,
    order time created_at, change time updated_at, variant orders.variant_id,
    basket orders.checkout_id, order outcome orders.order_status with its
    history in orders.tracking_info (ENG-29: the platform has no statusLog or
    return_info); post time posts.timestamp, compliance posts.compliance.status;
    product time products.createdAt; event time postevents.created_at, change
    time postevents.updated_at, on-screen time postevents.dwell_ms; price
    productvariants.salePrice; stock quantity - reservedStock; seller
    products.createdBy; follows userId -> followingId. A missing time is read
    from the record's _id.
  - Categories: a post's categories matched to the 23; a product's through
    categoryPathIds (or basicInfo.categoryId) and the categories tree. Unmatched
    ones are dropped, never guessed.
  - Status fields: compared ignoring case (status_is).
  - Events: native event types mapped to E codes (reco.platform.native_events).
  - Served item identity: item_id and item_type are the card shown; post_id and
    product_id are kept alongside. On a feed list, item_type product with a post
    id is a post card showing a product.
  - Undo and own posts: undone_at, undo_of and is_self are kept; nothing is
    filtered globally -- each model applies its own rule.
  - Post-page impressions (surface post_detail) are page visits.

Parsing is pure -- no database -- so every rule is testable on a dict. The async
readers are in reco.platform.fetch.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from reco.config import live
from reco.config.tunables import OrderStatusValues
from reco.platform.categories import (
    CategoryVocabulary,
    ProductCategoryIndex,
    canonical_name,
    post_categories,
)
from reco.platform.ids import as_utc, maybe_str, time_of, to_str
from reco.platform.native_events import PAGE_VISIT_SURFACE, engine_surface, native

Actor = Literal["user", "business", "unknown"]


def _spelled(value: str) -> str:
    """ENG-29 item 2: a stored spelling mapped by the settings' status_spellings."""
    key = value.strip().lower()
    return live.current().lists.status_spellings.get(key, key)


def status_is(value: Any, expected: str) -> bool:
    """ENG-03: status fields are compared ignoring case (and surrounding spaces).

    'Activate', 'activate ' and 'ACTIVATE' are one value. Different words stay
    different unless the settings' status spellings map them (ENG-29 item 2:
    {"activated": "activate"} makes 'Activated' read as 'Activate').
    """
    return isinstance(value, str) and isinstance(expected, str) and _spelled(value) == _spelled(expected)


def spellings_of(expected: str) -> list[str]:
    """Every stored spelling that reads as `expected` (for a database filter)."""
    target = _spelled(expected)
    return sorted({target} | {k for k, v in live.current().lists.status_spellings.items() if v == target})


def actor_kind(value: Any) -> Actor:
    """user_model / userModel: which collection an actor id belongs to (F79)."""
    key = str(value or "").strip().lower()
    return "user" if key == "user" else "business" if key == "businessregister" else "unknown"


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


def _opaque(value: Any) -> str | None:
    """An opaque platform string (event, request, session, checkout id): kept as written."""
    if value is None or value == "":
        return None
    return str(value)


class _Record(BaseModel):
    model_config = {"frozen": True}


# --- people ------------------------------------------------------------------------


class UserRecord(_Record):
    user_id: str
    status: str | None
    is_active: bool  # users.status, ignoring case (E-08)
    city: str | None
    date_of_birth: date | None  # users.DOB (E-11)
    account_is_public: bool  # accountIsPublic (E-05)
    restriction_level: str | None  # E-09, once DB-08 adds it
    declared_interests: list[str]  # users.interest, matched to the 23
    created_at: datetime | None


def parse_user(doc: dict[str, Any], vocabulary: CategoryVocabulary, category_map: dict[str, str] | None = None) -> UserRecord:
    return UserRecord(
        user_id=to_str(doc["_id"]),
        status=doc.get("status"),
        is_active=status_is(doc.get("status"), "active"),
        city=doc.get("city") or None,
        date_of_birth=_date(doc.get("DOB")),
        account_is_public=doc.get("accountIsPublic") is not False,
        restriction_level=_lower(doc.get("restriction_level")),
        declared_interests=post_categories(vocabulary, doc.get("interest"), category_map).resolved,
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
    restriction_level: str | None  # E-09, once DB-08 adds it
    created_at: datetime | None


def parse_business(doc: dict[str, Any], vocabulary: CategoryVocabulary, category_map: dict[str, str] | None = None) -> BusinessRecord:
    return BusinessRecord(
        business_id=to_str(doc["_id"]),
        owner_user_id=maybe_str(doc.get("user_id")),
        category=canonical_name(vocabulary, doc.get("category"), category_map),
        category_supplied=doc.get("category"),
        status=doc.get("status"),
        is_active=status_is(doc.get("status"), "active"),
        account_is_public=doc.get("accountIsPublic") is not False,
        restriction_level=_lower(doc.get("restriction_level")),
        created_at=time_of(doc, "timestamp"),
    )


def _lower(value: Any) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


class FollowRecord(_Record):
    follower_id: str  # follows.userId (text)
    followed_id: str  # follows.followingId (text)
    followed_kind: Literal["user", "business", "unknown"]  # followingReference
    created_at: datetime | None


def parse_follow(doc: dict[str, Any]) -> FollowRecord:
    reference = str(doc.get("followingReference") or "").strip().lower()
    kind = "user" if reference == "user" else "business" if reference == "businessregister" else "unknown"
    return FollowRecord(
        follower_id=to_str(doc["userId"]),
        followed_id=to_str(doc["followingId"]),
        followed_kind=kind,
        created_at=time_of(doc, "createdAt"),
    )


# --- content -----------------------------------------------------------------------


class BlockRecord(_Record):
    """A followers row with status blocked (E-01, DB-06: "the existing status blocked in
    followers"). ASSUMED shape -- followers is empty on dev and its field names are
    not documented (Kala question 16): userId blocked followerId."""

    blocker_id: str
    blocked_id: str


def parse_block(doc: dict[str, Any]) -> BlockRecord | None:
    """The block in a followers row, or None if the row is not a block."""
    if not status_is(doc.get("status"), "blocked") or doc.get("userId") is None or doc.get("followerId") is None:
        return None
    return BlockRecord(blocker_id=to_str(doc["userId"]), blocked_id=to_str(doc["followerId"]))


class PostRecord(_Record):
    post_id: str
    author_id: str  # posts.userId (text or ObjectId)
    created_at: datetime | None  # posts.timestamp, else _id
    categories: list[str]
    categories_dropped: list[str]
    post_type: str | None
    post_type_detailed: str | None
    is_hidden: bool  # E-04
    visibility: str | None  # E-04: must be 'public'
    compliance_status: str | None  # posts.compliance.status (E-12)
    product_status: str | None  # posts.Product_status (E-06)
    age_group: str | None  # E-11
    is_repost: bool
    product_ids: list[str]


def parse_post(doc: dict[str, Any], vocabulary: CategoryVocabulary, category_map: dict[str, str] | None = None) -> PostRecord:
    categories = post_categories(vocabulary, doc.get("categories"), category_map)
    product_ids = _ids(doc.get("products"))
    if doc.get("productId") and maybe_str(doc.get("productId")) not in product_ids:
        product_ids.insert(0, maybe_str(doc.get("productId")))
    compliance = doc.get("compliance") if isinstance(doc.get("compliance"), dict) else {}
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
        compliance_status=compliance.get("status"),
        product_status=doc.get("Product_status"),
        age_group=doc.get("ageGroup"),
        is_repost=bool(doc.get("isRepost")),
        product_ids=product_ids,
    )


# --- events ------------------------------------------------------------------------


class PostEventRecord(_Record):
    """One postevents row: the platform's event, with its E code (sheet 4)."""

    source_id: str  # the platform row's _id
    event_id: str | None  # opaque: the app's id, or <action key>:<event type>
    event_type: str | None  # native, lower case
    event_code: str | None  # E code from sheet 4, or None ("—")
    scored: bool  # used by a Wave 1A model (sheet 4)
    user_id: str | None
    actor: Actor  # user_model
    native_surface: str | None
    surface: str | None  # engine surface: feed, product, or None
    is_page_visit: bool  # a post_detail impression (X-05): never a card impression
    request_id: str | None
    position: int | None
    item_id: str | None  # the card shown
    item_type: str | None
    post_id: str | None  # kept alongside (F75): never read as a product id
    product_id: str | None
    is_exploration: bool
    session_id: str | None
    dwell_ms: float | None  # replaces view_duration_seconds (APP-02)
    influencer_id: str | None  # on follow: the account followed
    order_id: str | None
    checkout_id: str | None
    variant_id: str | None
    quantity: float | None
    value: float | None
    feedback_type: str | None
    target_id: str | None  # E13 F61: the post, product or author the feedback is about
    target_type: str | None  # E13 F62: post, product or author
    undone_at: datetime | None
    undo_of: str | None
    is_self: bool
    created_at: datetime | None  # the original event time
    updated_at: datetime | None  # the sync key only


def card_identity(item_id: Any, item_type: Any, post_id: Any, product_id: Any, surface: str | None) -> tuple[str | None, str | None, str | None]:
    """(card id, post_id, product_id), per ENG-03 / X-16 / F10.

    The card shown is item_id; where a platform row carries no item_id, the card
    is its post (or, failing that, its product). On a feed list, item_type
    product with a post id is a post card showing a product: post_id = the card,
    and product_id stays the product -- so a post id is never read as a product id.
    """
    item, post, product = maybe_str(item_id), maybe_str(post_id), maybe_str(product_id)
    card = item or post or product
    if item_type == "post":
        post = post or card
    elif item_type == "product":
        if surface == "feed" and (post or item):
            post = post or item  # a post card showing a product
        else:
            product = product or card
    return card, post, product


def parse_postevent(doc: dict[str, Any]) -> PostEventRecord:
    event_type = doc.get("event_type")
    event_type = event_type.strip().lower() if isinstance(event_type, str) else None
    entry = native(event_type)
    native_surface = doc.get("surface")
    surface = engine_surface(native_surface)
    card, post, product = card_identity(
        doc.get("item_id"), doc.get("item_type"), doc.get("post_id"), doc.get("product_id"), surface
    )
    position = doc.get("position")
    feedback = doc.get("feedback_type")
    return PostEventRecord(
        source_id=to_str(doc["_id"]),
        event_id=_opaque(doc.get("event_id")),
        event_type=event_type,
        event_code=entry.code if entry else None,
        scored=bool(entry and entry.scored),
        user_id=maybe_str(doc.get("user_id")),
        actor=actor_kind(doc.get("user_model")),
        native_surface=native_surface,
        surface=surface,
        is_page_visit=event_type == "impression" and str(native_surface or "").strip().lower() == PAGE_VISIT_SURFACE,
        request_id=_opaque(doc.get("request_id")),
        position=position if isinstance(position, int) and not isinstance(position, bool) else None,
        item_id=card,
        item_type=doc.get("item_type"),
        post_id=post,
        product_id=product,
        is_exploration=bool(doc.get("is_exploration")),
        session_id=_opaque(doc.get("session_id")),
        dwell_ms=_number(doc.get("dwell_ms")),
        influencer_id=maybe_str(doc.get("influencer_id")),
        order_id=maybe_str(doc.get("order_id")),
        checkout_id=_opaque(doc.get("checkout_id")),
        variant_id=maybe_str(doc.get("variant_id")),
        quantity=_number(doc.get("quantity")),
        value=_number(doc.get("value")),
        feedback_type=feedback.strip().lower() if isinstance(feedback, str) else None,
        target_id=maybe_str(doc.get("target_id")),
        target_type=doc.get("target_type").strip().lower() if isinstance(doc.get("target_type"), str) else None,
        undone_at=as_utc(doc.get("undone_at")),
        undo_of=maybe_str(doc.get("undo_of")),
        is_self=bool(doc.get("is_self")),
        created_at=time_of(doc, "created_at"),
        updated_at=as_utc(doc.get("updated_at")),
    )


# --- served lists --------------------------------------------------------------------


class ServedListRecord(_Record):
    """A recommendationrequests row (the platform's served-list record)."""

    source_id: str
    request_id: str | None  # opaque (req_... on fallback lists)
    user_id: str | None
    actor: Actor
    native_surface: str | None
    surface: str | None
    policy_id: str | None
    is_fallback: bool  # any policy_id not starting with cfg is a fallback list (F06)
    candidate_ids: list[str]
    session_id: str | None
    page: int | None
    created_at: datetime | None  # server_ts, else _id
    updated_at: datetime | None


def parse_served_list(doc: dict[str, Any]) -> ServedListRecord:
    policy = doc.get("policy_id")
    page = doc.get("page")
    return ServedListRecord(
        source_id=to_str(doc["_id"]),
        request_id=_opaque(doc.get("request_id")),
        user_id=maybe_str(doc.get("user_id")),
        actor=actor_kind(doc.get("userModel") or doc.get("user_model")),
        native_surface=doc.get("surface"),
        surface=engine_surface(doc.get("surface")),
        policy_id=policy,
        is_fallback=not (isinstance(policy, str) and policy.startswith("cfg")),
        candidate_ids=_ids(doc.get("candidate_ids")),
        session_id=_opaque(doc.get("session_id")),
        page=page if isinstance(page, int) else None,
        created_at=time_of(doc, "server_ts", "created_at"),
        updated_at=as_utc(doc.get("updated_at")),
    )


class ServeLogRecord(_Record):
    """A rec_serve_log row: SOCO_BE's own log of every list request (DS-017 4.3, APP-15).

    request_id, user_id, surface, page, origin (engine, fallback or cache),
    outcome (ok, timeout, error, off or skipped), elapsed_ms and the time. The
    operational fallback rate and the speed seen by SOCO_BE come from it (ENG-24).
    """

    source_id: str
    request_id: str | None  # opaque
    user_id: str | None
    native_surface: str | None
    surface: str | None
    page: int | None
    origin: str | None  # engine | fallback | cache
    outcome: str | None  # ok | timeout | error | off | skipped
    elapsed_ms: float | None
    created_at: datetime | None  # "at" (F80), else time / created_at, else _id
    updated_at: datetime | None


def parse_serve_log(doc: dict[str, Any]) -> ServeLogRecord:
    page = doc.get("page")
    lowered = lambda v: v.strip().lower() if isinstance(v, str) else None  # noqa: E731
    return ServeLogRecord(
        source_id=to_str(doc["_id"]),
        request_id=_opaque(doc.get("request_id")),
        user_id=maybe_str(doc.get("user_id")),
        native_surface=doc.get("surface"),
        surface=engine_surface(doc.get("surface")) or (doc.get("surface") if doc.get("surface") in ("feed", "product") else None),
        page=page if isinstance(page, int) and not isinstance(page, bool) else None,
        origin=lowered(doc.get("origin")),
        outcome=lowered(doc.get("outcome")),
        elapsed_ms=_number(doc.get("elapsed_ms")),
        created_at=time_of(doc, "at", "time", "timestamp", "created_at"),  # F80 names it "at"
        updated_at=as_utc(doc.get("updated_at")),
    )


# --- commerce ----------------------------------------------------------------------


class TrackingEntry(_Record):
    status: str  # the entry's text, as stored
    at: datetime | None
    stage: str | None  # from the settings' tracking_stages (ENG-29 item 4); None if no beginning matches
    actor: Literal["buyer", "seller"] | None  # "... by buyer" / "... by seller" in the text


def tracking_stage(text: str, stages: dict[str, str]) -> str | None:
    """The stage an entry's text begins with, ignoring case; the longest beginning wins."""
    lowered = text.strip().lower()
    matches = [prefix for prefix in stages if lowered.startswith(prefix)]
    return stages[max(matches, key=len)] if matches else None


def tracking_actor(text: str) -> Literal["buyer", "seller"] | None:
    lowered = f" {text.strip().lower()} "
    if " by buyer " in lowered:
        return "buyer"
    if " by seller " in lowered:
        return "seller"
    return None


def _first(entries: list[TrackingEntry], stage: str) -> TrackingEntry | None:
    return next((e for e in entries if e.stage == stage), None)


class OrderRecord(_Record):
    order_id: str
    buyer_id: str | None
    buyer_actor: Actor  # userModel
    seller_id: str | None
    product_id: str | None
    variant_id: str | None  # orders.variant_id: the order wins over the event
    post_id: str | None
    promoter_id: str | None
    checkout_id: str | None  # opaque
    request_id: str | None  # opaque
    value: float | None  # orders.total_price
    quantity: float | None
    status: str | None  # orders.order_status
    buyer_approval_status: str | None
    tracking: list[TrackingEntry]  # orders.tracking_info: the order's history (ENG-29), in time order
    delivered_at: datetime | None  # the FIRST time it reached Delivered (ENG-29 item 4)
    return_requested_at: datetime | None
    returned_at: datetime | None
    cancelled_at: datetime | None  # first cancellation or rejection
    is_returned: bool  # reached Return Requested or Returned, now or in its history (ENG-29 item 5)
    cancelled_by: Literal["buyer", "seller"] | None  # worked out, not stored (DS-017 6.4; ENG-29 item 4)
    cancel_reasons: dict[str, str]  # whatever exists; stored, never scored
    is_incognito: bool  # purchase privacy only: counts for the buyer, never names them
    created_at: datetime | None
    updated_at: datetime | None


def _cancelled_by(status: str | None, approval: str | None, statuses: OrderStatusValues) -> Literal["buyer", "seller"] | None:
    """DS-017 v2.5 section 6.4: Cancelled is by the buyer; Rejected with
    buyer_approval_status 'Rejected By Seller' is by the seller; Rejected with
    'Rejected' is by the buyer."""
    if status_is(status, statuses.cancelled):
        return "buyer"
    if status_is(status, statuses.rejected):
        if status_is(approval, "Rejected By Seller"):
            return "seller"
        if status_is(approval, "Rejected"):
            return "buyer"
    return None


def parse_order(
    doc: dict[str, Any], statuses: OrderStatusValues = OrderStatusValues(), stages: dict[str, str] | None = None
) -> OrderRecord:
    """ENG-29 item 4: tracking_info is the order's history. Each entry's stage comes
    from how its text begins (the settings' tracking_stages), its actor from
    "by buyer" / "by seller". order_status and buyer_approval_status decide the
    canceller first (DS-017 6.4); the entry decides it where they don't."""
    stages = stages if stages is not None else live.current().lists.tracking_stages
    tracking = sorted(
        (
            TrackingEntry(status=str(entry.get("status")), at=as_utc(entry.get("timestamp")),
                          stage=tracking_stage(str(entry.get("status")), stages), actor=tracking_actor(str(entry.get("status"))))
            for entry in doc.get("tracking_info") or []
            if isinstance(entry, dict) and entry.get("status")
        ),
        key=lambda e: (e.at is None, e.at or datetime.min),
    )
    status = doc.get("order_status")
    delivered, requested, returned = _first(tracking, "delivered"), _first(tracking, "return_requested"), _first(tracking, "returned")
    cancelled = next((e for e in tracking if e.stage in ("cancelled", "rejected")), None)
    is_returned = (
        any(status_is(status, v) for v in (statuses.return_requested, statuses.returned))
        or requested is not None or returned is not None
    )
    reasons = {
        field: str(doc[field])
        for field in ("reason_code", "cancel_reason", "cancel_reason_by_buyer", "reject_reason_by_buyer")
        if doc.get(field)
    }
    return OrderRecord(
        order_id=to_str(doc["_id"]),
        buyer_id=maybe_str(doc.get("user_id")),
        buyer_actor=actor_kind(doc.get("userModel")),
        seller_id=maybe_str(doc.get("seller_id")),
        product_id=maybe_str(doc.get("product_id")),
        variant_id=maybe_str(doc.get("variant_id")),
        post_id=maybe_str(doc.get("post_id")),
        promoter_id=maybe_str(doc.get("promoter_id")),
        checkout_id=_opaque(doc.get("checkout_id")),
        request_id=_opaque(doc.get("request_id")),
        value=_number(doc.get("total_price")),
        quantity=_number(doc.get("quantity")),
        status=status,
        buyer_approval_status=doc.get("buyer_approval_status"),
        tracking=tracking,
        delivered_at=delivered.at if delivered else None,
        return_requested_at=requested.at if requested else None,
        returned_at=returned.at if returned else None,
        cancelled_at=cancelled.at if cancelled else None,
        is_returned=is_returned,
        cancelled_by=_cancelled_by(status, doc.get("buyer_approval_status"), statuses) or (cancelled.actor if cancelled else None),
        cancel_reasons=reasons,
        is_incognito=bool(doc.get("isIncognitoMode")),
        created_at=time_of(doc, "created_at"),
        updated_at=as_utc(doc.get("updated_at")),
    )


class CartLineRecord(_Record):
    user_id: str | None
    actor: Actor  # userModel
    product_id: str | None
    variant_id: str | None
    post_id: str | None
    quantity: float | None
    request_id: str | None  # carts.ml.request_id: the list that first added the item (X-07)
    added_at: datetime | None


def parse_cart_line(doc: dict[str, Any]) -> CartLineRecord:
    ml = doc.get("ml") if isinstance(doc.get("ml"), dict) else {}
    return CartLineRecord(
        user_id=maybe_str(doc.get("user_id")),
        actor=actor_kind(doc.get("userModel")),
        product_id=maybe_str(doc.get("product_id")),
        variant_id=maybe_str(doc.get("variant_id")),
        post_id=maybe_str(doc.get("post_id")),
        quantity=_number(doc.get("quantity")),
        request_id=_opaque(ml.get("request_id") or doc.get("request_id")),
        added_at=time_of(doc, "timestamp"),
    )


class ProductRecord(_Record):
    product_id: str
    seller_id: str | None  # products.createdBy
    created_at: datetime | None
    status: str | None
    is_active: bool  # products.status 'Activate', ignoring case (E-07)
    in_stock: bool  # availability.inStock
    category_id: str | None  # categoryPathIds[0], else basicInfo.categoryId
    category: str | None  # one of the 23, or None
    cross_sell_ids: list[str]


def parse_product(doc: dict[str, Any], categories: ProductCategoryIndex) -> ProductRecord:
    basic = doc.get("basicInfo") if isinstance(doc.get("basicInfo"), dict) else {}
    availability = doc.get("availability") if isinstance(doc.get("availability"), dict) else {}
    path_ids = _ids(doc.get("categoryPathIds"))
    category_id = path_ids[0] if path_ids else maybe_str(basic.get("categoryId"))
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
    seller_id: str | None
    price: float | None  # salePrice
    list_price: float | None  # originalPrice
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
    top_level: str | None  # the first name in its path, if one of the 23 (or mapped)


def parse_category(doc: dict[str, Any], vocabulary: CategoryVocabulary, category_map: dict[str, str] | None = None) -> CategoryRecord:
    path = [p for p in doc.get("path") or [] if isinstance(p, str)]
    level = doc.get("level")
    return CategoryRecord(
        category_id=to_str(doc["_id"]),
        name=doc.get("name"),
        level=level if isinstance(level, int) else None,
        path=path,
        parent_id=maybe_str(doc.get("parent")),
        top_level=canonical_name(vocabulary, path[0] if path else doc.get("name"), category_map),
    )


#: Every record kind, for the readers and the ENG-03 check.
RECORD_KINDS: tuple[str, ...] = (
    "user", "business", "post", "postevent", "follow", "order", "cart_line",
    "product", "variant", "category", "served_list", "serve_log",
)
