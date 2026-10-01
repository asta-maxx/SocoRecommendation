"""Jobs mode. ENG-02 item 1, SD-01.

The same codebase as the API, started the other way: it runs scheduled work and
exits. Nothing here serves a request, so a failed job never touches the feed.

    python -m reco.jobs interest            # M1, both Wave 1A methods
    python -m reco.jobs sync                # one engine sync pass (ENG-04)
    python -m reco.jobs sync_loop           # a pass every sync_interval_minutes
    python -m reco.jobs sync_check          # the sync lag alert, on its own
    python -m reco.jobs reconcile_sync      # yesterday's reconciliation (IST day)
    python -m reco.jobs --list

The 2 AM IST scheduler that calls these arrives with ENG-07.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Awaitable, Callable

from reco.config import Settings, get_settings, sync
from reco.jobs.refresh import refresh
from reco.monitoring.logs import configure_logging, job_logger, job_run
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.store.scores import Method
from reco.store.writers import ensure_engine_collections, ensure_indexes
from reco.sync import reconcile as sync_reconcile
from reco.sync import run as sync_run


async def _interest(settings: Settings) -> None:
    """M1 interest: both methods, for every user (ENG-10 takes this further)."""
    for method in (Method.RECENCY_DECAY, Method.TIME_WINDOWS):
        async with job_run("interest", method=str(method)):
            result = await refresh(settings, method=method)
            job_logger.info(
                result.summary(),
                extra={
                    "job": "interest",
                    "method": result.method,
                    "users_seen": result.users_seen,
                    "users_scored": result.users_scored,
                    "scores_written": result.scores_written,
                },
            )


async def _sync(settings: Settings) -> None:
    """ENG-04: one pass over postevents, orders and recommendationrequests."""
    async with job_run("sync"):
        copied = await sync_run.sync_once(settings)
        job_logger.info("sync pass finished", extra={"job": "sync", "copied": copied})


async def _sync_loop(settings: Settings) -> None:
    async with job_run("sync_loop"):
        await sync_run.sync_forever(settings)


async def _sync_check(settings: Settings) -> None:
    async with job_run("sync_check"):
        statuses = await sync_run.check_lag(settings)
        job_logger.info("sync lag", extra={"job": "sync_check", "sources": statuses})


async def _reconcile_sync(settings: Settings) -> None:
    async with job_run("reconcile_sync"):
        results = await sync_reconcile.reconcile_day(settings)
        job_logger.info(
            "sync reconciliation finished",
            extra={"job": "reconcile_sync", "passed": all(r["passed"] for r in results),
                   "sources": {r["source"]: r["passed"] for r in results}},
        )


#: Job name -> what it runs. ENG-07 adds the rest of the nightly jobs here.
JOBS: dict[str, Callable[[Settings], Awaitable[None]]] = {
    "interest": _interest,
    "sync": _sync,
    "sync_loop": _sync_loop,
    "sync_check": _sync_check,
    "reconcile_sync": _reconcile_sync,
}


async def run(job: str) -> int:
    settings = get_settings()
    configure_logging(settings)
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await ensure_engine_collections(settings)
        await ensure_indexes(settings)
        # A job reads the settings once, at its start (ENG-02 item 3).
        await sync.load_at_start(settings)
        await JOBS[job](settings)
        return 0
    except Exception:
        # Already logged by job_run with the error; the exit code tells the
        # scheduler it failed.
        return 1
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reco.jobs")
    parser.add_argument("job", nargs="?", choices=sorted(JOBS))
    parser.add_argument("--list", action="store_true", help="list the jobs and exit")
    args = parser.parse_args(argv)
    if args.list or not args.job:
        print("\n".join(sorted(JOBS)))
        return 0
    return asyncio.run(run(args.job))


if __name__ == "__main__":
    sys.exit(main())
