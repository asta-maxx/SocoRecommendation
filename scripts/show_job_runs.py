"""Show the nightly job runs and which batch is current (ENG-07). Read-only.

    .venv/bin/python scripts/show_job_runs.py
    ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_job_runs.py
    .venv/bin/python scripts/show_job_runs.py --hours 36 --by scheduler    # review of 26 Oct, point 6

ml_job_runs, newest first: job, method, outcome, rows written, duration, whether
it is the current batch, and who started it (scheduler, sync_loop or hand: review of
26 Oct 2026, point 6); then the score rows held per batch. Ids and counts only -- no
user ids. With --hours or --by: every run in that window (oldest first) instead of
the newest 12.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.scores import utc_now  # noqa: E402
from reco.store.writers import read_job_runs  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, help="every run started in the last N hours, oldest first")
    parser.add_argument("--by", choices=["scheduler", "sync_loop", "hand"], help="only runs started this way")
    args = parser.parse_args()
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        if args.hours or args.by:
            query: dict = {"started_at": {"$gte": utc_now() - timedelta(hours=args.hours or 36)}}
            if args.by:
                query["started_by"] = args.by
            runs = await store_conn.ml_db(settings)["ml_job_runs"].find(query).sort("started_at", 1).to_list(None)
            print(f"ml_job_runs in {settings.ml_mongo_db} ({settings.engine_env}), last {args.hours or 36:g} h"
                  + (f", started by {args.by}" if args.by else "") + f", oldest first: {len(runs)} runs")
        else:
            runs = await read_job_runs(settings, limit=12)
            print(f"ml_job_runs in {settings.ml_mongo_db} ({settings.engine_env}), newest first:")
        for r in runs:
            print(
                f"  {r['_id'][:8]}  {r.get('job', ''):9} {str(r.get('method')):15} {r.get('outcome', ''):9}"
                f" rows {str(r.get('rows_written', '-')):>5}  {str(r.get('duration_seconds', '-')):>6}s"
                f"  {'CURRENT' if r.get('is_current') else '       '}  by {r.get('started_by', '-'):<9}"
                f"  {r['started_at']:%Y-%m-%d %H:%M}Z  {(r.get('error') or '')[:60]}"
            )
        held = Counter([
            (d.get("method"), (d.get("job_run_id") or "none")[:8])
            async for d in store_conn.ml_db(settings)[settings.scores_collection].find({}, {"method": 1, "job_run_id": 1})
        ])
        print(f"score rows in {settings.scores_collection} by batch:")
        for (method, run), n in sorted(held.items(), key=lambda x: (str(x[0][0]), x[0][1])):
            print(f"  {str(method):15} {run}  {n}")
    finally:
        await store_conn.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
