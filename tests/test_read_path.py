"""The fallback ladder. ENG-09 (Build List v1.3), SD-23.

The engine store and the platform are stubbed, so every rung can be reached
deliberately rather than by arranging the right database state. The check of
the row -- "Test users for each rung get the right rung reported" -- is the
rung tests below, one user per rung, plus test_each_rung_is_reported_on_the_list
in test_recommendations.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from reco.config import Settings
from reco.fallback.profile import Rung, evenly_spread
from reco.fallback.read_path import get_profile, is_stale
from reco.store.scores import InterestScore, Method, Window
from tests.conftest import put_in_force

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings() -> Settings:
    return Settings(data_profile="demo", model_version="test-1.0.0")


@pytest.fixture
def world(monkeypatch):
    """Everything the ladder reads, controllable from a test."""
    import reco.fallback.read_path as read_path
    from reco.platform import fetch
    from reco.store import writers

    state = {
        "scores": [], "actions": 0, "follows": 0, "declared": [], "delivered": None,
        "popularity": [], "store_down": False, "platform_down": False, "popularity_reads": 0,
    }

    async def scores(settings, user_id, method, model_version=None):
        if state["store_down"]:
            raise ConnectionError("engine store unreachable")
        return list(state["scores"])

    async def actions(settings, user_id, since, view_ms, enough):
        if state["store_down"]:
            raise ConnectionError("engine store unreachable")
        state["asked"] = {"since": since, "view_ms": view_ms, "enough": enough}
        return min(state["actions"], enough)

    async def user_with(settings, user_id, extra=()):
        if state["platform_down"]:
            raise ConnectionError("platform unreachable")
        return SimpleNamespace(declared_interests=list(state["declared"])), {f: state["delivered"] for f in extra}

    async def follows(settings, user_id, since):
        return state["follows"]

    async def popularity(settings):
        state["popularity_reads"] += 1
        return list(state["popularity"])

    monkeypatch.setattr(read_path, "read_user_scores", scores)
    monkeypatch.setattr(writers, "count_qualified_actions", actions)
    monkeypatch.setattr(writers, "read_popularity", popularity)
    monkeypatch.setattr(fetch, "read_user_with", user_with)
    monkeypatch.setattr(fetch, "read_business_follows", follows)
    return state


def score(category: str, share: float, age_hours: float = 1.0, raw: float | None = None, event_count: int = 3):
    return InterestScore(
        user_id="u", category=category, raw=share * 100 if raw is None else raw, share=share,
        event_count=event_count, method=Method.RECENCY_DECAY, model_version="test-1.0.0",
        window=Window.ALL, computed_at=NOW - timedelta(hours=age_hours),
    )


def popular(**views: int) -> list[dict]:
    return [{"category": c.replace("_", " "), "qualified_views": n} for c, n in views.items()]


# --- rung 1 -------------------------------------------------------------------------------


async def test_rung_1_five_actions_and_a_fresh_score(world, settings) -> None:
    world["actions"] = 5
    world["scores"] = [score("Electronics", 0.3), score("Fashion & Apparel", 0.7)]

    p = await get_profile(settings, "u1", reference_date=NOW)

    assert p.rung is Rung.PERSONALISED and p.fallback_step is None
    assert [c.category for c in p.categories] == ["Fashion & Apparel", "Electronics"]
    assert p.method == "recency_decay" and p.personalised and not p.cold_start


async def test_the_count_is_over_90_days_with_3_second_views_and_stops_at_5(world, settings) -> None:
    world["actions"] = 9
    world["scores"] = [score("Books", 1.0)]

    await get_profile(settings, "u1", reference_date=NOW)

    assert world["asked"] == {"since": NOW - timedelta(days=90), "view_ms": 3000, "enough": 5}


async def test_business_follows_count_towards_the_five(world, settings) -> None:
    world["actions"], world["follows"] = 3, 2
    world["scores"] = [score("Books", 1.0)]

    assert (await get_profile(settings, "u1", reference_date=NOW)).rung is Rung.PERSONALISED


# --- rung 2 -------------------------------------------------------------------------------


async def test_rung_2_fewer_than_five_with_declared_interests_uses_floor_plus_actions(world, settings) -> None:
    """The nightly score is the floor plus the actions (ENG-10), so rung 2 serves it."""
    world["actions"] = 4
    world["declared"] = ["Books", "Pets"]
    world["scores"] = [score("Books", 0.6), score("Pets", 0.4)]

    p = await get_profile(settings, "u2", reference_date=NOW)

    assert p.rung is Rung.DECLARED_ONLY and p.fallback_step == "rung_2"
    assert [c.share for c in p.categories] == [0.6, 0.4]
    assert p.cold_start and p.personalised


async def test_rung_2_without_a_usable_score_is_the_floor_spread_evenly(world, settings) -> None:
    """Signed up, picked interests, nothing scored yet: the common case at launch."""
    world["declared"] = ["Fashion & Apparel", "Books", "Pets"]

    p = await get_profile(settings, "u2", reference_date=NOW)

    assert p.rung is Rung.DECLARED_ONLY and p.method is None
    assert all(c.share == pytest.approx(1 / 3) for c in p.categories)


async def test_rung_2_comes_before_rung_4_for_a_new_user(world, settings) -> None:
    """First match wins: a user with fewer than 5 actions is rung 2, stale score or not."""
    world["actions"] = 1
    world["declared"] = ["Books"]
    world["scores"] = [score("Books", 1.0, age_hours=100)]

    p = await get_profile(settings, "u2", reference_date=NOW)

    assert p.rung is Rung.DECLARED_ONLY and p.categories[0].share == 1.0


# --- rung 3 -------------------------------------------------------------------------------


async def test_rung_3_fewer_than_five_and_nothing_declared_is_platform_popularity(world, settings) -> None:
    world["actions"] = 2
    world["popularity"] = popular(Books=30, Pets=10)

    p = await get_profile(settings, "u3", reference_date=NOW)

    assert p.rung is Rung.POPULARITY and p.fallback_step == "rung_3"
    assert [(c.category, c.share) for c in p.categories] == [("Books", 0.75), ("Pets", 0.25)]
    assert p.personalised is False and p.cold_start and p.popularity_window_days == 30


async def test_rung_3_empty_names_itself(world, settings, caplog) -> None:
    """A new platform with no qualified views: the list is eligible posts newest first."""
    with caplog.at_level(logging.WARNING, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u3", reference_date=NOW)

    assert p.categories == [] and p.fallback_step == "rung_3_empty"
    assert "RUNG 3 EMPTY" in caplog.text


async def test_an_unknown_user_is_rung_3(world, settings) -> None:
    world["popularity"] = popular(Books=1)

    assert (await get_profile(settings, "nobody", reference_date=NOW)).rung is Rung.POPULARITY


# --- rung 4 -------------------------------------------------------------------------------


async def test_rung_4_a_stale_score_serves_the_old_delivered_score(world, settings, caplog) -> None:
    world["actions"] = 6
    world["scores"] = [score("Books", 1.0, age_hours=49)]
    world["delivered"] = {"home & living": 30, "Pets": 10, "Books": 99, "Electronics": -5}

    with caplog.at_level(logging.WARNING, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u4", reference_date=NOW)

    assert p.rung is Rung.STALE and p.fallback_step == "rung_4" and not p.cold_start
    # matched to the 23 by name (case ignored); unmatched dropped; below 0 clipped
    assert [(c.category, c.share) for c in p.categories] == [("Home & Living", 0.75), ("Pets", 0.25), ("Electronics", 0.0)]
    assert "REFRESH" in caplog.text


async def test_rung_4_without_a_delivered_score_falls_to_rung_3(world, settings) -> None:
    world["actions"] = 6
    world["scores"] = [score("Books", 1.0, age_hours=49)]
    world["popularity"] = popular(Pets=4)

    p = await get_profile(settings, "u4", reference_date=NOW)

    assert p.rung is Rung.POPULARITY and p.fell_through_from is Rung.STALE
    assert p.fallback_step == "rung_4_to_3" and not p.cold_start


@pytest.mark.parametrize("stored", [
    [score("Books", 0.6), score("Pets", 0.3)],  # shares sum to 0.9
    [score("Books", 0.5), score("Books", 0.5)],  # a category twice
    [],  # 5 actions but no score at all
], ids=["shares", "repeated", "missing"])
async def test_rung_4_a_score_that_fails_its_checks(world, settings, stored) -> None:
    world["actions"] = 5
    world["scores"] = stored

    assert (await get_profile(settings, "u4", reference_date=NOW)).fell_through_from is Rung.STALE


async def test_the_48_hour_limit_is_the_setting(world, settings) -> None:
    world["actions"] = 5
    world["scores"] = [score("Books", 1.0, age_hours=47)]
    assert (await get_profile(settings, "u", reference_date=NOW)).rung is Rung.PERSONALISED

    put_in_force({"interest": {"stale_after_hours": 24}})
    assert (await get_profile(settings, "u", reference_date=NOW)).fell_through_from is Rung.STALE


# --- rung 5 -------------------------------------------------------------------------------


async def test_rung_5_an_unreadable_store_serves_the_delivered_score_at_once(world, settings, caplog) -> None:
    world["store_down"] = True
    world["delivered"] = {"Pets": 2}

    with caplog.at_level(logging.WARNING, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u5", reference_date=NOW)

    assert p.rung is Rung.UNAVAILABLE and p.fallback_step == "rung_5"
    assert "SERVING" in caplog.text


async def test_rung_5_without_a_delivered_score_is_an_error_at_once(world, settings) -> None:
    """Kala, 16 Oct (2d): rung 3 needs the engine store too, so there is no rung_5_to_3.
    The request answers 503 and SOCO_BE shows its own ordering (SD-26)."""
    from reco.fallback.read_path import EngineStoreUnavailable

    world["store_down"] = True
    world["popularity"] = popular(Books=1)

    with pytest.raises(EngineStoreUnavailable):
        await get_profile(settings, "u5", reference_date=NOW)
    assert world["popularity_reads"] == 0


async def test_a_platform_fault_is_not_a_rung(world, settings) -> None:
    """The ladder covers the engine's own store; a platform fault is the request's 503."""
    world["platform_down"] = True

    with pytest.raises(ConnectionError):
        await get_profile(settings, "u", reference_date=NOW)


# --- helpers --------------------------------------------------------------------------------


def test_is_stale_boundary() -> None:
    assert not is_stale(NOW - timedelta(hours=48), NOW, 48)
    assert is_stale(NOW - timedelta(hours=48, seconds=1), NOW, 48)


def test_evenly_spread_ignores_blanks_and_repeats() -> None:
    assert [c.category for c in evenly_spread(["Books", "", "Books", "Pets"])] == ["Books", "Pets"]
