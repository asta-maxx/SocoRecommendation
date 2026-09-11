"""The event row contract. Agreed in writing BEFORE the generator is built.

This is the shape of one document in `ml_demo_events`. It exists so the
generator and the engine can be built in parallel instead of one waiting on the
other: both sides validate against this model, so a field renamed on one side
fails on the other immediately rather than on demo day.

THE FIVE AGREED FIELDS
----------------------
    user_id     who
    event_type  what
    categories  which categories -- see the note below on why this is plural
    timestamp   when
    weight      what the generator believes it is worth

TWO MORE, CONDITIONAL
---------------------
    view_duration_seconds   on views only
    order_id                on purchase and reversal rows only

Seven fields on a row, five of them on every row. Both statements are true and
they are not in conflict: five is the core every row carries, seven is the full
set once the conditional pair is included.

`weight` IS WRITTEN BUT NEVER READ BY THE ENGINE
------------------------------------------------
The generator writes it so the data checks can do arithmetic a human can follow.
The engine derives every weight from P-06 keyed on `event_type` and ignores this
field entirely -- `domain.events.Event` has nowhere to put it. If the engine read
it, P-06 would stop being configuration: retuning a weight would change no score
and nothing would fail loudly to say so.

Keeping it on the row and unread is deliberate. `expected_weight()` below lets a
check assert that what the generator believed and what P-06 says agree -- which
is a test worth having, and the only legitimate use of the field.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

#: The event types a generated row may carry. `purchase_reversal` is its own
#: type rather than a boolean flag, so a row is self-describing and the contract
#: stays at seven fields.
ROW_EVENT_TYPES = (
    "product_view",
    "keyword_search",
    "product_click",
    "add_to_cart",
    "purchase",
    "purchase_reversal",
)

#: Row type -> the P-06 weight key it is paid at. The generator spells the types
#: one way and P-06 spells its weights another; this is the single place the two
#: vocabularies meet. `postevents` uses a third spelling again -- that mapping
#: lives in data.readers, which is the module that knows about sources.
ROW_TYPE_TO_WEIGHT = {
    "product_view": "view",
    "keyword_search": "search",
    "product_click": "click",
    "add_to_cart": "cart",
    "purchase": "purchase",
    "purchase_reversal": "purchase",
}

#: The five every row carries, in the agreed order.
CORE_FIELDS = ("user_id", "event_type", "categories", "timestamp", "weight")

#: Four legacy keys resolve to Home & Living, but only THREE are merges. Ruled by
#: Kala on 10 September, settling DS-008's "four" -- that figure counts map
#: entries, not merges.
#:
#: The fourth is an underscore variant of the canonical label repairing its own
#: spelling, which is why a category key with an underscore is rejected outright
#: by this contract: the underscore form is a legacy spelling to be mapped away,
#: never a value to store.
#:
#: U06 must show three old categories collapsing into one AND, separately, a
#: spelling being corrected. Presenting all four as merges overstates the
#: migration.
HOME_AND_LIVING_MERGES = ("home & decor", "kitchen & dining", "bedding & bath")
HOME_AND_LIVING_SPELLING_FIX = "home_&_living"

#: The two that appear only where they apply.
CONDITIONAL_FIELDS = ("view_duration_seconds", "order_id")


class DemoEventRow(BaseModel):
    """One row in ml_demo_events.

    The generator constructs these and writes `.model_dump()`. The engine's
    reader adapter consumes the same names. Neither side writes a field name as
    a string literal anywhere else.
    """

    model_config = {"extra": "forbid"}

    user_id: str
    event_type: str

    #: PLURAL, and an array even when there is one category.
    #:
    #: A post carrying several categories contributes FULL weight to EACH, not a
    #: divided share -- that is U03's whole purpose. A singular `category` field
    #: cannot express it, and a generator emitting one would make U03
    #: unbuildable without a second code path.
    categories: list[str] = Field(min_length=1)

    timestamp: datetime

    #: Written for the data checks. NOT read by the engine. See module docstring.
    weight: float

    view_duration_seconds: float | None = None
    order_id: str | None = None

    @field_validator("user_id")
    @classmethod
    def _user_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_id must not be blank")
        return v.strip()

    @field_validator("event_type")
    @classmethod
    def _event_type(cls, v: str) -> str:
        if v not in ROW_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {list(ROW_EVENT_TYPES)}, got {v!r}"
            )
        return v

    @field_validator("categories")
    @classmethod
    def _categories(cls, v: list[str]) -> list[str]:
        """Any non-blank string is allowed.

        The contract says so explicitly: the engine maps or drops, it does not
        validate at read. U06 carries legacy spellings ("home & decor") and U08
        carries values with no canonical equivalent ("Casual Sneakers") on
        purpose -- rejecting them here would make those two users ungeneratable
        and delete the demonstration of mapping and dropping.
        """
        for category in v:
            if not category.strip():
                raise ValueError("a category must not be blank")
        return v

    @field_validator("timestamp")
    @classmethod
    def _timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _conditional_fields_match_the_type(self) -> DemoEventRow:
        if self.event_type in ("purchase", "purchase_reversal") and not self.order_id:
            raise ValueError(
                f"{self.event_type} rows must carry order_id -- a reversal is aged "
                f"from the ORIGINAL order's creation, and without the id that "
                f"timestamp cannot be found"
            )
        if self.event_type != "product_view" and self.view_duration_seconds is not None:
            raise ValueError(
                "view_duration_seconds belongs on product_view rows only -- P-02 "
                "applies to views, and a duration elsewhere invites it being "
                "applied wider"
            )
        return self

    def expected_weight(self, tunables: dict) -> float:
        """What P-06 says this row is worth.

        The only legitimate reading of the `weight` field is a check asserting
        this equals it. A reversal is the purchase weight negated -- it is not
        P-07 negative feedback, and multiplying it by P-07 (0 at launch) would
        zero it silently.
        """
        weight = tunables["P-06"][ROW_TYPE_TO_WEIGHT[self.event_type]]
        return -weight if self.event_type == "purchase_reversal" else weight


def is_declared_interest_row(row: dict) -> bool:
    """Whether a row looks like a declared interest that has leaked in.

    A declared interest is a statement of preference, not an action. It has no
    timestamp and must never reach the event stream, where Method A's decay term
    would consume it -- the single easiest thing in this build to get wrong (G6).

    A row with no timestamp, or one typed as an interest, is that leak.
    """
    return row.get("timestamp") is None or row.get("event_type") in (
        "interest",
        "declared_interest",
        "signup_interest",
    )
