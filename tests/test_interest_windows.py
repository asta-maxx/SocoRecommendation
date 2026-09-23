"""Method two: time windows. Task 15, MB1-MB8."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from reco.config import Settings
from reco.slots.interest.events import Event, EventType
from reco.slots.interest import interest_decay, interest_windows
from reco.slots.interest.context import ScoringContext
from reco.slots.interest.interest_windows import score, window_weight

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def ctx(**overrides) -> ScoringContext:
    fields = {
        "tunables": Settings().tunables(),
        "declared_interests": [],
        "order_created_at": {},
        "now": NOW,
    }
    fields.update(overrides)
    return ScoringContext(**fields)


def event(days_ago: float, event_type=EventType.CLICK, **overrides) -> Event:
    fields = {
        "user_id": "u1",
        "event_type": event_type,
        "categories": ["Fashion & Apparel"],
        "timestamp": NOW - timedelta(days=days_ago),
    }
    fields.update(overrides)
    return Event(**fields)


def raw_of(events, context=None) -> float:
    raws, _ = score(events, context or ctx())
    return raws.get("Fashion & Apparel", 0.0)


# --- MB2: three disjoint windows --------------------------------------------


@pytest.mark.parametrize(
    "age,weight",
    [
        (0, 0.5), (3, 0.5), (7, 0.5),          # recent, inclusive at 7
        (7.1, 0.3), (20, 0.3), (30, 0.3),      # medium, inclusive at 30
        (30.1, 0.2), (60, 0.2), (90, 0.2),     # long, inclusive at 90
        (90.1, 0.0), (120, 0.0),               # beyond the cut-off
    ],
)
def test_each_age_lands_in_exactly_one_window(age: float, weight: float) -> None:
    assert window_weight(age, [7, 30, 90], [0.5, 0.3, 0.2]) == weight


def test_a_five_day_old_event_lands_in_the_recent_window_only(caplog) -> None:
    """MB3, the negative control.

    Nested windows -- "everything in the last 30 days", which includes the last 7
    -- are the more common implementation. Under nesting a five-day-old click
    would be counted three times, once per window it qualifies for, and be worth
    5 x (0.5 + 0.3 + 0.2) = 5.00 instead of 2.50.
    """
    got = raw_of([event(5)])

    assert got == pytest.approx(5 * 0.5)
    assert got != pytest.approx(5 * (0.5 + 0.3 + 0.2))


def test_windows_do_not_double_count_across_boundaries() -> None:
    """One event per window, so the total is the sum of three single hits."""
    events = [event(3), event(20), event(60)]

    assert raw_of(events) == pytest.approx(5 * 0.5 + 5 * 0.3 + 5 * 0.2)


def test_the_weights_of_all_windows_sum_to_one() -> None:
    """MB5. Settings asserts this at load, so a method never has to."""
    assert sum(ctx().window_weights) == pytest.approx(1.0)


# --- MB4: the cut-off -------------------------------------------------------


def test_an_event_past_the_last_boundary_contributes_nothing() -> None:
    """The defining difference between the two methods."""
    assert raw_of([event(91)]) == 0.0
    assert raw_of([event(365)]) == 0.0


def test_events_outside_the_window_are_counted(caplog) -> None:
    """Counted rather than silently absorbed -- the cut-off is the point."""
    _, stats = score([event(5), event(200), event(400)], ctx())

    assert stats.events_outside_window == 2
    assert stats.events_scored == 1


def test_decay_still_counts_what_windows_discard() -> None:
    """Method A's decay never quite reaches zero; Method B discards outright.

    This is the comparison in one assertion.
    """
    old = [event(120)]

    assert raw_of(old) == 0.0
    assert interest_decay.score(old, ctx())[0]["Fashion & Apparel"] > 0


# --- MB5: boundaries and weights are configuration --------------------------


def test_boundaries_come_from_p10() -> None:
    wide = ctx(tunables=Settings(window_boundaries_days=[14, 60, 180]).tunables())

    # 10 days is medium under the launch boundaries, recent under these.
    assert raw_of([event(10)], wide) == pytest.approx(5 * 0.5)
    assert raw_of([event(10)]) == pytest.approx(5 * 0.3)


def test_weights_come_from_p11() -> None:
    flat = ctx(tunables=Settings(window_weights=[0.4, 0.4, 0.2]).tunables())

    assert raw_of([event(20)], flat) == pytest.approx(5 * 0.4)


def test_out_of_range_window_weights_are_refused_at_load() -> None:
    """MB5. A set that does not sum to 1 is a specification error, not a run."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="sum to 1"):
        Settings(window_weights=[0.5, 0.3, 0.3])


# --- MB6: the reversal ------------------------------------------------------


def test_a_reversal_falls_in_the_window_of_the_order_it_reverses() -> None:
    """MB6. Not the window of the cancellation.

    An order placed 20 days ago is medium (0.3). Cancelled 2 days ago, the
    cancellation alone would be recent (0.5) -- and 20 x 0.5 removed against
    20 x 0.3 added would leave the user 4.00 BELOW zero on that category.
    """
    placed = NOW - timedelta(days=20)
    events = [
        event(20, EventType.PURCHASE, order_id="o1"),
        event(2, EventType.PURCHASE, order_id="o1", is_reversal=True),
    ]

    got = raw_of(events, ctx(order_created_at={"o1": placed}))

    assert got == pytest.approx(0.0, abs=1e-12)


