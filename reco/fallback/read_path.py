"""The read path and the fallback ladder. ENG-09 (Build List v1.3), SD-23, AS-14.

Asked for a user's interest profile, this walks the ladder and returns what the
first matching rung produces, together with WHICH rung produced it:

    1  5+ qualified actions in 90 days, and a score   the user's score
       under 48 hours old that passes its checks
    2  fewer than 5, with declared interests          the floor for those interests,
                                                      plus whatever actions they have
    3  fewer than 5, no declared interests            platform popularity (qualified
                                                      views per category, 30 days)
    4  the score is over 48 hours old or fails its    the old delivered score
       checks
    5  the engine's own store cannot be read          the old delivered score

If the engine's own store cannot be read, rung 5 applies at once. Where no old
delivered score exists, rung 4 falls back to rung 3; rung 5 does not (rung 3
needs the engine store too): the request is an error at once and SOCO_BE shows
its own ordering (Kala, 16 Oct; SD-26). When rung 3 has nothing either, the
profile is empty and named "rung 3 empty": the list is eligible posts newest first.

Every read comes from the engine's copies (ENG-04) or the platform's own records,
through reco.store and reco.platform. Nothing is calculated that a nightly job
should have calculated (SD-17): rung 3 reads the nightly popularity batch
(reco.fallback.popularity).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from reco.config import Settings
from reco.config import live
from reco.platform import fetch
from reco.platform.categories import canonical_name
from reco.platform.readers import vocabulary
from reco.store import writers
from reco.store.writers import read_user_scores
from reco.fallback.profile import (
    RUNG_DESCRIPTION,
    CategoryShare,
    Profile,
    Rung,
    evenly_spread,
)
from reco.store.scores import InterestScore, Method

logger = logging.getLogger(__name__)

class EngineStoreUnavailable(RuntimeError):
    """Rung 5 with no delivered score: the request answers 503 at once (SD-26)."""


#: The old delivered interest score on the platform's user record (ENG-03: read only
#: here, as the old score in the ladder). A map of category name -> number.
DELIVERED_SCORE_FIELD = "interestScores"


def _profile(
    settings: Settings,
    user_id: str,
    categories: list[CategoryShare],
    rung: Rung,
    *,
    method: str | None = None,
    computed_at: datetime | None = None,
    fell_through_from: Rung | None = None,
    popularity_window_days: int | None = None,
) -> Profile:
    return Profile(
        user_id=user_id,
        categories=categories,
        rung=rung,
        rung_description=RUNG_DESCRIPTION[rung],
        personalised=rung is not Rung.POPULARITY,
        method=method,
        model_version=settings.model_version,
        computed_at=computed_at,
        fell_through_from=fell_through_from,
        popularity_window_days=popularity_window_days,
    )


def is_stale(computed_at: datetime, now: datetime, staleness_hours: float) -> bool:
    """Rung 4: a score older than this is not used (48 hours against a daily refresh)."""
    return (now - computed_at) > timedelta(hours=staleness_hours)


def score_problem(stored: list[InterestScore], now: datetime, staleness_hours: float) -> str | None:
    """Why a stored score can't serve (rung 4), or None if it can.

    "Fails its checks": the M1 checks a request can see (ENG-11 checks 2 and 3):
    shares within 0 to 1 that sum to 1, raw never below 0, no category twice."""
    if not stored:
        return "no stored score"
    oldest = min(s.computed_at for s in stored)
    if is_stale(oldest, now, staleness_hours):
        return f"stored score is {(now - oldest).total_seconds() / 3600:.1f} hours old (limit {staleness_hours:g})"
    total = sum(s.share for s in stored)
    if abs(total - 1.0) > 1e-6:
        return f"stored shares sum to {total:.6f}, not 1"
    if any(s.raw < 0 or not 0.0 <= s.share <= 1.0 for s in stored):
        return "a stored raw is below 0 or a share outside 0 to 1"
    if len({s.category for s in stored}) != len(stored):
        return "a category is stored twice"
    return None


def _from_scores(stored: list[InterestScore]) -> list[CategoryShare]:
    return [
        CategoryShare(category=s.category, share=s.share, raw=s.raw, event_count=s.event_count)
        for s in sorted(stored, key=lambda s: s.share, reverse=True)
    ]


def delivered_shares(settings: Settings, value: Any) -> list[CategoryShare]:
    """The old delivered score as shares: each name matched to the 23 (unmatched ones
    dropped, ENG-03), values below 0 clipped to 0, then divided by the total."""
    if not isinstance(value, dict):
        return []
    category_map = live.current().lists.category_map
    raws: dict[str, float] = {}
    for name, number in value.items():
        category = canonical_name(vocabulary(settings), name, category_map)
        if category is None or isinstance(number, bool) or not isinstance(number, (int, float)):
            continue
        raws[category] = raws.get(category, 0.0) + max(0.0, float(number))
    total = sum(raws.values())
    if not total:
        return []
    return [
        CategoryShare(category=c, share=r / total, raw=r)
        for c, r in sorted(raws.items(), key=lambda kv: kv[1], reverse=True)
    ]


async def _popularity(
    settings: Settings, user_id: str, fell_through_from: Rung | None = None, *, store_readable: bool = True
) -> Profile:
    """Rung 3: platform-wide category popularity, from the current nightly batch.

    Not personalised, and it says so. Empty (rung 3 empty) when no batch exists
    yet, when the platform has no qualified views in the window, or when the
    engine's store, which holds the batch, can't be read."""
    window = live.current().interest.popularity_window_days
    rows: list[dict[str, Any]] = []
    if store_readable:
        try:
            rows = await writers.read_popularity(settings)
        except Exception:
            logger.exception("rung 3 for %s: the popularity batch could not be read", user_id)
    total = sum(r["qualified_views"] for r in rows)
    categories = (
        [CategoryShare(category=r["category"], share=r["qualified_views"] / total, event_count=r["qualified_views"])
         for r in rows]
        if total else []
    )
    if not categories:
        logger.warning("RUNG 3 EMPTY for %s: no platform popularity; the list is eligible posts newest first", user_id)
    return _profile(settings, user_id, categories, Rung.POPULARITY,
                    fell_through_from=fell_through_from, popularity_window_days=window)


async def _delivered_or_popularity(
    settings: Settings, user_id: str, rung: Rung, delivered: Any, reason: str, *, store_readable: bool = True
) -> Profile:
    """Rungs 4 and 5: the old delivered score, or rung 3 where none exists. Logged
    separately: a stale score is a refresh problem, an unreadable store a serving one."""
    kind = "REFRESH" if rung is Rung.STALE else "SERVING"
    shares = delivered_shares(settings, delivered)
    if shares:
        logger.warning("RUNG %d for %s: %s (a %s problem); serving the old delivered score",
                       int(rung), user_id, reason, kind)
        return _profile(settings, user_id, shares, rung)
    if rung is Rung.UNAVAILABLE:
        # Kala, 16 Oct (2d): rung 3 needs the engine store too, so with no delivered
        # score the request is an error at once and SOCO_BE shows its own ordering
        # (SD-26). There is no rung_5_to_3.
        logger.error("RUNG 5 for %s: %s and no delivered score; answering with an error", user_id, reason)
        raise EngineStoreUnavailable(reason)
    logger.warning("RUNG %d for %s: %s (a %s problem); no delivered score, so rung 3",
                   int(rung), user_id, reason, kind)
    return await _popularity(settings, user_id, fell_through_from=rung, store_readable=store_readable)


async def _engine_side(
    settings: Settings, user_id: str, method: Method, since: datetime, view_ms: float, enough: int
) -> tuple[list[InterestScore], int]:
    return await asyncio.gather(
        read_user_scores(settings, user_id, method),
        writers.count_qualified_actions(settings, user_id, since, view_ms, enough),
    )


async def get_profile(
    settings: Settings,
    user_id: str,
    method: Method = Method.RECENCY_DECAY,
    reference_date: datetime | None = None,
) -> Profile:
    """Walk the ladder for one user and one interest method. Always returns a profile.

    The engine store and the platform are read at the same time. A platform read
    that fails raises (the request answers 503); an engine store read that fails
    is rung 5. `reference_date` anchors the 90-day count and the 48-hour limit.
    """
    now = reference_date or datetime.now(timezone.utc)
    tunables = live.current()
    interest = tunables.interest
    since = now - timedelta(days=interest.personal_window_days)
    view_ms = tunables.events.qualified_view_seconds * 1000
    enough = interest.personal_min_actions

    engine, platform = await asyncio.gather(
        _engine_side(settings, user_id, method, since, view_ms, enough),
        asyncio.gather(
            fetch.read_user_with(settings, user_id, (DELIVERED_SCORE_FIELD,)),
            fetch.read_business_follows(settings, user_id, since),
        ),
        return_exceptions=True,
    )
    if isinstance(platform, BaseException):
        raise platform
    (user, extra), business_follows = platform
    delivered = extra.get(DELIVERED_SCORE_FIELD)

    # --- rung 5: the engine's own store cannot be read -----------------------
    if isinstance(engine, BaseException):
        logger.error("engine store unreadable for %s: %r", user_id, engine)
        return await _delivered_or_popularity(
            settings, user_id, Rung.UNAVAILABLE, delivered, "the engine store could not be read", store_readable=False
        )
    stored, actions = engine
    actions += business_follows
    problem = score_problem(stored, now, interest.stale_after_hours)

    if actions >= enough:
        # --- rung 1 ----------------------------------------------------------
        if problem is None:
            return _profile(settings, user_id, _from_scores(stored), Rung.PERSONALISED,
                            method=str(method), computed_at=min(s.computed_at for s in stored))
        # --- rung 4 ----------------------------------------------------------
        return await _delivered_or_popularity(settings, user_id, Rung.STALE, delivered, problem)

    declared = user.declared_interests if user else []
    if declared:
        # --- rung 2: the floor plus whatever actions they have -----------------
        # The nightly score already is exactly that (ENG-10 writes the floor for
        # every declared category, plus the weighted actions). Without a usable
        # one, the floor alone, spread evenly across what they declared.
        if problem is None:
            logger.info("RUNG 2 for %s: %d qualified actions; the stored score (floor plus actions)", user_id, actions)
            return _profile(settings, user_id, _from_scores(stored), Rung.DECLARED_ONLY,
                            method=str(method), computed_at=min(s.computed_at for s in stored))
        logger.info("RUNG 2 for %s: %d qualified actions; %s, so the declared floor alone", user_id, actions, problem)
        return _profile(settings, user_id, evenly_spread(declared), Rung.DECLARED_ONLY)

    # --- rung 3 ----------------------------------------------------------------
    logger.info("RUNG 3 for %s: %d qualified actions and no declared interests", user_id, actions)
    return await _popularity(settings, user_id)


async def get_profiles(
    settings: Settings,
    user_ids: list[str],
    method: Method = Method.RECENCY_DECAY,
    reference_date: datetime | None = None,
) -> dict[str, Profile]:
    """The ladder for several users. Convenience for the display script."""
    return {
        user_id: await get_profile(settings, user_id, method, reference_date)
        for user_id in user_ids
    }
