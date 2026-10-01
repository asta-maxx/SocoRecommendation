"""The watcher: alerts that must not depend on the thing they watch. ENG-04 item 7, ENG-07.

Runs inside the API process (always up), every sync_interval_minutes:

    sync lag     more than sync_lag_alert_minutes behind on any source, or a failed
                 last pass (ENG-04 item 7) -- so a sync process that died or hung
                 still raises the alert
    stuck runs   a job run still "running" STUCK_AFTER after it started: killed or
                 hung (ENG-07: "ml_job_runs shows the failure"; a kill runs no
                 handler, so it is found here). The pack sets no time; 2 hours is
                 well past any Wave 1A job on today's data.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from reco.config import Settings, live
from reco.monitoring.alerts import alert
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.watch")

STUCK_AFTER = timedelta(hours=2)


async def stuck_runs(settings: Settings) -> list[dict[str, Any]]:
    stuck = await writers.read_running_jobs(settings, started_before=utc_now() - STUCK_AFTER)
    for run in stuck:
        alert("job_stuck", "a job run has been 'running' too long: killed or hung",
              job=run.get("job"), method=run.get("method"), job_run_id=run["_id"], started_at=str(run.get("started_at")))
    return stuck


async def watch_once(settings: Settings) -> None:
    from reco.sync.run import check_lag  # the sync module; imported here to keep monitoring light

    await check_lag(settings)
    await stuck_runs(settings)


async def watch_loop(settings: Settings) -> None:
    while True:
        try:
            await watch_once(settings)
        except Exception:
            logger.exception("the watcher could not run its checks")
        await asyncio.sleep(live.current().events.sync_interval_minutes * 60)
