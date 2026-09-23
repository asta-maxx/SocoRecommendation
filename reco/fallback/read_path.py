"""The read path and the fallback ladder. RE-05 and RE-07, tasks 17 and 20.

Asked for a user's profile, this walks the ladder and returns whatever the first
matching rung produces -- together with WHICH rung produced it.

    1  has activity and a fresh score      the personalised score
    2  declared interests, no activity     the floor alone, spread across them
    3  neither                             platform popularity over P-27 days
    4  a score, but stale or out of range   the delivered score -> falls to 3
    5  the engine is unavailable            the delivered score -> falls to 3

Nobody is ever served nothing, and nobody is ever served a guess that looks like
a real profile. Rung 3 is the same answer for every user on the platform, so a
screen that cannot tell the difference might put "Recommended for you" above it.
That is why the rung travels with the answer instead of being logged and dropped.

This week's scope is rungs 2 and 3. Rung 1 is the score store, already built.
Rungs 4 and 5 are implemented as fall-throughs because the delivered fixed-weight
score they point at does not exist for most users -- and each logs separately: a
stale score is a refresh problem, an unreachable engine is a serving problem, and
the two need different fixes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from reco.config import Settings
from reco.platform import readers
from reco.store.writers import read_user_scores
from reco.fallback.profile import (
    FALLS_THROUGH_TO_POPULARITY,
    RUNG_DESCRIPTION,
    CategoryShare,
    Profile,
    Rung,
    evenly_spread,
)
from reco.store.scores import Method

logger = logging.getLogger(__name__)


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
        personalised=rung in (Rung.PERSONALISED, Rung.DECLARED_ONLY),
        method=method,
        model_version=settings.model_version,
        computed_at=computed_at,
        fell_through_from=fell_through_from,
        popularity_window_days=popularity_window_days,
    )


def is_stale(computed_at: datetime, now: datetime, staleness_hours: float) -> bool:
    """P-08. A score older than this is treated as unusable.

    The threshold must exceed the refresh interval or every score is stale before
    it is replaced -- P-08 is 24 hours against a daily cadence for that reason.
    """
    return (now - computed_at) > timedelta(hours=staleness_hours)


async def _popularity(
    settings: Settings,
    user_id: str,
    reference_date: datetime | None,
    fell_through_from: Rung | None = None,
) -> Profile:
    """Rung 3. Platform-wide category popularity over the P-27 window.

    Not personalised, and it says so. Every user who lands here gets the same
    answer.
    """
    window = settings.cold_start_popularity_window_days
    counts = await readers.read_category_popularity(
        settings, window_days=window, reference_date=reference_date
    )

    total = sum(counts.values())
    if not total:
        # No platform activity in the window either. An empty profile that still
        # names its rung is honest; inventing a spread across the vocabulary
        # would not be.
        logger.warning(
            "rung 3 has no platform activity in the last %d days; serving an "
            "empty profile for %s",
            window,
            user_id,
        )
        categories: list[CategoryShare] = []
    else:
        categories = [
            CategoryShare(category=c, share=n / total, event_count=n)
            for c, n in counts.items()
        ]

    return _profile(
        settings,
        user_id,
        categories,
        Rung.POPULARITY,
        fell_through_from=fell_through_from,
        popularity_window_days=window,
    )


async def get_profile(
    settings: Settings,
    user_id: str,
    method: Method = Method.RECENCY_DECAY,
    reference_date: datetime | None = None,
) -> Profile:
    """Walk the ladder for one user. Always returns a profile.

    `reference_date` anchors staleness and the popularity window, so a run
    against the generated dataset is reproducible rather than dependent on when
    it happens to be run.
    """
    now = reference_date or datetime.now(timezone.utc)

    # --- rung 1 and rung 4: the stored score -------------------------------
    try:
        stored = await read_user_scores(settings, user_id, method)
    except Exception:
        # --- rung 5 ---------------------------------------------------------
        logger.exception(
            "RUNG 5 for %s: the score store could not be read. This is a SERVING "
            "problem -- falling through to rung 3.",
            user_id,
        )
        return await _popularity(
            settings, user_id, reference_date, fell_through_from=Rung.UNAVAILABLE
        )

    if stored:
        oldest = min(s.computed_at for s in stored)
        if is_stale(oldest, now, settings.score_staleness_hours):
            # --- rung 4 ------------------------------------------------------
            age_hours = (now - oldest).total_seconds() / 3600
            logger.warning(
                "RUNG 4 for %s: stored score is %.1f hours old against a P-08 "
                "limit of %.0f. This is a REFRESH problem -- falling through to "
                "rung 3 because no delivered score exists to serve instead.",
                user_id,
                age_hours,
                settings.score_staleness_hours,
            )
            return await _popularity(
                settings, user_id, reference_date, fell_through_from=Rung.STALE
            )

        # --- rung 1 ---------------------------------------------------------
        total = sum(s.share for s in stored)
        if abs(total - 1.0) > 1e-6:
            logger.error(
                "RUNG 4 for %s: stored shares sum to %.6f, not 1. The score fails "
                "a range check -- falling through to rung 3.",
                user_id,
                total,
            )
            return await _popularity(
                settings, user_id, reference_date, fell_through_from=Rung.STALE
            )

        if sum(s.event_count for s in stored) == 0:
            # A score exists, but no event contributed to it -- every category is
            # the declared floor alone. That is rung 2, not rung 1.
            #
            # Rung 1's condition is "has activity AND a fresh score", not "has a
            # row in the store". The refresh writes a floor-only score for anyone
            # who declared interests and has done nothing, so keying rung 1 on
            # the row's existence would make rung 2 unreachable -- and rung 2 is
            # the common case at launch, not the exception: everyone who signs up
            # on day one has picked interests and done nothing.
            logger.info(
                "RUNG 2 for %s: a score exists but no events contributed to it, "
                "so it is the declared floor alone",
                user_id,
            )
            ordered = sorted(stored, key=lambda s: s.share, reverse=True)
            return _profile(
                settings,
                user_id,
                [
                    CategoryShare(
                        category=s.category,
                        share=s.share,
                        raw=s.raw,
                        event_count=s.event_count,
                    )
                    for s in ordered
                ],
                Rung.DECLARED_ONLY,
                computed_at=oldest,
            )

        ordered = sorted(stored, key=lambda s: s.share, reverse=True)
        return _profile(
            settings,
            user_id,
            [
                CategoryShare(
                    category=s.category,
                    share=s.share,
                    raw=s.raw,
                    event_count=s.event_count,
                )
                for s in ordered
            ],
            Rung.PERSONALISED,
            method=str(method),
            computed_at=oldest,
        )

    # --- rung 2 -------------------------------------------------------------
    #
    # The common case at launch rather than the exception: everyone who signs up
    # on day one has picked interests and done nothing yet.
    declared = await readers.read_declared_interests(settings, user_id)
    if declared:
        logger.info("RUNG 2 for %s: %d declared interests, no score", user_id, len(declared))
        return _profile(settings, user_id, evenly_spread(declared), Rung.DECLARED_ONLY)

    # --- rung 3 -------------------------------------------------------------
    logger.info("RUNG 3 for %s: no score and no declared interests", user_id)
    return await _popularity(settings, user_id, reference_date)


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
