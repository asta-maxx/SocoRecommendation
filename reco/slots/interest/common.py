"""Everything the two methods share, which is everything except time.

Method A and Method B read identical inputs, apply identical weights, and add the
declared floor identically. **The only difference between them is how they treat
time.** That is deliberate: it makes the comparison a test of time-treatment and
nothing else.

So the shared work lives here once, and each method supplies a single function:

    time_factor(age_days, category) -> float

Method A returns `2 ** (-age / H)`. Method B returns the weight of the window the
age falls into, or 0 beyond the last boundary.

Sharing the code rather than writing it twice is what makes the claim true. Two
copies of the qualified-view gate would drift, and a difference in outcome would
no longer be attributable to time alone -- which is the only thing the
demonstration is comparing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable, Protocol

from reco.slots.interest.events import Event, EventType
from reco.slots.interest.context import ScoringContext

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400.0

#: Event type -> the P-06 weight key. The internal vocabulary and the parameter
#: vocabulary are separate, and this is where they meet.
WEIGHT_KEY = {
    EventType.VIEW: "view",
    EventType.CLICK: "click",
    EventType.CART: "cart",
    EventType.PURCHASE: "purchase",
    EventType.SEARCH: "search",
}


class TimeFactor(Protocol):
    """How much an event of this age, in this category, still counts."""

    def __call__(self, age_days: float, category: str) -> float: ...


class MethodStats:
    """What a method dropped while scoring, and why.

    The sub-threshold-view count lives here rather than with the reader's
    counters because P-02 is a tunable: a reader that filtered on it would be
    making a scoring decision, and changing P-02 would then need a different
    reader. It is reported separately from the reader's unresolved-category and
    timestamp counters -- the three say different things.
    """

    __slots__ = (
        "sub_threshold_views",
        "views_without_duration",
        "reversals_applied",
        "reversals_unaged",
        "events_scored",
        "events_outside_window",
        "contributions",
    )

    def __init__(self) -> None:
        self.sub_threshold_views = 0
        self.views_without_duration = 0
        self.reversals_applied = 0
        self.reversals_unaged = 0
        self.events_scored = 0
        #: Method B only: older than the last boundary, so worth nothing. The
        #: cut-off is the defining difference between the two methods, so it is
        #: counted rather than silently absorbed.
        self.events_outside_window = 0

        #: category -> how many events actually CONTRIBUTED to its raw score.
        #:
        #: The stored `event_count` comes from here rather than from counting the
        #: user's events by category. Those are different numbers: U02 has twenty
        #: views of one category and eight that qualify, and showing 20 beside a
        #: score built from 8 invites exactly the question the number was meant to
        #: answer. An event that was gated out, or that fell past Method B's
        #: cut-off, contributed nothing and is not counted here.
        self.contributions: dict[str, int] = {}

    def as_dict(self) -> dict[str, int]:
        return {
            name: getattr(self, name)
            for name in self.__slots__
            if name != "contributions"
        }


#: Kept for readers of the older name.
DecayStats = MethodStats


def age_days(ctx: ScoringContext, event: Event) -> float:
    """How old the event is, in days, as of ctx.now.

    For a reversal this is the age of the ORIGINAL ORDER, not of the
    cancellation. A cancellation is always more recent than the order it cancels,
    so under decay it would fade less and remove more than the purchase added;
    under windows it could land in a nearer window and cancel the wrong amount.
    Aged from the order, the two terms cancel exactly under both methods -- which
    is the point of doing it here, once, for both.
    """
    at = event.timestamp
    if event.is_reversal and event.order_id:
        placed = ctx.order_created_at.get(event.order_id)
        if placed is not None:
            at = placed
    return (ctx.now - at).total_seconds() / SECONDS_PER_DAY


def weight_of(ctx: ScoringContext, event: Event) -> float:
    """What P-06 says this event contributes, before time is applied.

    A reversal is the purchase weight negated. It is NOT governed by P-07 --
    P-07 is negative feedback (hide, report, skip) and is zero at launch, so
    multiplying the reversal by it would zero the reversal and the profile would
    never correct itself, with nothing in the logs to say so.
    """
    weight = float(ctx.event_weights[WEIGHT_KEY[event.event_type]])
    return -weight if event.is_reversal else weight


def accumulate(
    events: list[Event],
    ctx: ScoringContext,
    time_factor: TimeFactor,
    *,
    on_zero_factor: Callable[[MethodStats], None] | None = None,
) -> tuple[dict[str, float], MethodStats]:
    """The shared scoring loop. Everything but the treatment of time.

    Returns raw only. Normalising to shares belongs to `domain.scores`, because a
    share is a property of the whole map rather than of any one category, and
    both methods normalise identically.
    """
    raws: dict[str, float] = defaultdict(float)
    stats = MethodStats()

    for event in events:
        if event.event_type is EventType.VIEW:
            duration = event.view_duration_seconds
            if duration is None:
                # Neither qualified nor below threshold -- a third case the
                # specification does not name. Counted separately and not
                # scored, so an unrecorded duration never silently becomes a
                # qualified view. Live postevents populates the field on some
                # views only; generated rows always carry it.
                stats.views_without_duration += 1
                continue
            if duration < ctx.qualified_view_seconds:
                stats.sub_threshold_views += 1
                continue

        if event.is_reversal:
            stats.reversals_applied += 1
            if not (event.order_id and event.order_id in ctx.order_created_at):
                # Aged from its own timestamp, which is the cancellation -- the
                # error both methods exist to avoid. Loud, because the resulting
                # score is wrong in a way no later check attributes correctly.
                stats.reversals_unaged += 1
                logger.error(
                    "reversal for order %r has no creation timestamp in the "
                    "context; it will be aged from the cancellation and will "
                    "remove more than the purchase added",
                    event.order_id,
                )

        weight = weight_of(ctx, event)
        age = age_days(ctx, event)
        contributed = False

        for category in event.categories:
            # Full weight to EACH category, never a divided share. A post tagged
            # with three categories is three full contributions.
            factor = time_factor(age, category)
            raws[category] += weight * factor
            if factor:
                contributed = True
                stats.contributions[category] = stats.contributions.get(category, 0) + 1
            else:
                # Keep the category in the map at zero. It was seen and it scored
                # nothing -- which for Method B is the cut-off doing its job, and
                # is worth showing rather than hiding.
                raws.setdefault(category, 0.0)

        if contributed:
            stats.events_scored += 1
        elif on_zero_factor is not None:
            on_zero_factor(stats)

    apply_declared_floor(raws, ctx)
    return dict(raws), stats


def apply_declared_floor(raws: dict[str, float], ctx: ScoringContext) -> None:
    """Add P-25 to every category the user declared at signup.

    Shared by both methods on purpose (MB7): the floor is added identically, so a
    difference in outcome between them is attributable to time treatment alone.

    It is not an event. It carries no timestamp and never reaches the event
    stream. P-26 decides whether it decays; at launch it does not, so a user who
    declared an interest and then browsed lightly for three months keeps it --
    which is exactly the user who most needs the declaration to hold.
    """
    if not ctx.declared_floor:
        return
    for category in ctx.declared_interests:
        raws[category] += ctx.declared_floor
