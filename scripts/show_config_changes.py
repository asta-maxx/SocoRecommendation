"""Print the settings change log, newest last. ENG-02 item 4.

    .venv/bin/python scripts/show_config_changes.py            # the engine database in .env
    ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_config_changes.py

One line per recorded version: when, which version replaced which, who made it,
and every changed setting with its old and new value. Read-only.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        changes = store_conn.ml_db(settings)["ml_config_changes"]
        print(f"ml_config_changes in {settings.ml_mongo_db} ({settings.engine_env})")
        count = 0
        async for record in changes.find({}, {"values": 0}).sort("changed_at", 1):
            count += 1
            when = record["changed_at"].isoformat(timespec="seconds")
            print(
                f"\n{when}  version {record['previous_version']} -> {record['config_version']}"
                f"  by {record['changed_by']}"
            )
            for change in record.get("changes") or []:
                print(f"    {change['key']}: {change['old']} -> {change['new']}")
            if not record.get("changes"):
                print("    (put in force; no values changed)")
        if not count:
            print("  no changes recorded yet")
    finally:
        await store_conn.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
