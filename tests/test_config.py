"""The environment settings: connections, model identity, what the server provides.

Tunable values are not here any more. They live in the settings file and are
tested in test_tunables.py (ENG-02, SD-07).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reco.config import Settings


def test_tunables_are_not_environment_settings() -> None:
    """SD-07: every tunable lives in the one settings file, not in the environment."""
    fields = set(Settings.model_fields)

    for old in (
        "qualified_view_threshold_seconds", "decay_half_life_days", "event_weights",
        "negative_feedback_weight", "score_staleness_hours", "window_weights",
        "declared_interest_floor", "cold_start_popularity_window_days",
    ):
        assert old not in fields
    assert "settings_file" in fields


def test_blank_model_version_raises() -> None:
    """It is part of the score key -- a blank one makes scores unattributable."""
    with pytest.raises(ValidationError, match="blank"):
        Settings(model_version="   ")


def test_connection_strings_never_appear_in_repr() -> None:
    """A Settings object is printed by pytest fixture headers, FastAPI error
    pages and any log line that formats it. A connection string carries a
    password, so it must not be in the repr -- that is how a live credential
    reaches a transcript or a CI log.
    """
    s = Settings(
        app_mongo_uri="mongodb+srv://user:hunter2@cluster.example.net/",
        app_mongo_db="soco",
        ml_mongo_uri="mongodb+srv://user:hunter2@other.example.net/",
    )

    text = repr(s)

    assert "hunter2" not in text
    assert "mongodb" not in text.lower()
    # Still readable through the attribute -- hidden from repr, not from code.
    assert s.ml_mongo_uri.endswith("other.example.net/")


def test_settings_are_frozen() -> None:
    """Configuration does not change under a running method."""
    s = Settings()

    with pytest.raises(ValidationError):
        s.model_version = "9.9.9"


def test_env_overrides_are_read(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_VERSION", "2.0.0")
    monkeypatch.setenv("SETTINGS_FILE", "/etc/soco/engine.toml")

    s = Settings.from_env()

    assert s.model_version == "2.0.0"
    assert s.settings_file == "/etc/soco/engine.toml"


def test_old_tunable_env_vars_are_ignored(monkeypatch) -> None:
    """The DS-007 P04_... variables no longer set anything: the file does."""
    monkeypatch.setenv("P04_DECAY_HALF_LIFE_DAYS", "500")

    Settings.from_env()  # no error: the variable is simply not read
