"""The service contract between SOCO and the recommendation service. RE-00d, DS-017.

DS-003 RE-00d: "Agree the request and response shape between the app and the
recommendation service, and agree the single endpoint all twelve events are
written to." This module is both halves:

    POST /v1/recommendations   the request and response shape -- a served list
    POST /v1/events            the ONE endpoint all twelve events are written to

The twelve events are the DS-003 capture register, section 1, E1 to E12, and their
fields are section 2, F01 to F59, with the register's own names. Where this module
adds anything the register does not carry, the addition is marked BEYOND THE
REGISTER at the point it is made, with the reason, so it is a proposal rather than
a quiet change to an agreed document.

Enforced in code for the same reason the event row contract is: a field renamed on
one side should fail the other side's tests, not surface as an empty collection.
SOCO_BE is Node, so it validates against the JSON Schema exported from here --
`docs/service_contract.schema.json` -- and a test fails if that file falls behind.

TIME DISCIPLINE (R7)
--------------------
Server clocks are UTC, and the contract refuses anything else: `server_ts`,
`state_ts`, `stitch_ts`. The device clock keeps its offset: `client_ts` must carry
one and is stored with it, never converted and never overwritten by server time,
so clock skew between device and server stays detectable. The ingest endpoint
stamps `received_at` separately -- R7 requires every event time to differ from
the time it was ingested.

REQUIRED-BUT-NULLABLE IS DELIBERATE
-----------------------------------
Every field that may be empty is a required key that may be `null`. An absent key
is a caller bug; an explicit null is a statement. U10 is the proof of why that
matters: `if "timestamp" not in row` misses every one of its rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

#: Bumped only by agreement. The major digit changes when a field is removed or its
#: meaning changes; an added nullable field is a minor change.
CONTRACT_VERSION = "1.0"

RECOMMENDATIONS_PATH = "/v1/recommendations"

#: The single ingest endpoint. All twelve events go here -- no per-event routes, so
#: there is one place to authenticate, validate, log and monitor, and a thirteenth
#: event is a contract change rather than a new route.
INGEST_PATH = "/v1/events"

#: Where accepted events land. ml_ prefixed, so it needs one line adding to the
#: mlWriter role in HANDOFF.md section 3.
EVENTS_COLLECTION = "ml_events"

#: An engineering limit, not a model parameter.
MAX_EVENTS_PER_REQUEST = 500

#: The policy_id SOCO_BE stamps when it served the delivered ordering itself,
#: because the service timed out or failed (rung 5). R1 still holds: the backend
#: generates the request_id and emits recommendation_request, so impressions of a
#: fallback list join back to something that says the engine did not order it.
DELIVERED_POLICY_ID = "delivered"


# --- shared field types ------------------------------------------------------------


def _require_utc(value: datetime) -> datetime:
    """R7: a backend clock, in UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must carry a timezone, and it must be UTC")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(
            f"must be UTC -- got offset {value.utcoffset()}. Server times are "
            "stamped in UTC; only client_ts carries a local offset"
        )
    return value


