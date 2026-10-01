"""The daily refresh at 2 AM IST. ENG-07.

    python -m reco.jobs nightly      every nightly job once, now
    python -m reco.jobs scheduler    wait for 2 AM IST, run them, repeat

The Build List's nightly list, and the item that brings each job:

    M1, both methods                 interest        here now (ENG-10 moves it onto ml_events)
    M2 method two candidates         ENG-14
    M5, both methods                 ENG-17
    M8, both methods, and the        ENG-16
      monthly copy on the 1st
    M6                               ENG-18
    the fraud rules                  ENG-21

Each item adds its job to NIGHTLY when it is built. The jobs run one after
another; a failed job is recorded and alerted, the others still run, and the
night's run exits non-zero.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Awaitable, Callable

from reco.config import Settings
from reco.config import sync as config_sync
from reco.monitoring.alerts import alert
from reco.store.scores import utc_now

logger = logging.getLogger("reco.job")

IST = timezone(timedelta(hours=5, minutes=30))
RUN_AT = time(2, 0, tzinfo=IST)

#: Job names (in reco.jobs JOBS) run every night, in this order.
NIGHTLY: tuple[str, ...] = ("interest",)


def next_run(now: datetime) -> datetime:
    """The next 2 AM IST strictly after `now`."""
    local = now.astimezone(IST)
    candidate = datetime.combine(local.date(), RUN_AT)
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
        due = next_run(utc_now())
        logger.info("next nightly run", extra={"job": "scheduler", "due": due.isoformat()})
        await asyncio.sleep(max(0.0, (due - utc_now()).total_seconds()))
        # A job reads the settings once, at its start (ENG-02 item 3).
        await config_sync.reload(settings)
        await run_nightly(settings, jobs)
