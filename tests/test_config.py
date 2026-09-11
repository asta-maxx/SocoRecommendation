"""The config layer holds DS-007 v1.1 and refuses values outside its ranges. S4, S5."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reco.config import EventWeights, Settings


def test_launch_values_are_ds007_v11() -> None:
    """If this fails, someone has built from a v1.0 copy."""
    s = Settings()

    assert s.qualified_view_threshold_seconds == 3.0  # P-02
    assert s.decay_half_life_days == 30.0  # P-04
    assert s.per_category_half_life_days == {}  # P-05
    assert s.negative_feedback_weight == 0.0  # P-07
    assert s.score_staleness_hours == 24.0  # P-08
    assert s.refresh_cadence == "daily"  # P-09
    assert s.window_boundaries_days == [7, 30, 90]  # P-10
    assert s.window_weights == [0.5, 0.3, 0.2]  # P-11
    assert s.variant_split_incumbent == 90  # P-22
    assert s.declared_interest_floor == 10.0  # P-25
    assert s.declared_interest_decays is False  # P-26
    assert s.cold_start_popularity_window_days == 30  # P-27


def test_event_weights_are_p06() -> None:
    w = EventWeights()

    assert (w.view, w.click, w.cart, w.purchase, w.search) == (2.0, 5.0, 10.0, 20.0, 3.0)


def test_declared_interest_floor_is_not_an_event_weight() -> None:
    """P-25 is held separately from P-06 in v1.1.

    Folding the floor into the weight table is how it ends up in the event
    stream, where the decay term consumes it.
    """
    assert "declared" not in EventWeights.model_fields
    assert "floor" not in EventWeights.model_fields
    assert "declared_interest_floor" in Settings.model_fields


@pytest.mark.parametrize(
    "field,bad",
    [
        ("qualified_view_threshold_seconds", 0.5),  # P-02 below 1
        ("qualified_view_threshold_seconds", 11.0),  # P-02 above 10
        ("decay_half_life_days", 6.0),  # P-04 below 7
        ("decay_half_life_days", 181.0),  # P-04 above 180
        ("negative_feedback_weight", 1.0),  # P-07 must be <= 0
        ("negative_feedback_weight", -21.0),  # P-07 below -20
        ("score_staleness_hours", 0.5),  # P-08 below 1
        ("score_staleness_hours", 73.0),  # P-08 above 72
        ("variant_split_incumbent", 49),  # P-22 below 50
        ("variant_split_incumbent", 96),  # P-22 above 95
        ("declared_interest_floor", 51.0),  # P-25 above 50
        ("cold_start_popularity_window_days", 6),  # P-27 below 7
        ("cold_start_popularity_window_days", 366),  # P-27 above 365
        ("refresh_cadence", "fortnightly"),  # P-09 not an allowed cadence
    ],
)
def test_out_of_range_parameter_raises(field: str, bad) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: bad})


def test_window_boundaries_must_ascend() -> None:
    """P-10. Descending or equal boundaries make the windows overlap."""
    with pytest.raises(ValidationError, match="ascending"):
        Settings(window_boundaries_days=[30, 7, 90])


def test_window_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        Settings(window_weights=[0.5, 0.3, 0.5])


def test_blank_model_version_raises() -> None:
    """It is part of the score key -- a blank one makes scores unattributable."""
    with pytest.raises(ValidationError, match="blank"):
        Settings(model_version="   ")


def test_tunables_exclude_io_settings() -> None:
    """S5. A method receives parameters and performs no I/O.

    If a connection string can reach a method through ctx.tunables, a method can
    open a database, and the no-I/O half of the method contract stops being
    enforceable.
    """
    tunables = Settings().tunables()

    serialised = str(tunables)
    assert "mongodb://" not in serialised
    assert not any("uri" in key.lower() for key in tunables)
    assert set(tunables) == {
        "P-02", "P-04", "P-05", "P-06", "P-07", "P-08", "P-09",
        "P-10", "P-11", "P-22", "P-25", "P-26", "P-27",
    }


def test_connection_strings_never_appear_in_repr() -> None:
    """A Settings object is printed by pytest fixture headers, FastAPI error
    pages and any log line that formats it. A connection string carries a
    password, so it must not be in the repr -- that is how a live credential
    reaches a transcript or a CI log.
    """
    s = Settings(
        app_mongo_uri="mongodb+srv://user:hunter2@cluster.example.net/",
        ml_mongo_uri="mongodb+srv://user:hunter2@cluster.example.net/",
    )

    text = repr(s)

    assert "hunter2" not in text
    assert "mongodb" not in text.lower()
    # Still readable through the attribute -- hidden from repr, not from code.
    assert s.ml_mongo_uri.endswith("cluster.example.net/")


def test_settings_are_frozen() -> None:
    """Configuration does not change under a running method."""
    s = Settings()

    with pytest.raises(ValidationError):
        s.decay_half_life_days = 60.0


def test_env_overrides_are_read(monkeypatch) -> None:
    monkeypatch.setenv("P04_DECAY_HALF_LIFE_DAYS", "45")
    monkeypatch.setenv("MODEL_VERSION", "2.0.0")

    s = Settings.from_env()

    assert s.decay_half_life_days == 45.0
    assert s.model_version == "2.0.0"


def test_env_override_outside_range_still_raises(monkeypatch) -> None:
    """An env var is not an escape hatch around the DS-007 ranges."""
    monkeypatch.setenv("P04_DECAY_HALF_LIFE_DAYS", "500")

    with pytest.raises(ValidationError):
        Settings.from_env()
