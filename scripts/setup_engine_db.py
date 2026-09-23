"""Set up one environment's engine database. ENG-01.

    ENGINE_ENV=dev  python scripts/setup_engine_db.py
    ENGINE_ENV=test python scripts/setup_engine_db.py

Creates the twelve ml_ collections and the ml_events indexes, then confirms the
platform database answers on the read-only connection. Idempotent: run it again
and nothing changes. Prints database names and hosts, never a connection string.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import ENGINE_COLLECTIONS, _hosts_of, get_settings  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.writers import ensure_engine_collections, ensure_indexes  # noqa: E402


async def main() -> int:
    settings = get_settings()
    print(f"environment      {settings.engine_env}")
    print(f"engine database  {settings.ml_mongo_db} on {', '.join(_hosts_of(settings.ml_mongo_uri))}")
    print(f"platform (read)  {settings.app_mongo_db} on {', '.join(_hosts_of(settings.app_mongo_uri))}")

    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        created = await ensure_engine_collections(settings)
        await ensure_indexes(settings)

        present = set(await store_conn.ml_db(settings).list_collection_names())
        missing = [name for name in ENGINE_COLLECTIONS if name not in present]
        print(f"created          {', '.join(created) or 'nothing (all present)'}")
        print(f"engine check     {len(ENGINE_COLLECTIONS) - len(missing)} of {len(ENGINE_COLLECTIONS)} collections present")

        platform_ok = await platform_conn.ping(settings)
        print(f"platform ping    {'ok' if platform_ok else 'FAILED'}")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()

    return 0 if not missing and platform_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
