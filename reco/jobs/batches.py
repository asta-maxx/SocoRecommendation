"""Write a whole new batch, and only then make it current. ENG-07.

    await run_batch(settings, job="interest", slot="interest", method="recency_decay",
                    collection=settings.scores_collection, data_window=..., work=...)

`work(job_run_id)` writes every row of the batch carrying that job_run_id and
returns how many it wrote. Then:

    succeeded  the batch is marked current (requests switch to it), and batches
               older than the one it replaced are removed
    failed     the run is recorded as failed, its partial rows are removed, and
               the previous batch stays current
    killed     nothing runs at all -- so the next run of the job records the
               leftover "running" record as failed (abandoned), and its rows,
               never current, are removed at the next success

Jobs that write no batch record their runs with recorded_run() (SD-21).

A request reads only the batch marked current (reco.store.writers
read_user_scores), so it never sees a half-written one.

Every run is a record in ml_job_runs: job, slot, method, data window, rows
written, duration, outcome (running / succeeded / failed), error, and its _id
is the job_run_id.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable

from reco.config import Settings, live
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.job")

#: Who started the run, recorded on every ml_job_runs row (review of 26 Oct 2026,
#: point 6): "scheduler" (the 2 AM nightly), "sync_loop" (the sync every few
#: minutes), or "hand" (a person ran `python -m reco.jobs ...`).
TRIGGER: ContextVar[str] = ContextVar("job_trigger", default="hand")


async def run_batch(
    settings: Settings,
    *,
    job: str,
    slot: str | None,
    method: str | None,
    collection: str,
    data_window: dict[str, datetime | None],
    work: Callable[[str], Awaitable[int]],
) -> dict[str, Any]:
    job_run_id = str(uuid.uuid4())
    started = utc_now()
    clock = time.monotonic()
    abandoned = await writers.abandon_running(settings, job, method, started)
    if abandoned:
        logger.warning("earlier runs never finished; recorded as failed", extra={"job": job, "method": method, "abandoned": abandoned})
    record = {
        "_id": job_run_id,
        "job": job,
        "slot": slot,
        "method": method,
        "collection": collection,
        "data_window": data_window,
        "config_version": live.current().config_version,
        "model_version": settings.model_version,
        "started_at": started,
        "started_by": TRIGGER.get(),
        "outcome": "running",
        "is_current": False,
    }
    await writers.record_job_run(settings, record)
    try:
        rows = await work(job_run_id)
    except BaseException as exc:  # a cancelled task too: the previous batch stays current
        await writers.update_job_run(settings, job_run_id, {
            "outcome": "failed", "error": repr(exc)[:500], "finished_at": utc_now(),
            "duration_seconds": round(time.monotonic() - clock, 3),
            "rows_written": 0,  # its partial rows are removed just below
        })
        await writers.delete_batches_except(settings, collection, method, keep=[], only=job_run_id)
        raise
    finished = utc_now()
    await writers.update_job_run(settings, job_run_id, {
        "outcome": "succeeded", "rows_written": rows, "finished_at": finished,
        "duration_seconds": round(time.monotonic() - clock, 3),
    })
    previous = await writers.mark_current(settings, job, method, job_run_id)
    removed = await writers.delete_batches_except(settings, collection, method, keep=[job_run_id, previous])
    record.update(outcome="succeeded", rows_written=rows, finished_at=finished, is_current=True,
                  replaced=previous, rows_removed=removed)
    return record


@asynccontextmanager
async def recorded_run(
    settings: Settings, job: str, *, data_window: dict[str, datetime | None] | None = None
) -> AsyncIterator[dict[str, Any]]:
    """SD-21: a job that writes no batch (the sync, its reconciliation, the lag
    check) is still recorded in ml_job_runs. The caller fills in rows_written
    and, optionally, detail.

        async with recorded_run(settings, "sync") as run:
            run["rows_written"] = ...
    """
    job_run_id = str(uuid.uuid4())
    started = utc_now()
    clock = time.monotonic()
    await writers.abandon_running(settings, job, None, started)
    await writers.record_job_run(settings, {
        "_id": job_run_id, "job": job, "slot": None, "method": None, "data_window": data_window,
        "config_version": live.current().config_version, "model_version": settings.model_version,
        "started_at": started, "started_by": TRIGGER.get(), "outcome": "running", "is_current": False,
    })
    result: dict[str, Any] = {"job_run_id": job_run_id, "rows_written": 0, "detail": None}
    try:
        yield result
    except BaseException as exc:
        await writers.update_job_run(settings, job_run_id, {
            "outcome": "failed", "error": repr(exc)[:500], "finished_at": utc_now(),
            "duration_seconds": round(time.monotonic() - clock, 3), "rows_written": result["rows_written"],
            "detail": result["detail"],
        })
        raise
    await writers.update_job_run(settings, job_run_id, {
        "outcome": "succeeded", "finished_at": utc_now(), "duration_seconds": round(time.monotonic() - clock, 3),
        "rows_written": result["rows_written"], "detail": result["detail"],
    })
