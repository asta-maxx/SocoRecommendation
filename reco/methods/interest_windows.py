"""Method two: time windows. RE-04, task 15.

    raw(u, c) = floor(u, c) + SUM over windows k of  v(k) * SUM w(e) for e in k

    Window    Ages          Weight
    Recent    0 to 7 days   0.5      P-10 boundaries, P-11 weights
    Medium    8 to 30 days  0.3
    Long      31 to 90 days 0.2
    --        over 90 days  0        contributes nothing at all

Same inputs, same weights, same floor as Method A. **The only difference is the
treatment of time** -- which is the only thing the comparison is meant to test.
Everything else lives in `methods/common.py` and is shared.

THE WINDOWS ARE DISJOINT
------------------------
An event falls into exactly one. Nested windows -- "everything in the last 30
days" including the last 7 -- are the more common implementation and would count
a recent event three times over, in every window it qualifies for. A five-day-old
event belongs to the recent window and to nothing else.

`test_interest_windows.py` carries that as an explicit negative control.

THE CUT-OFF IS THE DEFINING DIFFERENCE
--------------------------------------
Method A's decay never quite reaches zero: a year-old event still contributes
something tiny. Method B discards anything past the last boundary outright. That
is why U18 exists -- its three events sit at 88, 89 and 92 days, so two count and
one does not.
"""

from __future__ import annotations

from reco.domain.events import Event
from reco.methods.common import MethodStats, accumulate
from reco.methods.context import ScoringContext


def window_weight(
    age_days: float,
    boundaries: list[int],
    weights: list[float],
) -> float:
    """The weight of the single window this age falls into, or 0 beyond the last.

    Boundaries are inclusive upper bounds: with [7, 30, 90], an event at exactly
    7 days is recent, at exactly 30 is medium, at exactly 90 is long, and at 90.1
    is nothing. That matches how the data checks band the same events, so the two
    agree about where U18's cliff falls.

    Returns on the FIRST matching boundary and never accumulates -- that single
    `return` is what keeps the windows disjoint.
    """
    if age_days < 0:
        # A future event. Readers drop these; treat as present-day rather than
        # letting a negative age fall past every boundary and score nothing.
        age_days = 0.0

    for boundary, weight in zip(boundaries, weights):
        if age_days <= boundary:
            return weight
    return 0.0


def score(
    events: list[Event],
    ctx: ScoringContext,
) -> tuple[dict[str, float], MethodStats]:
    """One user's raw score per category, and what was dropped while scoring.

    Identical signature to Method A, so the two are interchangeable behind the
    same slot.
    """
    boundaries = ctx.window_boundaries
    weights = ctx.window_weights

    def time_factor(age: float, category: str) -> float:
        return window_weight(age, boundaries, weights)

    def count_outside(stats: MethodStats) -> None:
        stats.events_outside_window += 1

    return accumulate(events, ctx, time_factor, on_zero_factor=count_outside)
