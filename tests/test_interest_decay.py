"""Method A's own behaviour, on events built for the purpose.

The expected-value suite proves it reproduces the generator. These prove the
individual rules hold for reasons anyone can follow from the numbers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reco.config import Settings
from reco.slots.interest.events import Event, EventType
from reco.slots.interest.context import ScoringContext
from reco.slots.interest.interest_decay import apply_incremental, decay_factor, score
from tests.conftest import m1_tunables

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def ctx(**overrides) -> ScoringContext:
    fields = {
        "tunables": m1_tunables(),
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


# --- the decay term ---------------------------------------------------------


def test_one_half_life_halves_the_contribution() -> None:
    """Base two is the whole point: H is directly interpretable."""
    assert decay_factor(30, 30) == pytest.approx(0.5)
    assert decay_factor(60, 30) == pytest.approx(0.25)
    assert decay_factor(0, 30) == 1.0


def test_a_click_today_is_worth_its_full_weight() -> None:
    raws, _ = score([event(0)], ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(5.0)


def test_a_click_one_half_life_old_is_worth_half() -> None:
    raws, _ = score([event(30)], ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(2.5)


def test_a_future_event_cannot_amplify() -> None:
    """Readers drop these against the reference date. This is the second line:
    a negative age would give a factor above one and inflate without bound.
    """
    raws, _ = score([event(-10)], ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(5.0)


def test_half_life_comes_from_configuration() -> None:
    slow = ctx(tunables=m1_tunables({"interest.half_life_days": 60}))

    raws, _ = score([event(60)], slow)

    assert raws["Fashion & Apparel"] == pytest.approx(2.5)


def test_p05_overrides_the_half_life_for_one_category() -> None:
    """Launch value is none, but a parameter the engine ignores is not really
    configuration. Fashion turns over faster than furniture.
    """
    tunables = m1_tunables({"interest.per_category_half_life_days": {"Fashion & Apparel": 15}})
    events = [event(30), event(30, categories=["Home & Living"])]

    raws, _ = score(events, ctx(tunables=tunables))

    assert raws["Fashion & Apparel"] == pytest.approx(5 * 2 ** (-30 / 15))
    assert raws["Home & Living"] == pytest.approx(2.5)


# --- the qualified view gate ------------------------------------------------


def test_a_sub_threshold_view_contributes_nothing() -> None:
    raws, stats = score(
        [event(0, EventType.VIEW, view_duration_seconds=1.0)], ctx()
    )

    assert raws == {}
    assert stats.sub_threshold_views == 1


def test_a_qualified_view_counts() -> None:
    raws, stats = score(
        [event(0, EventType.VIEW, view_duration_seconds=6.0)], ctx()
    )

    assert raws["Fashion & Apparel"] == pytest.approx(2.0)
    assert stats.sub_threshold_views == 0


def test_exactly_at_the_threshold_qualifies() -> None:
    """P-02 is 3 seconds and the gate is 'below', so 3.0 counts."""
    raws, _ = score([event(0, EventType.VIEW, view_duration_seconds=3.0)], ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(2.0)


def test_a_view_with_no_duration_is_counted_separately() -> None:
    """Neither qualified nor below threshold -- a third case the specification
    does not name. Live postevents populates the field on some views only.
    """
    raws, stats = score([event(0, EventType.VIEW)], ctx())

    assert raws == {}
    assert stats.views_without_duration == 1
    assert stats.sub_threshold_views == 0


def test_the_threshold_comes_from_configuration() -> None:
    lenient = ctx(tunables=m1_tunables({"events.qualified_view_seconds": 1}))

    raws, _ = score([event(0, EventType.VIEW, view_duration_seconds=1.5)], lenient)

    assert raws["Fashion & Apparel"] == pytest.approx(2.0)


def test_the_gate_applies_only_to_views() -> None:
    """A click has no duration and must not be dropped for lacking one."""
    raws, stats = score([event(0, EventType.CLICK)], ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(5.0)
    assert stats.views_without_duration == 0


# --- multi-category ---------------------------------------------------------


def test_each_category_gets_the_full_weight() -> None:
    raws, _ = score(
        [event(0, categories=["Fashion & Apparel", "Jewellery", "Technology"])],
        ctx(),
    )

    assert list(raws.values()) == [5.0, 5.0, 5.0]


def test_categories_are_kept_as_supplied() -> None:
    """No hardcoded list anywhere. Legacy and unmappable values score under
    exactly the string the source gave, which is what U06 and U08 demonstrate.
    """
    raws, _ = score([event(0, categories=["home & decor", "Casual Sneakers"])], ctx())

    assert set(raws) == {"home & decor", "Casual Sneakers"}


# --- the declared floor -----------------------------------------------------


def test_the_floor_applies_without_any_events() -> None:
    raws, _ = score([], ctx(declared_interests=["Fashion & Apparel"]))

    assert raws == {"Fashion & Apparel": 10.0}


def test_the_floor_does_not_decay() -> None:
    """P-26 is No at launch, so the signup date is irrelevant."""
    raws, _ = score([], ctx(declared_interests=["Fashion & Apparel"]))
    assert raws["Fashion & Apparel"] == 10.0


def test_the_floor_adds_to_events_rather_than_replacing_them() -> None:
    raws, _ = score([event(0)], ctx(declared_interests=["Fashion & Apparel"]))

    assert raws["Fashion & Apparel"] == pytest.approx(15.0)


def test_the_floor_comes_from_configuration() -> None:
    raised = ctx(
        declared_interests=["Fashion & Apparel"],
        tunables=m1_tunables({"interest.declared_floor": 25}),
    )

    raws, _ = score([], raised)

    assert raws["Fashion & Apparel"] == 25.0


def test_a_zero_floor_stores_nothing_for_a_user_with_no_events() -> None:
    zeroed = ctx(
        declared_interests=["Fashion & Apparel"],
        tunables=m1_tunables({"interest.declared_floor": 0}),
    )

    assert score([], zeroed)[0] == {}


# --- the purchase and its reversal ------------------------------------------


def test_a_purchase_counts_at_order_creation() -> None:
    """Not at delivery. M1 measures interest, not commercial outcome -- under
    cash on delivery, waiting would leave the profile blind for a fortnight.
    """
    raws, _ = score([event(0, EventType.PURCHASE, order_id="o1")], ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(20.0)


def test_a_reversal_aged_from_the_original_order_cancels_exactly() -> None:
    """The single most important number in the build.

    An order placed 12 days ago, cancelled 5 days ago. Aged from the order, the
    two terms are equal and opposite and the user lands on zero.
    """
    placed = NOW - timedelta(days=12)
    events = [
        event(12, EventType.PURCHASE, order_id="o1"),
        event(5, EventType.PURCHASE, order_id="o1", is_reversal=True),
    ]

    raws, stats = score(events, ctx(order_created_at={"o1": placed}))

    assert raws["Fashion & Apparel"] == pytest.approx(0.0, abs=1e-12)
    assert stats.reversals_applied == 1
    assert stats.reversals_unaged == 0


def test_aged_from_the_cancellation_it_would_overshoot() -> None:
    """Why the rule exists, shown as arithmetic.

    The cancellation is more recent, so it decays less, so it removes more than
    the purchase ever added -- and the raw goes negative, which then normalises
    into a negative share.
    """
    from_order = 20 * 2 ** (-12 / 30)
    from_cancellation = 20 * 2 ** (-5 / 30)

    assert from_cancellation > from_order
    assert from_order - from_cancellation < 0


def test_a_reversal_without_its_order_is_logged_loudly(caplog) -> None:
    """It still applies, aged from its own timestamp -- but nothing silently
    pretends the score is right.
    """
    import logging

    events = [event(5, EventType.PURCHASE, order_id="o1", is_reversal=True)]

    with caplog.at_level(logging.ERROR, logger="reco.slots.interest.interest_decay"):
        _, stats = score(events, ctx())

    assert stats.reversals_unaged == 1
    assert "aged from the cancellation" in caplog.text


def test_p07_is_not_applied_to_the_reversal() -> None:
    """P-07 governs hide, report and skip, and is zero at launch. Multiplying
    the reversal by it would zero the reversal, the profile would never correct
    itself, and nothing in the logs would say so.
    """
    placed = NOW - timedelta(days=12)
    events = [
        event(12, EventType.PURCHASE, order_id="o1"),
        event(5, EventType.PURCHASE, order_id="o1", is_reversal=True),
    ]

    with_p07_zero = ctx(order_created_at={"o1": placed})
    with_p07_set = ctx(
        order_created_at={"o1": placed},
        tunables=m1_tunables({"interest.weights.not_interested_or_hide": -20}),
    )

    a, _ = score(events, with_p07_zero)
    b, _ = score(events, with_p07_set)

    # P-07 does not touch this path at all, so changing it changes nothing.
    assert a == b
    assert a["Fashion & Apparel"] == pytest.approx(0.0, abs=1e-12)


# --- decay disabled ---------------------------------------------------------


def test_events_of_age_zero_give_exactly_the_weighted_sum() -> None:
    """The decay term is the ONLY thing separating this from a plain weighted
    sum. At age zero every factor is exactly one, so the two coincide.
    """
    events = [event(0), event(0, EventType.VIEW, view_duration_seconds=6.0)]

    raws, _ = score(events, ctx())

    assert raws["Fashion & Apparel"] == pytest.approx(5.0 + 2.0)


def test_a_longer_half_life_moves_the_score_toward_the_plain_sum() -> None:
    """H -> infinity makes every factor approach one. P-04 is capped at 180, so
    this asserts the direction and the convergence rather than the limit itself.

    This was the precondition for the conformance check. Conformance is out of
    scope now, but the relationship is still the clearest statement of what
    decay is doing.
    """
    events = [event(0), event(1), event(2)]
    plain_sum = 15.0

    fast, _ = score(events, ctx(tunables=m1_tunables({"interest.half_life_days": 7})))
    launch, _ = score(events, ctx())
    slow, _ = score(events, ctx(tunables=m1_tunables({"interest.half_life_days": 180})))

    fast_v = fast["Fashion & Apparel"]
    launch_v = launch["Fashion & Apparel"]
    slow_v = slow["Fashion & Apparel"]

    assert fast_v < launch_v < slow_v < plain_sum
    assert plain_sum - slow_v < 0.06  # within 0.4 percent at the range maximum


# --- the incremental path ---------------------------------------------------


def test_incremental_equals_a_full_recomputation() -> None:
    """The only way to detect drift between the fast path and the truth."""
    old_events = [event(40), event(35, EventType.VIEW, view_duration_seconds=6.0)]
    new_events = [event(2), event(1, EventType.CART)]
    last_run = NOW - timedelta(days=10)

    at_last_run = ctx(now=last_run)
    previous, _ = score(
        [e for e in old_events if e.timestamp <= last_run], at_last_run
    )

    incremental, _ = apply_incremental(previous, new_events, ctx(), last_run)
    full, _ = score(old_events + new_events, ctx())

    assert incremental.keys() == full.keys()
    for category in full:
        assert incremental[category] == pytest.approx(full[category], rel=1e-9)


def test_incremental_keeps_the_floor_from_decaying() -> None:
    """The floor is subtracted before the old total is decayed and re-added
    afterwards. Without that it decays a little on every refresh -- a slow leak
    no single run would reveal.
    """
    declared = ["Fashion & Apparel"]
    last_run = NOW - timedelta(days=30)

    previous, _ = score([], ctx(now=last_run, declared_interests=declared))
    assert previous == {"Fashion & Apparel": 10.0}

    after, _ = apply_incremental(
        previous, [], ctx(declared_interests=declared), last_run
    )

    assert after["Fashion & Apparel"] == pytest.approx(10.0)


def test_incremental_over_many_refreshes_does_not_drift() -> None:
    """Ten daily refreshes must land where one ten-day recomputation does."""
    declared = ["Fashion & Apparel"]
    start = NOW - timedelta(days=10)

    running, _ = score([event(20)], ctx(now=start, declared_interests=declared))
    for day in range(10, 0, -1):
        at = NOW - timedelta(days=day - 1)
        running, _ = apply_incremental(
            running, [], ctx(now=at, declared_interests=declared), at - timedelta(days=1)
        )

    full, _ = score([event(20)], ctx(declared_interests=declared))

    assert running["Fashion & Apparel"] == pytest.approx(
        full["Fashion & Apparel"], rel=1e-9
    )
