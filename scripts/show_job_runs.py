"""Print the engine's job runs (ml_job_runs), with who started each (review of 26 Oct 2026, point 6).

    .venv/bin/python scripts/show_job_runs.py                 # the last 36 hours
    .venv/bin/python scripts/show_job_runs.py --hours 72 --by scheduler

One line per run: when it started, the job and method, who started it (scheduler,
sync_loop or hand), the outcome, rows written, how long it took, and whether its
batch is current. Prints the engine database name, never a connection string.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reco.config import get_settings  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.scores import utc_now  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=36)
    parser.add_argument("--by", choices=["scheduler", "sync_loop", "hand"], help="only runs started this way")
    args = parser.parse_args()
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        query = {"started_at": {"$gte": utc_now() - timedelta(hours=args.hours)}}
        if args.by:
            query["started_by"] = args.by
        rows = await store_conn.ml_db(settings)["ml_job_runs"].find(query).sort("started_at", 1).to_list(None)
        print(f"engine db {settings.ml_mongo_db} ({settings.engine_env}): {len(rows)} runs in the last {args.hours:g} h"
              + (f", started by {args.by}" if args.by else ""))
        for r in rows:
            print(f"{r['started_at']:%Y-%m-%d %H:%M:%S}Z  {r.get('job', ''):<16} {str(r.get('method') or ''):<22} "
                  f"by {r.get('started_by', '(not recorded)'):<10} {r.get('outcome', ''):<10} "
                  f"rows {r.get('rows_written', 0):<7} {r.get('duration_seconds', 0) or 0:>8.1f} s"
                  f"{'  current' if r.get('is_current') else ''}")
        return 0
    finally:
        await store_conn.close_client()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
