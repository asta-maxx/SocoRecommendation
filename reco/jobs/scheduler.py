"""The daily refresh at 2 AM IST. ENG-07, SD-22.

    python -m reco.jobs nightly      every nightly job once, now
    python -m reco.jobs scheduler    wait for 2 AM IST, run them, repeat

The Build List's nightly list, and the item that brings each job:

    M1, both methods                 interest        here now (ENG-10 moves it onto ml_events)
    ladder rung 3 popularity         popularity      here now (ENG-09)
    M2 method two candidates         similar_posts   here now (ENG-14)
    M5, both methods                 product_ranking here now (ENG-17)
    M8, both methods, and the        ENG-16
      monthly copy on the 1st
    M6                               ENG-18
    the fraud rules                  ENG-21
    unmapped categories (daily)      category_check  here now (ENG-29 item 1)

Each item adds its job to NIGHTLY when it is built. The jobs run one after
another; a failed job is recorded and alerted, the others still run, and the
night's run exits non-zero. SD-22: the engine sync's daily reconciliation runs
after the refreshes, so it is last.

The time is a setting (SD-22): interest.refresh_time_ist, "02:00" (the Settings
sheet: "daily, 2 AM IST", fixed for Wave 1A). It is read again before each wait.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Awaitable, Callable

from reco.config import Settings, live
from reco.config import sync as config_sync
from reco.monitoring.alerts import alert
from reco.store.scores import utc_now

logger = logging.getLogger("reco.job")

IST = timezone(timedelta(hours=5, minutes=30))

#: Job names (in reco.jobs JOBS) run every night, in this order.
NIGHTLY: tuple[str, ...] = ("interest", "similar_posts", "promoter", "product_ranking", "popularity", "category_check",
                            "reconcile_sync")


def next_run(now: datetime, at: str = "02:00") -> datetime:
    """The next `at` (HH:MM, IST) strictly after `now`."""
    hour, minute = (int(part) for part in at.split(":"))
    local = now.astimezone(IST)
    candidate = datetime.combine(local.date(), time(hour, minute, tzinfo=IST))
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


async def run_nightly(settings: Settings, jobs: dict[str, Callable[[Settings], Awaitable[None]]]) -> list[str]:
    """Every nightly job once. Returns the names that failed."""
    failed = []
    for name in NIGHTLY:
        try:
            await jobs[name](settings)
        except Exception as exc:
            failed.append(name)
            alert("job_failed", "nightly job failed; the previous batch stays in use", job=name, error=repr(exc)[:500])
    return failed


async def run_forever(settings: Settings, jobs: dict[str, Callable[[Settings], Awaitable[None]]]) -> None:
    while True:
        await config_sync.reload(settings)  # a changed run time applies from the next wait
        due = next_run(utc_now(), live.current().interest.refresh_time_ist)
        logger.info("next nightly run", extra={"job": "scheduler", "due": due.isoformat()})
        await asyncio.sleep(max(0.0, (due - utc_now()).total_seconds()))
        # A job reads the settings once, at its start (ENG-02 item 3).
        await config_sync.reload(settings)
        await run_nightly(settings, jobs)