def _require_offset(value: datetime) -> datetime:
    """R7: the device clock, with its offset, kept as sent."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "client_ts must carry the device's timezone offset, e.g. +05:30"
        )
    return value


Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
UtcTs = Annotated[datetime, AfterValidator(_require_utc)]
ClientTs = Annotated[datetime, AfterValidator(_require_offset)]
Position = Annotated[int, Field(ge=1)]  # F11, F18: counting from one
Money = Annotated[float, Field(ge=0)]


class Surface(StrEnum):
    """F02. Which screen asked. Each surface is ranked by a different model.

    The three Wave 1A surfaces: the feed (Engine A), product and cart screens (M5)
    and promoter opportunities (Engine B). Aravinth's F02 note says `feedType`
    already carries this under another name; its values must be mapped onto these,
    and any surface missing here added by agreement -- the register allows no free
    text.
    """

    FEED = "feed"
    PRODUCT = "product"
    OPPORTUNITY = "opportunity"


class ItemType(StrEnum):
    """F10. What an item is.

    The register lists "product, promotion, promoter or brand" in F10 and "product,
    post, promoter or brand" in F32. Feed items are posts, so both lists are taken
    together rather than one silently chosen.
    """

    POST = "post"
    PRODUCT = "product"
    PROMOTION = "promotion"
    PROMOTER = "promoter"
    BRAND = "brand"


# --- POST /v1/recommendations ------------------------------------------------------------


class RecommendationsRequest(BaseModel):
    """What SOCO_BE sends when a surface needs a list.

    The fields /dashboard-feed already receives, renamed to the register's
    spelling. `session_id` (F04) is absent: it is Deferred in the register, and no
    app session identifier exists (DS-003 question 7).
    """

    model_config = {"extra": "forbid", "frozen": True}

    contract_version: Literal["1.0"]
    user_id: Id  # F03
    surface: Surface  # F02
    limit: int = Field(ge=1)
    page: int = Field(ge=1)
    is_business_account: bool
    #: Generated by Flutter on pull-to-refresh. Varies the order of similarly
    #: ranked items without changing the ranking logic.
    refresh_seed: str | None


class RecommendedItem(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    item_id: Id  # F09
    item_type: ItemType  # F10
    position: Position  # F11


class RecommendationsResponse(BaseModel):
    """What the service returns. Budget 200 ms, then SOCO_BE serves the delivered
    ordering under DELIVERED_POLICY_ID.

    The client keeps `request_id` and `is_exploration` with the list and echoes
    them on every event that follows from it (R1, R5). `policy_id` is the stamp for
    the list (R3). It is not repeated on each event, because request_id joins
    every event back to the recommendation_request that carries it.
    """

    model_config = {"extra": "forbid", "frozen": True}

    contract_version: Literal["1.0"]
    request_id: Id  # F01
    #: F06. The configuration generation AND, on the three two-method slots, the
    #: variant that served -- PT-10 requires the served list to say which method
    #: produced it.
    policy_id: Id
    server_ts: UtcTs  # F07
    #: F14. Set by the service for the randomised slice. Never computed on the client.
    is_exploration: bool
    #: False when the list is not built from this user's own profile -- the cold
    #: start ladder's platform popularity rung. A screen must not label such a list
    #: "Recommended for you".
    personalised: bool
    items: list[RecommendedItem]

    @field_validator("items")
    @classmethod
    def _positions_run_from_one_without_gaps(
        cls, items: list[RecommendedItem]
    ) -> list[RecommendedItem]:
        """F11's check: integers from one upward, no gaps within one request."""
        positions = [item.position for item in items]
        if positions != list(range(1, len(items) + 1)):
            raise ValueError(
                f"positions must run 1..{len(items)} in order, got {positions}"
            )
        return items


# --- the twelve events --------------------------------------------------------------------


class EventName(StrEnum):
    """DS-003 capture register, section 1."""

    RECOMMENDATION_REQUEST = "recommendation_request"  # E1
    RECOMMENDATION_IMPRESSION = "recommendation_impression"  # E2
    RECOMMENDATION_CLICK = "recommendation_click"  # E3
    ADD_TO_CART = "add_to_cart"  # E4
    ORDER_PLACED = "order_placed"  # E5
    ORDER_STATE_CHANGED = "order_state_changed"  # E6
    PAYMENT_STATE_CHANGED = "payment_state_changed"  # E7
    COMMISSION_STATE_CHANGED = "commission_state_changed"  # E8
    SOCIAL_INTERACTION = "social_interaction"  # E9
    OPPORTUNITY_STATE_CHANGED = "opportunity_state_changed"  # E10
    SEARCH_PERFORMED = "search_performed"  # E11
    IDENTITY_STITCHED = "identity_stitched"  # E12


#: The register's ID for each event.
REGISTER_ID: dict[EventName, str] = {
    name: f"E{i}" for i, name in enumerate(EventName, start=1)
}

