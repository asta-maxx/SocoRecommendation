"""Show the nightly job runs and which batch is current (ENG-07). Read-only.

    .venv/bin/python scripts/show_job_runs.py
    ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_job_runs.py

ml_job_runs, newest first: job, method, outcome, rows written, duration, whether
it is the current batch; then the score rows held per batch. Ids and counts
only -- no user ids.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.writers import read_job_runs  # noqa: E402


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        runs = await read_job_runs(settings, limit=12)
        print(f"ml_job_runs in {settings.ml_mongo_db} ({settings.engine_env}), newest first:")
        for r in runs:
            print(
                f"  {r['_id'][:8]}  {r.get('job', ''):9} {str(r.get('method')):15} {r.get('outcome', ''):9}"
                f" rows {str(r.get('rows_written', '-')):>5}  {str(r.get('duration_seconds', '-')):>6}s"
                f"  {'CURRENT' if r.get('is_current') else '       '}  {(r.get('error') or '')[:60]}"
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
