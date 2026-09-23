"""Method one: recency decay. RE-03, task 10.

    raw(u, c) = floor(u, c) + SUM over events e of  w(e) * 2 ** (-age_days(e) / H)

    H            = P-04, launch value 30 days
    floor(u, c)  = P-25, launch value 10, if the user declared c at signup
    w(e)         = P-06, keyed on the event type

Base two, so H is directly interpretable: an event exactly one half-life old
contributes half what it did when it happened.

Everything except the decay term is in `methods/common.py`, shared with Method B.
This module is the time treatment and nothing else, which is what makes the
comparison between the two a test of time treatment and nothing else.

A pure function. No database, no I/O, no mutation of its inputs.
`tests/test_method_contract.py` enforces that rather than leaving it to
discipline.
"""

from __future__ import annotations

from collections import defaultdict

from reco.slots.interest.events import Event
from reco.slots.interest.common import (
    SECONDS_PER_DAY,
    MethodStats,
    accumulate,
    apply_declared_floor,
)
from reco.slots.interest.context import ScoringContext


def decay_factor(age_days: float, half_life_days: float) -> float:
    """2 ** (-age / H), clamped so a future event can never amplify.

    A negative age would produce a factor above one and inflate the score
    without bound. Readers already drop future events against the reference
    date; this is the second line, for an event whose timestamp is after `now`
    for any other reason.

    With decay switched off the half-life is infinite, which makes this exactly
    1 for every age -- one formula, no second code path.
    """
    if age_days <= 0:
        return 1.0
    return 2.0 ** (-age_days / half_life_days)


def score(
    events: list[Event],
    ctx: ScoringContext,
) -> tuple[dict[str, float], MethodStats]:
    """One user's raw score per category, and what was dropped while scoring."""

    def time_factor(age: float, category: str) -> float:
        return decay_factor(age, ctx.half_life_for(category))

    return accumulate(events, ctx, time_factor)


def apply_incremental(
    previous_raw: dict[str, float],
    new_events: list[Event],
    ctx: ScoringContext,
    previous_computed_at,
) -> tuple[dict[str, float], MethodStats]:
    """Advance a stored score without replaying history.

        raw_new = raw_old * 2 ** (-delta / H) + sum of the new events

    Exact, not approximate: decaying the old total by the elapsed time is
    algebraically identical to re-decaying every event it contains, because the
    decay factor is exponential and every term shares the same H.

    Method B has no equivalent. Its windows are not exponential, so an event can
    cross a boundary between runs and change weight -- there is no way to advance
    a stored total without knowing which events are near an edge.

    The declared floor is the exception and must not be aged with the rest. It is
    subtracted before the old total is decayed and re-added afterwards --
    otherwise a non-decaying floor decays a little more on every refresh, which
    is a slow leak no single run would reveal.
    """
    delta_days = (ctx.now - previous_computed_at).total_seconds() / SECONDS_PER_DAY

    floor_categories = set(ctx.declared_interests) if ctx.declared_floor else set()

    carried: dict[str, float] = {}
    for category, raw in previous_raw.items():
        body = raw
        if category in floor_categories and not ctx.declared_floor_decays:
            body -= ctx.declared_floor
        carried[category] = max(body, 0.0) * decay_factor(
            delta_days, ctx.half_life_for(category)
        )

    # Score the new events with the floor switched off, so it is added once.
    floorless = ctx.model_copy(update={"declared_interests": []})
    added, stats = score(new_events, floorless)

    merged: dict[str, float] = defaultdict(float, carried)
    for category, raw in added.items():
        merged[category] += raw

    apply_declared_floor(merged, ctx)
    return dict(merged), stats