def test_aged_from_the_cancellation_it_would_cross_a_window() -> None:
    """Why MB6 exists, as arithmetic."""
    added = 20 * 0.3        # order at 20 days: medium
    removed = 20 * 0.5      # cancellation at 2 days: recent

    assert removed > added
    assert added - removed == pytest.approx(-4.0)


def test_a_reversal_of_an_order_past_the_cut_off_cancels_at_zero() -> None:
    """Both terms are outside the window, so both are worth nothing. The user is
    left where they started, not in deficit.
    """
    placed = NOW - timedelta(days=200)
    events = [
        event(200, EventType.PURCHASE, order_id="o1"),
        event(1, EventType.PURCHASE, order_id="o1", is_reversal=True),
    ]

    assert raw_of(events, ctx(order_created_at={"o1": placed})) == 0.0


# --- MB7: the same floor treatment ------------------------------------------


def test_the_floor_is_added_identically_to_method_a() -> None:
    """MB7. Shared code path, so a difference in outcome between the methods is
    attributable to time treatment alone.
    """
    context = ctx(declared_interests=["Fashion & Apparel"])

    windows, _ = score([], context)
    decay, _ = interest_decay.score([], context)

    assert windows == decay == {"Fashion & Apparel": 10.0}


def test_the_floor_does_not_decay_under_windows_either() -> None:
    """P-26 is No. The floor has no age, so no window applies to it."""
    context = ctx(declared_interests=["Fashion & Apparel"])

    assert raw_of([], context) == 10.0


def test_the_floor_survives_when_every_event_is_past_the_cut_off() -> None:
    """A user whose only activity is ancient still keeps what they declared."""
    context = ctx(declared_interests=["Fashion & Apparel"])

    assert raw_of([event(300)], context) == 10.0


# --- shared behaviour, inherited ---------------------------------------------


def test_the_qualified_view_gate_applies(monkeypatch) -> None:
    _, stats = score([event(1, EventType.VIEW, view_duration_seconds=1.0)], ctx())

    assert stats.sub_threshold_views == 1


def test_multi_category_events_get_full_weight_each() -> None:
    raws, _ = score(
        [event(1, categories=["Fashion & Apparel", "Jewellery"])], ctx()
    )

    assert raws["Fashion & Apparel"] == raws["Jewellery"] == pytest.approx(2.5)


def test_p07_is_not_applied_to_the_reversal() -> None:
    placed = NOW - timedelta(days=20)
    events = [
        event(20, EventType.PURCHASE, order_id="o1"),
        event(2, EventType.PURCHASE, order_id="o1", is_reversal=True),
    ]
    orders = {"o1": placed}

    a = raw_of(events, ctx(order_created_at=orders))
    b = raw_of(
        events,
        ctx(
            order_created_at=orders,
            tunables=Settings(negative_feedback_weight=-20).tunables(),
        ),
    )

    assert a == b == pytest.approx(0.0, abs=1e-12)


# --- MB8: U15 against the hand calculation ----------------------------------

DEMO = Path(__file__).resolve().parents[1] / "reference" / "demo"


def test_u15_matches_the_hand_calculation() -> None:
    """MB8. Six recent, four medium, two long -- computed on paper.

    U15 exists to make the bands visible, so its score is one a person can check:
    each window's events summed at their own weight, and nothing carried across.
    """
    meta_path = DEMO / "ml_demo_meta.json"
    if not meta_path.exists():
        pytest.skip("demo dataset not unpacked")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    reference = datetime.fromisoformat(meta["reference_date"])
    rows = [
        r
        for r in json.loads((DEMO / "ml_demo_events.json").read_text(encoding="utf-8"))
        if r["user_id"] == "U15"
    ]

    boundaries, weights = [7, 30, 90], [0.5, 0.3, 0.2]
    bands = {0: [], 1: [], 2: [], 3: []}
    for r in rows:
        age = (reference - datetime.fromisoformat(r["timestamp"])).total_seconds() / 86400
        band = sum(1 for b in boundaries if age > b)
        bands[band].append(r)

    # The shape U15 was built to have.
    assert (len(bands[0]), len(bands[1]), len(bands[2])) == (6, 4, 2)
    assert bands[3] == []

    by_hand = sum(
        weights[band] * sum(r["weight"] for r in rows_in)
        for band, rows_in in bands.items()
        if band < 3
    )

    events = [
        Event(
            user_id="U15",
            event_type={
                "product_view": EventType.VIEW,
                "product_click": EventType.CLICK,
                "add_to_cart": EventType.CART,
                "purchase": EventType.PURCHASE,
                "keyword_search": EventType.SEARCH,
            }[r["event_type"]],
            categories=r["categories"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            view_duration_seconds=r.get("view_duration_seconds"),
            order_id=r.get("order_id"),
        )
        for r in rows
    ]
    raws, _ = score(events, ctx(now=reference))

    assert raws["Home & Living"] == pytest.approx(by_hand, abs=1e-9)