#: The event decision recorded in the register's column J. A shape is agreed here
#: for every event, whatever its decision, so a Deferred event arrives later as an
#: implementation rather than as a fresh negotiation.
REGISTER_DECISION: dict[EventName, str] = {
    EventName.RECOMMENDATION_REQUEST: "Accepted",
    EventName.RECOMMENDATION_IMPRESSION: "Accepted",
    EventName.RECOMMENDATION_CLICK: "Accepted",
    EventName.ADD_TO_CART: "Accepted",
    EventName.ORDER_PLACED: "Accepted",
    EventName.ORDER_STATE_CHANGED: "Accepted",
    EventName.PAYMENT_STATE_CHANGED: "Needs discussion",
    EventName.COMMISSION_STATE_CHANGED: "Accepted",
    EventName.SOCIAL_INTERACTION: "Accepted",
    EventName.OPPORTUNITY_STATE_CHANGED: "Deferred",
    EventName.SEARCH_PERFORMED: "Accepted",
    EventName.IDENTITY_STITCHED: "Needs discussion",
}

#: How M1 reads each event: the P-06 weight key it is paid at, or None where M1
#: does not read it. The conditions live in the ml_events reader adapter, not here:
#:
#:   recommendation_impression  a view, only if viewport_entered and dwell_ms is at
#:                              least P-02. dwell_ms null scores nothing and is
#:                              counted separately from a short view
#:   order_placed               a purchase, at order creation, not at Delivered
#:   order_state_changed        the purchase weight NEGATED when new_state is
#:                              Cancelled or Rejected, aged from the ORIGINAL
#:                              order's creation; every other state scores nothing
#:   search_performed           a search -- but see the note on SearchPerformed:
#:                              the register carries no result categories
M1_WEIGHT_KEY: dict[EventName, str | None] = {
    EventName.RECOMMENDATION_REQUEST: None,
    EventName.RECOMMENDATION_IMPRESSION: "view",
    EventName.RECOMMENDATION_CLICK: "click",
    EventName.ADD_TO_CART: "cart",
    EventName.ORDER_PLACED: "purchase",
    EventName.ORDER_STATE_CHANGED: "purchase",
    EventName.PAYMENT_STATE_CHANGED: None,
    EventName.COMMISSION_STATE_CHANGED: None,
    EventName.SOCIAL_INTERACTION: None,
    EventName.OPPORTUNITY_STATE_CHANGED: None,
    EventName.SEARCH_PERFORMED: "search",
    EventName.IDENTITY_STITCHED: None,
}


