"""The fallback ladder. Task 17.

The store and the readers are stubbed, so every rung can be reached deliberately
rather than by arranging the right database state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from reco.config import Settings
from reco.fallback.profile import Profile, Rung, evenly_spread
from reco.store.scores import InterestScore, Method, Window
from reco.fallback.read_path import get_profile, is_stale

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings() -> Settings:
    return Settings(data_profile="demo", model_version="test-1.0.0")


@pytest.fixture
def world(monkeypatch):
    """Everything the read path depends on, controllable from a test."""
    from reco.platform import readers
    import reco.fallback.read_path as read_path

    state = {"scores": [], "declared": {}, "popularity": {}, "raise_on_read": False}

    async def fake_scores(settings, user_id, method, model_version=None):
        if state["raise_on_read"]:
            raise ConnectionError("score store unreachable")
        return [s for s in state["scores"] if s.user_id == user_id]

    async def fake_declared(settings, user_id):
        return state["declared"].get(user_id, [])

    async def fake_popularity(settings, window_days, reference_date=None):
        return dict(state["popularity"])

    monkeypatch.setattr(read_path, "read_user_scores", fake_scores)
    monkeypatch.setattr(readers, "read_declared_interests", fake_declared)
    monkeypatch.setattr(readers, "read_category_popularity", fake_popularity)
    return state


def score(
    user_id: str,
    category: str,
    share: float,
    age_hours: float = 1.0,
    event_count: int = 3,
):
    return InterestScore(
        user_id=user_id,
        category=category,
        raw=share * 100,
        share=share,
        event_count=event_count,
        method=Method.RECENCY_DECAY,
        model_version="test-1.0.0",
        window=Window.ALL,
        computed_at=NOW - timedelta(hours=age_hours),
    )


# --- rung 1 -----------------------------------------------------------------


async def test_rung_1_serves_the_stored_score(world, settings) -> None:
    world["scores"] = [
        score("u1", "Fashion & Apparel", 0.7),
        score("u1", "Electronics", 0.3),
    ]

    p = await get_profile(settings, "u1", reference_date=NOW)

    assert p.rung is Rung.PERSONALISED
    assert p.personalised is True
    assert [c.category for c in p.categories] == ["Fashion & Apparel", "Electronics"]
    assert p.method == "recency_decay"
    assert p.computed_at is not None


async def test_rung_1_orders_by_share(world, settings) -> None:
    world["scores"] = [
        score("u1", "Books", 0.2),
        score("u1", "Fashion & Apparel", 0.5),
        score("u1", "Electronics", 0.3),
    ]

    p = await get_profile(settings, "u1", reference_date=NOW)

    assert [c.share for c in p.categories] == [0.5, 0.3, 0.2]


# --- rung 2 -----------------------------------------------------------------


async def test_rung_2_serves_the_declared_interests(world, settings) -> None:
    """The common case at launch: signed up, picked interests, done nothing."""
    world["declared"] = {"u7": ["Fashion & Apparel", "Books", "Pets"]}

    p = await get_profile(settings, "u7", reference_date=NOW)

    assert p.rung is Rung.DECLARED_ONLY
    assert len(p.categories) == 3
    assert all(c.share == pytest.approx(1 / 3) for c in p.categories)


async def test_rung_2_is_marked_personalised(world, settings) -> None:
    """It is about this user specifically, unlike rung 3."""
    world["declared"] = {"u7": ["Books"]}

    assert (await get_profile(settings, "u7", reference_date=NOW)).personalised is True


async def test_rung_2_carries_no_method(world, settings) -> None:
    """No method computed it -- claiming one would misattribute the answer."""
    world["declared"] = {"u7": ["Books"]}

    p = await get_profile(settings, "u7", reference_date=NOW)

    assert p.method is None
    assert p.model_version == "test-1.0.0"


async def test_a_floor_only_score_is_rung_2_not_rung_1(world, settings) -> None:
    """The refresh writes a score for a user who declared interests and has done
    nothing -- every category at the floor, zero events behind it.

    Rung 1's condition is "has activity AND a fresh score", not "has a row in the
    store". Keying it on the row's existence makes rung 2 unreachable, and rung 2
    is the common case at launch.
    """
    world["scores"] = [
        score("u7", "Fashion & Apparel", 0.5, event_count=0),
        score("u7", "Books", 0.5, event_count=0),
    ]

    p = await get_profile(settings, "u7", reference_date=NOW)

    assert p.rung is Rung.DECLARED_ONLY
    assert p.personalised is True
    assert p.method is None


async def test_one_event_is_enough_for_rung_1(world, settings) -> None:
    """The distinction is any activity at all, not a threshold."""
    world["scores"] = [
        score("u1", "Fashion & Apparel", 0.5, event_count=1),
        score("u1", "Books", 0.5, event_count=0),
    ]

    assert (await get_profile(settings, "u1", reference_date=NOW)).rung is Rung.PERSONALISED


async def test_rung_2_deduplicates(world, settings) -> None:
    world["declared"] = {"u7": ["Books", "Books", "Pets"]}

    p = await get_profile(settings, "u7", reference_date=NOW)

    assert len(p.categories) == 2


# --- rung 3 -----------------------------------------------------------------


async def test_rung_3_serves_platform_popularity(world, settings) -> None:
    world["popularity"] = {"Fashion & Apparel": 60, "Electronics": 40}

    p = await get_profile(settings, "u11", reference_date=NOW)

    assert p.rung is Rung.POPULARITY
    assert p.categories[0].share == pytest.approx(0.6)
    assert p.popularity_window_days == 30


async def test_rung_3_is_not_personalised(world, settings) -> None:
    """Every user who lands here gets the same answer, so a screen must not
    label it "Recommended for you".
    """
    world["popularity"] = {"Books": 1}

    assert (await get_profile(settings, "u11", reference_date=NOW)).personalised is False


async def test_rung_3_uses_the_p27_window(world, settings) -> None:
    captured = {}

    from reco.platform import readers

    async def capture(settings, window_days, reference_date=None):
        captured["window"] = window_days
        return {"Books": 1}

    readers.read_category_popularity = capture
    tuned = Settings(data_profile="demo", cold_start_popularity_window_days=90)

    p = await get_profile(tuned, "u11", reference_date=NOW)

    assert captured["window"] == 90
    assert p.popularity_window_days == 90


async def test_rung_3_with_no_platform_activity_is_empty_not_invented(
    world, settings, caplog
) -> None:
    """An empty profile that names its rung is honest. Inventing a spread across
    the vocabulary would not be.
    """
    world["popularity"] = {}

    with caplog.at_level(logging.WARNING, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u11", reference_date=NOW)

    assert p.categories == []
    assert p.rung is Rung.POPULARITY
    assert "no platform activity" in caplog.text


# --- rung 4 -----------------------------------------------------------------


async def test_rung_4_a_stale_score_falls_through_to_rung_3(
    world, settings, caplog
) -> None:
    """P-08 is 24 hours. A score older than that is unusable, and the delivered
    score it should fall back to does not exist for most users.
    """
    world["scores"] = [score("u1", "Fashion & Apparel", 1.0, age_hours=48)]
    world["popularity"] = {"Books": 10}

    with caplog.at_level(logging.WARNING, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u1", reference_date=NOW)

    assert p.rung is Rung.POPULARITY
    assert p.fell_through_from is Rung.STALE
    assert "RUNG 4" in caplog.text
    assert "REFRESH problem" in caplog.text


async def test_a_fresh_score_is_not_stale(world, settings) -> None:
    world["scores"] = [score("u1", "Fashion & Apparel", 1.0, age_hours=23)]

    assert (await get_profile(settings, "u1", reference_date=NOW)).rung is Rung.PERSONALISED


async def test_staleness_threshold_comes_from_configuration(world, settings) -> None:
    world["scores"] = [score("u1", "Fashion & Apparel", 1.0, age_hours=48)]
    world["popularity"] = {"Books": 1}
    lenient = Settings(data_profile="demo", score_staleness_hours=72)

    assert (await get_profile(lenient, "u1", reference_date=NOW)).rung is Rung.PERSONALISED


async def test_shares_that_do_not_sum_to_one_fail_the_range_check(
    world, settings, caplog
) -> None:
    """A score can be fresh and still broken."""
    world["scores"] = [
        score("u1", "Fashion & Apparel", 0.5),
        score("u1", "Electronics", 0.2),
    ]
    world["popularity"] = {"Books": 1}

    with caplog.at_level(logging.ERROR, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u1", reference_date=NOW)

    assert p.rung is Rung.POPULARITY
    assert p.fell_through_from is Rung.STALE
    assert "range check" in caplog.text


# --- rung 5 -----------------------------------------------------------------


async def test_rung_5_an_unreachable_store_falls_through_to_rung_3(
    world, settings, caplog
) -> None:
    world["raise_on_read"] = True
    world["popularity"] = {"Books": 10}

    with caplog.at_level(logging.ERROR, logger="reco.fallback.read_path"):
        p = await get_profile(settings, "u1", reference_date=NOW)

    assert p.rung is Rung.POPULARITY
    assert p.fell_through_from is Rung.UNAVAILABLE
    assert "RUNG 5" in caplog.text
    assert "SERVING problem" in caplog.text


async def test_rungs_4_and_5_are_logged_distinctly(world, settings, caplog) -> None:
    """A stale score is a refresh problem; an unreachable engine is a serving
    problem. One combined message would send someone to fix the wrong thing.
    """
    world["popularity"] = {"Books": 1}

    world["scores"] = [score("u1", "Books", 1.0, age_hours=48)]
    with caplog.at_level(logging.WARNING, logger="reco.fallback.read_path"):
        await get_profile(settings, "u1", reference_date=NOW)
    stale_log = caplog.text
    caplog.clear()

    world["scores"] = []
    world["raise_on_read"] = True
    with caplog.at_level(logging.ERROR, logger="reco.fallback.read_path"):
        await get_profile(settings, "u2", reference_date=NOW)

    assert "REFRESH problem" in stale_log and "SERVING problem" not in stale_log
    assert "SERVING problem" in caplog.text and "REFRESH problem" not in caplog.text


# --- the ladder as a whole --------------------------------------------------


async def test_the_order_is_first_match_wins(world, settings) -> None:
    """A user with a score AND declared interests gets the score."""
    world["scores"] = [score("u1", "Electronics", 1.0)]
    world["declared"] = {"u1": ["Books"]}

    p = await get_profile(settings, "u1", reference_date=NOW)

    assert p.rung is Rung.PERSONALISED
    assert p.categories[0].category == "Electronics"


async def test_nobody_is_ever_served_nothing(world, settings) -> None:
    """Every rung returns a Profile. There is no 'unknown user' case."""
    world["popularity"] = {"Books": 1}

    p = await get_profile(settings, "someone-who-does-not-exist", reference_date=NOW)

    assert isinstance(p, Profile)
    assert p.rung is Rung.POPULARITY


async def test_every_response_carries_the_stamp(world, settings) -> None:
    """Task 20. The model version travels with every answer, at every rung."""
    world["popularity"] = {"Books": 1}
    world["declared"] = {"u7": ["Pets"]}
    world["scores"] = [score("u1", "Electronics", 1.0)]

    for user_id in ("u1", "u7", "u11"):
        p = await get_profile(settings, user_id, reference_date=NOW)
        assert p.model_version == "test-1.0.0"
        assert p.rung_description


async def test_the_summary_names_the_rung(world, settings) -> None:
    world["declared"] = {"u7": ["Pets"]}

    assert "rung 2" in (await get_profile(settings, "u7", reference_date=NOW)).summary()


# --- helpers ----------------------------------------------------------------


def test_is_stale_uses_the_threshold() -> None:
    assert is_stale(NOW - timedelta(hours=25), NOW, 24) is True
    assert is_stale(NOW - timedelta(hours=23), NOW, 24) is False


def test_evenly_spread_sums_to_one() -> None:
    shares = evenly_spread(["a", "b", "c"])

    assert len(shares) == 3
    assert sum(s.share for s in shares) == pytest.approx(1.0)


def test_evenly_spread_ignores_blanks() -> None:
    assert evenly_spread(["a", "", "   ", "b"]) and len(evenly_spread(["a", "", "b"])) == 2


def test_evenly_spread_of_nothing_is_empty() -> None:
    assert evenly_spread([]) == []
