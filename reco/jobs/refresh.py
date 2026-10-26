"""The refresh: compute a score for every user and write it. ENG-10 (and the M1 demo's RE-06).

ENG-10: on the live profile the inputs are the engine's own copies
(reco.slots.interest.copies), with every v1.3 action and weight, and each user's
raws are clipped at 0 before sharing. The demo profile keeps the M1 demo's reader
and its coherence rule, which its pinned checks depend on.

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
from datetime import datetime, timedelta

from reco.config import Settings
from reco.config import live
from reco.config.accounts import test_account_ids
from reco.platform import readers
from reco.store.writers import remove_scores_older_than, upsert_user_scores
from reco.slots.interest.events import Event, ReadStats
from reco.store.scores import (
    CoherenceFailure,
    InterestScore,
    clip_to_shares,
    Method,
    Window,
    normalise_with_coherence,
    utc_now,
)
from reco.slots.interest import copies, interest_decay, interest_windows
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


def data_window(method: Method, anchor: datetime) -> dict[str, datetime | None]:
    """The events a method reads: all of them up to the anchor for the decay
    method, the last window bound (90 days by default) for time windows."""
    if METHODS[method][1] == Window.LAST_90_DAYS:
        days = max(live.current().interest.window_bounds_days)
        return {"from": anchor - timedelta(days=days), "to": anchor}
    return {"from": None, "to": anchor}


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
    test_accounts_skipped: int = 0  # ENG-29 item 3
    #: "copies" (ENG-10: the engine's own copies) or "demo" (the M1 demo's events).
    source: str = "copies"
    #: ENG-10: what the copy reader left out before scoring, and why.
    skipped: dict[str, int] = field(default_factory=dict)
    #: Users with a category below 0 before the clip (Not interested / Hide).
    users_clipped: int = 0
    #: ENG-30 point 7: "current", or why the return-request copy was not.
    return_requests: str = "current"
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
            f"Source: {self.source}; left out before scoring: {self.skipped or 'nothing'}; "
            f"users clipped at 0: {self.users_clipped}; return-request copy: {self.return_requests}. "
            f"Test accounts left out: {self.test_accounts_skipped}. "
            f"Stale rows removed: {self.stale_removed}. "
            f"Coherence failures: {len(self.coherence_failures)}."
        )


async def refresh(
    settings: Settings,
    method: Method = Method.RECENCY_DECAY,
    reference_date: datetime | None = None,
    tunables: dict | None = None,
    job_run_id: str | None = None,
) -> RefreshRun:
    """Score every user under one method and write the results.

    `reference_date` anchors the decay. Passing the dataset's own reference date
    reproduces its expected values exactly; passing None ages from now, which is
    what a live run does.

    Which method is asked for decides both how it is computed and what it is
    stored as, so a decay-off run cannot land under the decay-on name.

    With `job_run_id` (a nightly job, ENG-07) every row joins that batch and
    nothing is removed here: reco.jobs.batches makes the batch current once it
    is complete and clears the older ones. Without it (the M1 demo's own run),
    rows are rewritten in place and stale ones swept, as before.
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

    if settings.data_profile == "demo":
        # The M1 demo's generated events (its pinned checks depend on them).
        run.source = "demo"
        events_by_user, run.read_stats = await readers.read_events_by_user(
            settings, reference_date=anchor
        )
        declared = await readers.read_all_declared_interests(settings)
        orders = await readers.read_all_order_creation_times(settings)
        user_ids = await readers.read_all_user_ids(settings)
    else:
        # ENG-10: every model reads only the engine's copies (ENG-04). Reversed
        # orders and undone actions are already netted to zero by the reader.
        inputs = await copies.read_inputs(settings, anchor)
        events_by_user, run.read_stats = inputs.events_by_user, inputs.read_stats
        declared, orders, user_ids = inputs.declared, {}, inputs.user_ids
        run.skipped = dict(inputs.skipped)
        run.return_requests = inputs.return_requests

    # ENG-29 item 3: test accounts are left out of learning.
    tests = test_account_ids()
    run.test_accounts_skipped = sum(1 for u in user_ids if str(u).lower() in tests)
    user_ids = [u for u in user_ids if str(u).lower() not in tests]
    run.users_seen = len(user_ids)
    # The settings in force, unless a caller pins its own (the demo checks pin
    # the DS-007 values their expected answers were generated with).
    tunables = tunables if tunables is not None else live.current().m1()

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

        if run.source == "demo":
            clamped, shares, failures = normalise_with_coherence(user_id, raws)
            run.coherence_failures.extend(failures)
        else:
            # ENG-10's order: weighted actions, plus the floor, then clip each
            # category at 0, then share. A negative is Not interested / Hide doing
            # its job, not a fault.
            run.users_clipped += any(raw < 0 for raw in raws.values())
            clamped, shares = clip_to_shares(raws)

        if not shares:
            # Either the user has no signal at all, or a coherence failure
            # suppressed the whole distribution. Store NOTHING -- a uniform share
            # is indistinguishable from a genuine even spread and would hide that
            # the user is unknown. The cold-start ladder answers instead.
            run.users_with_no_score += 1
            continue

        qualified = inputs.qualified_by_category.get(user_id, {}) if run.source == "copies" else None
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
                # Copies: the qualified actions in the last 90 days in this category
                # (Kala, 16 Oct). Demo: the events that contributed, as before.
                event_count=(qualified.get(category, 0) if qualified is not None
                             else stats.contributions.get(category, 0)),
                qualified_actions=inputs.qualified.get(user_id, 0) if run.source == "copies" else None,
                method=method,
                model_version=settings.model_version,
                window=window,
                computed_at=started,
                job_run_id=job_run_id,
                config_version=live.current().config_version if job_run_id else None,
                data_window=data_window(method, anchor) if job_run_id else None,
            )
            for category, share in shares.items()
        ]

        run.scores_written += await upsert_user_scores(settings, user_id, scores)
        run.users_scored += 1

    # Anything this run did not rewrite is from a previous one and is stale.
    # (A batch run leaves that to reco.jobs.batches.)
    if job_run_id is None:
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
