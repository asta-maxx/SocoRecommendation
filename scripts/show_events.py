"""Show what the engine sync has copied, and how far behind it is. Read-only.

    .venv/bin/python scripts/show_events.py
    ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py

ml_events by source collection and E code, ml_orders, and each source's
checkpoint and last successful run from ml_sync_state (ENG-04). Prints counts,
codes and times only -- no user ids.
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


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        db = store_conn.ml_db(settings)
        counts = Counter(
            [(d.get("source"), d.get("event_code") or "-") async for d in db["ml_events"].find({}, {"source": 1, "event_code": 1})]
        )
        print(f"ml_events in {settings.ml_mongo_db} ({settings.engine_env}): {sum(counts.values())} copies")
        for (source, code), n in sorted(counts.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
            print(f"  {str(source):26}{code:6}{n}")
        print(f"ml_orders: {await db['ml_orders'].count_documents({})} orders")
        print("sync state:")
        async for state in db["ml_sync_state"].find({}):
            backfill = state.get("backfill") or {}
            run = state.get("last_run") or {}
            print(
                f"  {state['_id']:26} backfill {'done' if backfill.get('done') else 'in progress'}"
                f" ({backfill.get('copied', 0)} copied) | checkpoint {state.get('checkpoint')}"
                f" | current as of {state.get('current_as_of')} | last run {run.get('outcome')}"
            )
        print("reconciliation:")
        async for r in db["ml_measurements"].find({"measure": "sync_reconciliation"}).sort("day", -1).limit(9):
            print(
                f"  {r['day']}  {r['source']:26} {'PASSED' if r['passed'] else 'NOT PASSED'}"
                f"  ids {r['platform_ids']}/{r['engine_ids']}  missing {r['missing']}"
                f"  mismatched {r['mismatched']}  extra {r['extra']}  re-read {r['reread']}"
            )
    finally:
        await store_conn.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
