"""The single internal event shape, and the trap it exists to close."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from reco.domain.events import Event, EventType, ReadStats


def make_event(**overrides) -> Event:
    fields = {
        "user_id": "u1",
        "event_type": EventType.VIEW,
        "categories": ["fashion & apparel"],
        "timestamp": datetime.now(timezone.utc) - timedelta(days=1),
    }
    fields.update(overrides)
    return Event(**fields)


def test_event_has_nowhere_to_put_a_row_weight() -> None:
    """The generator writes `weight` onto every demo row, for the data checks'
    arithmetic. If the engine read it, P-06 would stop being configuration:
    retuning a weight would change no score, the config layer would be
    decorative, and nothing would fail loudly to say so.

    The enforcement is that this model has no such field and forbids extras.
    """
    assert "weight" not in Event.model_fields

    with pytest.raises(ValidationError):
        make_event(weight=2.0)


def test_event_carries_no_score() -> None:
    """An event is an observation. What it is worth is P-06's business, decided
    by the method at scoring time.
    """
    assert not {"score", "raw", "delta"} & set(Event.model_fields)


def test_event_without_a_category_is_refused() -> None:
    """Unresolved events are dropped by the reader and counted. Constructing one
    would mean a drop was missed.
    """
    with pytest.raises(ValidationError, match="at least one category"):
        make_event(categories=[])


def test_multi_category_event_keeps_every_category() -> None:
    """A post with several categories contributes FULL weight to each, not a
    divided share -- so the shape must carry them all.
    """
    event = make_event(categories=["fashion & apparel", "home & living"])

    assert len(event.categories) == 2


def test_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_event(timestamp=datetime(2026, 9, 1, 12, 0))


def test_reversal_must_carry_its_order_id() -> None:
    """Without order_id the reversal cannot be aged from the original order,
    which is the one thing a reversal has to get right.
    """
    with pytest.raises(ValidationError, match="order_id"):
        make_event(event_type=EventType.PURCHASE, is_reversal=True)


def test_only_a_purchase_can_be_reversed() -> None:
    with pytest.raises(ValidationError, match="only a purchase"):
        make_event(event_type=EventType.CART, is_reversal=True, order_id="o1")


def test_valid_reversal() -> None:
    event = make_event(
        event_type=EventType.PURCHASE, is_reversal=True, order_id="order-1"
    )

    assert event.is_reversal and event.order_id == "order-1"


def test_event_is_immutable() -> None:
    """A method must not mutate its inputs -- part of the method contract."""
    with pytest.raises(ValidationError):
        make_event().categories = ["books"]


def test_p06_covers_every_event_type() -> None:
    """If a type existed with no weight, it would score zero silently."""
    from reco.config import EventWeights

    assert {t.value for t in EventType} == set(EventWeights.model_fields)


# --- counters ---------------------------------------------------------------


def test_counters_are_kept_separate() -> None:
    """An unresolved category, a missing timestamp and a future timestamp say
    three different things. One combined 'dropped' number hides all three.
    """
    stats = ReadStats(
        read=10, unresolved_category=3, missing_timestamp=1, future_timestamp=2
    )

    assert stats.dropped == 6
    assert stats.unresolved_category_rate == 0.3


def test_sub_threshold_views_are_not_a_reader_counter() -> None:
    """P-02 is a tunable, so the filtering happens in the method. A reader that
    filtered on it would be making a scoring decision.
    """
    assert not any("threshold" in f or "duration" in f for f in ReadStats.model_fields)


def test_empty_read_has_no_rate() -> None:
    assert ReadStats().unresolved_category_rate == 0.0