class _EventBase(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    #: BEYOND THE REGISTER. Generated once, where the event is created. It is the
    #: idempotency key: a retried request is counted as duplicates, never stored
    #: twice. Without it a timeout-and-retry double counts every event in the batch.
    event_id: UUID


class RecommendationRequestEvent(_EventBase):
    """E1. Emitted by the recommendation service as it builds a response.

    Not an endpoint of its own. The service writes it to ml_events through the same
    validation as everything else. SOCO_BE sends it only when it served the
    delivered ordering itself, with policy_id DELIVERED_POLICY_ID.
    """

    event_name: Literal["recommendation_request"]
    request_id: Id  # F01
    surface: Surface  # F02
    user_id: Id  # F03
    session_id: Id | None  # F04 -- Deferred in the register; null until it exists
    #: F05. The shortlist before ranking, including items not shown. Held in the
    #: service, never returned to the client.
    candidate_ids: list[Id]
    policy_id: Id  # F06
    server_ts: UtcTs  # F07


class RecommendationImpressionEvent(_EventBase):
    """E2. An item on a served list, from the list widget's visibility callback."""

    event_name: Literal["recommendation_impression"]
    request_id: Id  # F08
    item_id: Id  # F09
    item_type: ItemType  # F10
    position: Position  # F11
    viewport_entered: bool  # F12
    #: F13. Enter to leave, measured on the device. Null when not measured, which
    #: is neither a short view nor a qualified one.
    dwell_ms: Annotated[int, Field(ge=0)] | None
    is_exploration: bool  # F14, echoed from the response
    client_ts: ClientTs  # F15


class RecommendationClickEvent(_EventBase):
    """E3. A card-level tap. Carries the same request_id as the impression."""

    event_name: Literal["recommendation_click"]
    request_id: Id  # F16
    item_id: Id  # F17
    position: Position  # F18
    server_ts: UtcTs  # F19


class AddToCartEvent(_EventBase):
    """E4. Emitted by the backend after the cart write succeeds."""

    event_name: Literal["add_to_cart"]
    #: F20. Null when the product was not reached from a served list -- from a
    #: search or a shared link, say. A null is a statement; an invented id is not.
    request_id: Id | None
    product_id: Id  # F21
    quantity: Annotated[int, Field(ge=1)]  # F22
    #: BEYOND THE REGISTER. Who added it. The register joins through request_id,
    #: which is null whenever the product was not reached from a list, and an
    #: unattributable cart add is lost to M1-12. The engagement call already sends
    #: user_id, so this costs nothing to carry.
    user_id: Id


class LineItem(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    product_id: Id
    qty: Annotated[int, Field(ge=1)]
    price: Money


class OrderPlacedEvent(_EventBase):
    """E5. Emitted unconditionally after the order document is written, whether or
    not a post_id is present."""

    event_name: Literal["order_placed"]
    order_id: Id  # F23
    request_id: Id | None  # F24 -- null on an order not reached from a list
    #: F25. One order per product (Q04), so one line today. Kept as an array so a
    #: multi-line order changes nothing here.
    line_items: list[LineItem] = Field(min_length=1)
    promoter_id: Id | None  # F26 -- null on a direct order
    order_value: Money  # F27, total_price
    server_ts: UtcTs  # F28
    checkout_id: Id | None  # F59 -- null on a direct order (question 2)


class OrderState(StrEnum):
    """F30. The values of order_status, the canonical field (Q06, PT-04).

    Pending is the state an order is created in, so it arrives as order_placed.
    Returned and Refunded do not exist: D1 records a return as two fields on the
    order, with the status left unchanged.
    """

    ACCEPTED = "Accepted"
    CONFIRMED = "Confirmed"
    SHIPPED = "Shipped"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"


#: The states that reverse a purchase for M1.
REVERSING_ORDER_STATES = frozenset({OrderState.CANCELLED, OrderState.REJECTED})


class OrderStateChangedEvent(_EventBase):
    """E6. From every place order_status is written, including admin actions and jobs."""

    event_name: Literal["order_state_changed"]
    order_id: Id  # F29
    new_state: OrderState  # F30
    reason_code: str | None  # F31
    state_ts: UtcTs  # F32


class PaymentStateChangedEvent(_EventBase):
    """E7. Needs discussion in the register: no Razorpay webhook exists."""

    event_name: Literal["payment_state_changed"]
    order_id: Id  # F33
    new_state: Literal["settled", "failed", "charged_back"]  # F34
    state_ts: UtcTs  # F35


class CommissionStateChangedEvent(_EventBase):
    """E8. All three transitions, not only the first."""

    event_name: Literal["commission_state_changed"]
    commission_id: Id  # F36
    promoter_id: Id  # F37
    order_id: Id  # F38
    new_state: Literal["attributed", "confirmed", "reversed"]  # F39
    amount: Money  # F40
    state_ts: UtcTs  # F41


class SocialInteractionEvent(_EventBase):
    """E9. One event per action, with who and when, not a counter."""

    event_name: Literal["social_interaction"]
    user_id: Id  # F42
    target_id: Id  # F43
    action: Literal["like", "save", "share", "repost", "follow"]  # F44
    request_id: Id | None  # F45 -- null when not acted on from a served list
    server_ts: UtcTs  # F46


class OpportunityStateChangedEvent(_EventBase):
    """E10. Deferred in the register: no opportunity model exists yet."""

    event_name: Literal["opportunity_state_changed"]
    opportunity_id: Id  # F47
    promoter_id: Id  # F48
    #: F49. Deferred. Null until Q02 delivers a campaign entity -- never a promo code.
    campaign_id: Id | None
    new_state: Literal["accepted", "completed", "withdrawn", "expired"]  # F50
    state_ts: UtcTs  # F51


class SearchPerformedEvent(_EventBase):
    """E11. Emitted after the search resolves, fire and forget.

    M1 credits a search to the categories of its RESULT SET (P-06), and the register
    carries no result categories -- only query_text and result_count. As registered,
    M1-15 stays not computable. That is an open point in the contract document, not
    something added here unasked.
    """

    event_name: Literal["search_performed"]
    user_id: Id  # F52
    query_text: Annotated[str, StringConstraints(min_length=1)]  # F53, untrimmed
    result_count: Annotated[int, Field(ge=0)]  # F54
    server_ts: UtcTs  # F55


class IdentityStitchedEvent(_EventBase):
    """E12. Needs discussion in the register: no anonymous identifier exists yet."""

    event_name: Literal["identity_stitched"]
    anonymous_id: Id  # F56
    user_id: Id  # F57
    stitch_ts: UtcTs  # F58


EVENT_MODELS: dict[EventName, type[_EventBase]] = {
    EventName.RECOMMENDATION_REQUEST: RecommendationRequestEvent,
    EventName.RECOMMENDATION_IMPRESSION: RecommendationImpressionEvent,
    EventName.RECOMMENDATION_CLICK: RecommendationClickEvent,
    EventName.ADD_TO_CART: AddToCartEvent,
    EventName.ORDER_PLACED: OrderPlacedEvent,
    EventName.ORDER_STATE_CHANGED: OrderStateChangedEvent,
    EventName.PAYMENT_STATE_CHANGED: PaymentStateChangedEvent,
    EventName.COMMISSION_STATE_CHANGED: CommissionStateChangedEvent,
    EventName.SOCIAL_INTERACTION: SocialInteractionEvent,
    EventName.OPPORTUNITY_STATE_CHANGED: OpportunityStateChangedEvent,
    EventName.SEARCH_PERFORMED: SearchPerformedEvent,
    EventName.IDENTITY_STITCHED: IdentityStitchedEvent,
}

#: Fields each event carries that the register does not. Kept as data so a test can
#: hold the contract to "the register's fields, plus exactly these".
BEYOND_THE_REGISTER: dict[EventName, set[str]] = {
    name: {"event_id", "event_name"} for name in EventName
}
BEYOND_THE_REGISTER[EventName.ADD_TO_CART] |= {"user_id"}

IngestEvent = Annotated[
    Union[
        RecommendationRequestEvent,
        RecommendationImpressionEvent,
        RecommendationClickEvent,
        AddToCartEvent,
        OrderPlacedEvent,
        OrderStateChangedEvent,
        PaymentStateChangedEvent,
        CommissionStateChangedEvent,
        SocialInteractionEvent,
        OpportunityStateChangedEvent,
        SearchPerformedEvent,
        IdentityStitchedEvent,
    ],
    Field(discriminator="event_name"),
]

_EVENT_ADAPTER: TypeAdapter[IngestEvent] = TypeAdapter(IngestEvent)


# --- POST /v1/events --------------------------------------------------------------------


class IngestRequest(BaseModel):
    """The request body of POST /v1/events, fully typed.

    This is the shape SOCO_BE builds and the schema it validates against. The server
    parses the envelope and each event separately -- see `parse_batch` -- so one
    malformed impression does not throw away an order in the same batch.
    """

    model_config = {"extra": "forbid"}

    contract_version: Literal["1.0"]
    sent_at: UtcTs
    events: list[IngestEvent] = Field(min_length=1, max_length=MAX_EVENTS_PER_REQUEST)


class _Envelope(BaseModel):
    """IngestRequest with the events left unparsed. Server side only."""

    model_config = {"extra": "forbid"}

    contract_version: Literal["1.0"]
    sent_at: UtcTs
    events: list[Any] = Field(min_length=1, max_length=MAX_EVENTS_PER_REQUEST)


class RejectedEvent(BaseModel):
    model_config = {"extra": "forbid"}

    #: Position in the request's `events` array.
    index: int
    #: Echoed when the event carried a readable one, so the caller can find it.
    event_id: str | None
    errors: list[str]


class IngestResponse(BaseModel):
    """202 Accepted -- the envelope was valid, whatever happened to each event.

    `accepted` means STORED, not that the event will score. A short impression or
    an order state M1 does not read is accepted, then ignored or dropped and counted
    by the reader.

    `accepted + duplicates + len(rejected)` always equals the number sent.
    """

    model_config = {"extra": "forbid"}

    contract_version: Literal["1.0"]
    received_at: UtcTs
    accepted: int = Field(ge=0)
    #: Already stored under the same event_id. Not an error: it is what makes a
    #: retry safe.
    duplicates: int = Field(ge=0)
    rejected: list[RejectedEvent]


class IngestError(BaseModel):
    """400 when the envelope itself is unusable. Nothing in the request is stored."""

    model_config = {"extra": "forbid"}

    contract_version: Literal["1.0"]
    error: str
    detail: list[str]


@dataclass(frozen=True)
class ParsedBatch:
    events: list[_EventBase]
    rejected: list[RejectedEvent]
    #: Repeats of an event_id earlier in the same request. Repeats of one already in
    #: the store are found at write time.
    duplicates_in_request: int
    sent_at: datetime


def _messages(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in e['loc']) or '(event)'}: {e['msg']}"
        for e in error.errors()
    ]


