"""The refresh: compute a score for every user and write it. RE-06, task 10.

    read the sources once
      -> score each user with a method
        -> normalise that user's raws to shares
          -> write the user's whole category map in one call

Everything a method needs is read here and handed over, so the method itself
touches no database. The refresh is the only thing that knows both sides.

A refresh that fails silently is the commonest way a score stops being current
without anyone noticing, so every run returns a record of what it did: how many
users, how many scores, what was dropped and why, and how long it took.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from reco.config import Settings
from reco.platform import readers
from reco.store.writers import remove_scores_older_than, upsert_user_scores
from reco.slots.interest.events import Event, ReadStats
from reco.store.scores import (
    CoherenceFailure,
    InterestScore,
    Method,
    Window,
    normalise_with_coherence,
    utc_now,
)
from reco.slots.interest import interest_decay, interest_windows
from reco.slots.interest.context import ScoringContext

logger = logging.getLogger(__name__)

#: method -> (the module that computes it, its window, whether decay applies)
#:
#: The decay-off run is a separate entry rather than a flag on the call, so the
#: two can never be written under one method value by accident. Both rows in the
#: store at once is the point -- step 4 shows them side by side -- and sharing a
#: name would have the checks read decay-off rows as wrong answers to the
#: decay-on question.
METHODS = {
    Method.RECENCY_DECAY: (interest_decay, Window.ALL, True),
    Method.RECENCY_DECAY_NO_DECAY: (interest_decay, Window.ALL, False),
    Method.TIME_WINDOWS: (interest_windows, Window.LAST_90_DAYS, True),
}


@dataclass
class RefreshRun:
    """What one refresh did. Written alongside the scores, not just logged.

    A run that wrote nothing and a run that was never started look identical in
    the score store. They do not look identical here.
    """

    method: str
    model_version: str
    window: str
    started_at: datetime
    reference_date: datetime

    users_seen: int = 0
    users_scored: int = 0
    users_with_no_score: int = 0
    scores_written: int = 0
    stale_removed: int = 0
    duration_seconds: float = 0.0

    read_stats: ReadStats = field(default_factory=ReadStats)
    sub_threshold_views: int = 0
    views_without_duration: int = 0
    reversals_applied: int = 0
    reversals_unaged: int = 0
    coherence_failures: list[CoherenceFailure] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.method} v{self.model_version}: {self.users_scored} of "
            f"{self.users_seen} users scored, {self.scores_written} scores "
            f"written in {self.duration_seconds:.1f}s. "
            f"Dropped at read: {self.read_stats.dropped} "
            f"(unresolved category {self.read_stats.unresolved_category}, "
            f"missing timestamp {self.read_stats.missing_timestamp}, "
            f"future timestamp {self.read_stats.future_timestamp}). "
            f"Dropped at scoring: sub-threshold views "
            f"{self.sub_threshold_views}, views without a duration "
            f"{self.views_without_duration}. "
            f"Reversals {self.reversals_applied} "
            f"({self.reversals_unaged} could not be aged). "
            f"Users with no score: {self.users_with_no_score}. "
            f"Stale rows removed: {self.stale_removed}. "
            f"Coherence failures: {len(self.coherence_failures)}."
        )


async def refresh(
    settings: Settings,
    method: Method = Method.RECENCY_DECAY,
    reference_date: datetime | None = None,
) -> RefreshRun:
    """Score every user under one method and write the results.

    `reference_date` anchors the decay. Passing the dataset's own reference date
    reproduces its expected values exactly; passing None ages from now, which is
    what a live run does.

    Which method is asked for decides both how it is computed and what it is
    stored as, so a decay-off run cannot land under the decay-on name.
    """
    module, window, decay_enabled = METHODS[method]
    started = utc_now()
    clock = time.monotonic()

    anchor = reference_date or started
    run = RefreshRun(
        method=str(method),
        model_version=settings.model_version,
        window=str(window),
        started_at=started,
        reference_date=anchor,
    )

    events_by_user, run.read_stats = await readers.read_events_by_user(
        settings, reference_date=anchor
    )
    declared = await readers.read_all_declared_interests(settings)
    orders = await readers.read_all_order_creation_times(settings)
    user_ids = await readers.read_all_user_ids(settings)

    run.users_seen = len(user_ids)
    tunables = settings.tunables()

    for user_id in user_ids:
        events: list[Event] = events_by_user.get(user_id, [])
        ctx = ScoringContext(
            tunables=tunables,
            declared_interests=declared.get(user_id, []),
            order_created_at=orders,
            now=anchor,
            decay_enabled=decay_enabled,
        )

        raws, stats = module.score(events, ctx)

        run.sub_threshold_views += stats.sub_threshold_views
        run.views_without_duration += stats.views_without_duration
        run.reversals_applied += stats.reversals_applied
        run.reversals_unaged += stats.reversals_unaged

        clamped, shares, failures = normalise_with_coherence(user_id, raws)
        run.coherence_failures.extend(failures)

        if not shares:
            # Either the user has no signal at all, or a coherence failure
            # suppressed the whole distribution. Store NOTHING -- a uniform share
            # is indistinguishable from a genuine even spread and would hide that
            # the user is unknown. The cold-start ladder answers instead.
            run.users_with_no_score += 1
            continue

        scores = [
            InterestScore(
                user_id=user_id,
                category=category,
                raw=clamped[category],
                share=share,
                # Events that CONTRIBUTED to this number, not events in this
                # category. U02 has twenty views and eight that qualify; showing
                # 20 beside a score built from 8 invites the exact question the
                # number exists to answer.
                event_count=stats.contributions.get(category, 0),
                method=method,
                model_version=settings.model_version,
                window=window,
                computed_at=started,
            )
            for category, share in shares.items()
        ]

        run.scores_written += await upsert_user_scores(settings, user_id, scores)
        run.users_scored += 1

    # Anything this run did not rewrite is from a previous one and is stale.
    run.stale_removed = await remove_scores_older_than(
        settings, method, settings.model_version, started
    )

    run.duration_seconds = time.monotonic() - clock

    if run.coherence_failures:
        logger.error(
            "%d coherence failures this run -- check the purchase reversal is "
            "aged from the original order",
            len(run.coherence_failures),
        )
    if run.reversals_unaged:
        logger.error(
            "%d reversals could not be aged from their order; those scores are "
            "wrong, not merely approximate",
            run.reversals_unaged,
        )

    logger.info(run.summary())
    return run
