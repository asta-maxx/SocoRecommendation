"""The one event shape the scoring methods see.

Swapping a collection name does NOT make two differently shaped documents
compatible, so `DATA_PROFILE` cannot be the whole story:

  demo (ml_demo_events)  the categories array is on the event row itself
  live (postevents)      the row carries a post_id and no categories at all;
                         the category resolves through the post's `categories`
                         field, which is a join

Those are structurally different reads. Rather than let each method learn both,
`data.readers` adapts each source into the shape below, and the methods see only
this. One shared internal shape, one adapter per source.

WHY THERE IS NO `weight` FIELD HERE
-----------------------------------
The generator writes a `weight` onto every demo row. That value exists for the
data checks' arithmetic, so a check can assert against a number a human can
follow. It is NOT an input to the engine.

If a method read `weight` off the row, P-06 would stop being configuration:
retuning a weight would no longer change any score, the config layer would be
decorative, and nothing would fail loudly to say so. The engine derives every
weight from P-06 keyed on `event_type`. This model therefore has nowhere to put
a row's weight, which is the enforcement -- an adapter that tried to carry one
would not typecheck, and `test_events.py` asserts the field is absent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(StrEnum):
    """The five event types P-06 carries a weight for.

    Negative feedback (hide, report, skip) is P-07 and is not in this list: its
    launch weight is 0 and it is a separate concern from the purchase reversal.
    """

    VIEW = "view"
    SEARCH = "search"
    CLICK = "click"
    CART = "cart"
    PURCHASE = "purchase"


class Event(BaseModel):
    """One qualifying interaction, normalised across sources.

    Deliberately carries no weight and no score. It is an observation; what it is
    worth is P-06's business, decided by the method at scoring time.
    """

    model_config = {"extra": "forbid", "frozen": True}

    user_id: str
    event_type: EventType

    #: Full weight to EACH, not a divided share -- a post carrying several
    #: categories contributes its whole weight to every one of them.
    categories: list[str]

    timestamp: datetime

    #: Present on views only. The method applies P-02 to it; the reader does not,
    #: because the threshold is a tunable and a reader that filtered on it would
    #: be making a scoring decision.
    view_duration_seconds: float | None = None

    #: Purchases and reversals only.
    order_id: str | None = None

    #: A reversal reverses a purchase and is aged from the ORIGINAL ORDER'S
    #: creation, never from the cancellation. A cancellation is always more
    #: recent than the order it cancels, so it decays less, so it is always
    #: larger -- aged from the cancellation the user ends up below someone who
    #: never ordered and the raw goes negative.
    #:
    #: Carrying the original timestamp on the row is what keeps the incremental
    #: path exact: the reversal can be aged correctly whenever it is noticed.
    is_reversal: bool = False

    @field_validator("user_id")
    @classmethod
    def _user_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_id must not be blank")
        return v.strip()

    @field_validator("categories")
    @classmethod
    def _categories_resolved(cls, v: list[str]) -> list[str]:
        """An event with no resolvable category must never reach a method.

        Readers drop those and count them toward the unresolved-category rate.
        Constructing one here would mean a drop was missed.
        """
        if not v:
            raise ValueError(
                "an Event must carry at least one category -- unresolved events "
                "are dropped by the reader and counted, not passed on"
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def _timestamp_is_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _reversal_carries_its_order(self) -> Event:
        """A reversal without its order_id cannot be aged from the original
        order, which is the one thing a reversal must get right.
        """
        if self.is_reversal:
            if self.event_type is not EventType.PURCHASE:
                raise ValueError("only a purchase can be reversed")
            if not self.order_id:
                raise ValueError(
                    "a reversal must carry order_id -- without it the reversal "
                    "cannot be aged from the original order's creation"
                )
        return self


class ReadStats(BaseModel):
    """What a read dropped, and why.

    Two counters, kept SEPARATE. They say different things: an unresolved
    category is a data-quality problem in the catalogue, a missing timestamp is a
    problem in the event writer, and a future timestamp is a clock problem. One
    combined "dropped" number would hide all three.

    The sub-threshold view rate is deliberately NOT here: P-02 is a tunable and
    the filtering happens in the method, so the reader never sees a view as
    sub-threshold.
    """

    model_config = {"extra": "forbid"}

    read: int = 0

    #: EVENTS dropped because none of their categories resolved.
    unresolved_category: int = 0

    missing_timestamp: int = 0
    future_timestamp: int = 0
    unknown_event_type: int = 0

    #: Individual CATEGORY VALUES dropped, counted separately from the events.
    #: An event tagged with one canonical and one seller-invented category is not
    #: dropped -- but the invented one is, and that has to be visible. Counting
    #: only whole events would report zero for exactly that case.
    unmapped_category_values: int = 0

    #: Which strings were dropped, and how often. The drop rate is a monitored
    #: figure, and "which ones" is the first question anyone asks about it.
    unmapped_examples: dict[str, int] = Field(default_factory=dict)

    def record_unmapped(self, values: list[str]) -> None:
        for value in values:
            self.unmapped_category_values += 1
            self.unmapped_examples[value] = self.unmapped_examples.get(value, 0) + 1

    @property
    def dropped(self) -> int:
        return (
            self.unresolved_category
            + self.missing_timestamp
            + self.future_timestamp
            + self.unknown_event_type
        )

    @property
    def unresolved_category_rate(self) -> float:
        return self.unresolved_category / self.read if self.read else 0.0
