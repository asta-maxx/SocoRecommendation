"""Show what is in the engine's event log (ml_events), and the switch date. Read-only.

    .venv/bin/python scripts/show_events.py
    ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_events.py

Counts by event name, the newest few events (name, time, event_id only -- no
user ids), and the ENG-03/ENG-04 switch date if one has been fixed.
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
from reco.store.writers import read_switch_date  # noqa: E402


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        events = store_conn.ml_db(settings)["ml_events"]
        names = Counter([doc["event_name"] async for doc in events.find({}, {"event_name": 1})])
        print(f"ml_events in {settings.ml_mongo_db} ({settings.engine_env}): {sum(names.values())} events")
        for name, count in sorted(names.items()):
            print(f"  {name:28}{count}")
        newest = events.find({}, {"event_name": 1, "server_ts": 1, "event_id": 1}).sort("received_at", -1).limit(5)
        print("newest:")
        async for doc in newest:
            print(f"  {doc.get('server_ts')}  {doc['event_name']:28} {doc['event_id']}")
        switch = await read_switch_date(settings)
        print(f"switch date: {switch or 'not fixed yet (the old collections are still the source)'}")
    finally:
        await store_conn.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