def parse_batch(body: Any) -> ParsedBatch:
    """Validate a request body. Raises ValidationError only for the envelope.

    Each event is validated on its own and either accepted or rejected with its
    reasons -- a batch is never all-or-nothing.
    """
    envelope = _Envelope.model_validate(body)

    events: list[_EventBase] = []
    rejected: list[RejectedEvent] = []
    seen: set[UUID] = set()
    duplicates = 0

    for index, raw in enumerate(envelope.events):
        try:
            event = _EVENT_ADAPTER.validate_python(raw)
        except ValidationError as error:
            raw_id = raw.get("event_id") if isinstance(raw, dict) else None
            rejected.append(
                RejectedEvent(
                    index=index,
                    event_id=raw_id if isinstance(raw_id, str) else None,
                    errors=_messages(error),
                )
            )
            continue

        if event.event_id in seen:
            duplicates += 1
            continue
        seen.add(event.event_id)
        events.append(event)

    return ParsedBatch(
        events=events,
        rejected=rejected,
        duplicates_in_request=duplicates,
        sent_at=envelope.sent_at,
    )


def to_document(event: _EventBase, received_at: datetime) -> dict[str, Any]:
    """How an accepted event is stored in ml_events.

    The event's own fields, plus the two the server adds. `event_id` is held as
    text so the unique index and a JSON round-trip agree. `client_ts` is held as
    the ISO string it arrived as: BSON dates are UTC, and storing it as one would
    throw away the device offset R7 exists to keep.
    """
    document = event.model_dump(mode="python")
    document["event_id"] = str(document["event_id"])
    if "client_ts" in document:
        document["client_ts"] = document["client_ts"].isoformat()
    document["received_at"] = _require_utc(received_at)
    document["contract_version"] = CONTRACT_VERSION
    return document


