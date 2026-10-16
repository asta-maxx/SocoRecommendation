"""Jobs mode. ENG-02 item 1, SD-01.

The same codebase as the API, started the other way: it runs scheduled work and
exits. Nothing here serves a request, so a failed job never touches the feed.

    python -m reco.jobs interest            # M1, both Wave 1A methods
    python -m reco.jobs popularity          # platform popularity, ladder rung 3 (ENG-09)
    python -m reco.jobs post_index          # recent posts and 7-day views, for the candidate sources (ENG-12)
    python -m reco.jobs sync                # one engine sync pass (ENG-04)
    python -m reco.jobs sync_loop           # a pass every sync_interval_minutes
    python -m reco.jobs sync_check          # the sync lag alert, on its own
    python -m reco.jobs reconcile_sync      # yesterday's reconciliation (IST day)
    python -m reco.jobs category_check      # categories outside the 23 (ENG-29)
    python -m reco.jobs nightly             # every nightly job once, now (ENG-07)
    python -m reco.jobs scheduler           # the nightly jobs at 2 AM IST, every day
    python -m reco.jobs --list

"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Awaitable, Callable

from reco.config import Settings, get_settings, sync
from reco.fallback import popularity
from reco.jobs import category_check, scheduler
from reco.jobs.batches import recorded_run, run_batch
from reco.jobs.refresh import data_window, refresh
from reco.monitoring.logs import configure_logging, job_logger, job_run
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.store import writers
from reco.store.scores import Method, utc_now
from reco.store.writers import ensure_engine_collections, ensure_indexes
from reco.sync import reconcile as sync_reconcile
from reco.sync import run as sync_run


async def _interest(settings: Settings) -> None:
    """M1 interest: both methods, for every user, each as a batch (ENG-07; ENG-10 takes it further).
    One method failing doesn't stop the other; the job still fails at the end."""
    # ENG-10: old time-windows rows with no method name are deleted, then recomputed below.
    removed = await writers.delete_unnamed_scores(settings)
    if removed:
        job_logger.info("unnamed score rows deleted", extra={"job": "interest", "rows": removed})
    failed = []
    for method in (Method.RECENCY_DECAY, Method.TIME_WINDOWS):
        try:
            await _interest_method(settings, method)
        except Exception:
            failed.append(str(method))
    if failed:
        raise RuntimeError(f"interest failed for {', '.join(failed)}")


async def _interest_method(settings: Settings, method: Method) -> None:
    async with job_run("interest", method=str(method)):
        anchor = utc_now()
        results: dict = {}

        async def work(job_run_id: str) -> int:
            results["run"] = await refresh(settings, method=method, reference_date=anchor, job_run_id=job_run_id)
            return results["run"].scores_written

        record = await run_batch(
            settings, job="interest", slot="interest", method=str(method),
            collection=settings.scores_collection, data_window=data_window(method, anchor), work=work,
        )
        result = results["run"]
        job_logger.info(
            result.summary(),
            extra={
                "job": "interest",
                "method": result.method,
                "job_run_id": record["_id"],
                "users_seen": result.users_seen,
                "users_scored": result.users_scored,
                "scores_written": result.scores_written,
            },
        )


async def _popularity(settings: Settings) -> None:
    """ENG-09 rung 3: qualified views per category over the window, as one batch."""
    async with job_run("popularity"):
        now = utc_now()
        detail: dict = {}

        async def work(job_run_id: str) -> int:
            rows, detail["counts"] = await popularity.compute_popularity(settings, now, job_run_id)
            return rows

        record = await run_batch(
            settings, job="popularity", slot="interest", method=writers.POPULARITY_METHOD,
            collection="ml_measurements", data_window=popularity.data_window(now), work=work,
        )
        job_logger.info("platform popularity", extra={"job": "popularity", "job_run_id": record["_id"],
                                                      "categories": record["rows_written"], **detail["counts"]})


async def _post_index(settings: Settings) -> None:
    """ENG-12: the post index the candidate sources read (also run by the sync loop)."""
    from reco.ranking import post_index

    async with job_run("post_index"):
        result = await post_index.refresh(settings)
        job_logger.info("post index", extra={"job": "post_index", **result})


async def _sync(settings: Settings) -> None:
    """ENG-04: one pass over postevents, orders and recommendationrequests."""
    async with job_run("sync"):
        copied = await sync_run.sync_once(settings)
        job_logger.info("sync pass finished", extra={"job": "sync", "copied": copied})


async def _sync_loop(settings: Settings) -> None:
    async with job_run("sync_loop"):
        await sync_run.sync_forever(settings)


async def _sync_check(settings: Settings) -> None:
    async with job_run("sync_check"), recorded_run(settings, "sync_check") as run:
        statuses = await sync_run.check_lag(settings)
        run["detail"] = {"alerts": [s["source"] for s in statuses if s["alert"]]}
        job_logger.info("sync lag", extra={"job": "sync_check", "sources": statuses})


async def _reconcile_sync(settings: Settings) -> None:
    async with job_run("reconcile_sync"):
        results = await sync_reconcile.reconcile_day(settings)
        job_logger.info(
            "sync reconciliation finished",
            extra={"job": "reconcile_sync", "passed": all(r["passed"] for r in results),
                   "sources": {r["source"]: r["passed"] for r in results}},
        )


async def _category_check(settings: Settings) -> None:
    """ENG-29 item 1: report categories outside the 23 and not in the category map."""
    async with job_run("category_check"), recorded_run(settings, "category_check") as run:
        unmapped = await category_check.check_categories(settings)
        run["detail"] = {"unmapped": len(unmapped)}
        job_logger.info("category check", extra={"job": "category_check", "unmapped": len(unmapped),
                                                 "labels": [row["label"] for row in unmapped[:20]]})


async def _nightly(settings: Settings) -> None:
    """ENG-07: every nightly job once, now."""
    async with job_run("nightly", jobs=list(scheduler.NIGHTLY)):
        failed = await scheduler.run_nightly(settings, JOBS)
        if failed:
            raise RuntimeError(f"nightly jobs failed: {', '.join(failed)}")


async def _scheduler(settings: Settings) -> None:
    """ENG-07: the nightly jobs at 2 AM IST, every day."""
    async with job_run("scheduler"):
        await scheduler.run_forever(settings, JOBS)


#: Job name -> what it runs. ENG-07 adds the rest of the nightly jobs here.
JOBS: dict[str, Callable[[Settings], Awaitable[None]]] = {
    "interest": _interest,
    "popularity": _popularity,
    "post_index": _post_index,
    "sync": _sync,
    "sync_loop": _sync_loop,
    "sync_check": _sync_check,
    "reconcile_sync": _reconcile_sync,
    "category_check": _category_check,
    "nightly": _nightly,
    "scheduler": _scheduler,
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