#: The indexes ml_events needs. The unique one makes retries safe. The other two are
#: the joins everything depends on: a user's history, and every event back to its
#: request (R1). The first is exactly the index postevents lacks (open question 4).
EVENTS_INDEXES = (
    ({"event_id": 1}, {"name": "uniq_event_id", "unique": True}),
    ({"user_id": 1, "event_name": 1}, {"name": "user_events", "sparse": True}),
    ({"request_id": 1}, {"name": "request_join", "sparse": True}),
)


def json_schema() -> dict[str, Any]:
    """The contract as JSON Schema, for the Node side. Written to docs/ by
    scripts/export_contract_schema.py; a test fails if the file is stale."""
    from pydantic.json_schema import models_json_schema

    _, schema = models_json_schema(
        [
            (RecommendationsRequest, "validation"),
            (RecommendationsResponse, "serialization"),
            (IngestRequest, "validation"),
            (IngestResponse, "serialization"),
            (IngestError, "serialization"),
        ],
        title=f"SOCO recommendation service contract v{CONTRACT_VERSION}",
    )
    schema["x-contract-version"] = CONTRACT_VERSION
    schema["x-endpoints"] = {
        "recommendations": f"POST {RECOMMENDATIONS_PATH}",
        "ingest": f"POST {INGEST_PATH}",
    }
    schema["x-register"] = {
        name.value: {"id": REGISTER_ID[name], "decision": REGISTER_DECISION[name]}
        for name in EventName
    }
    return schema
