"""Show what the platform login may do, without writing anything. ENG-01, DB-02.

    .venv/bin/python scripts/check_platform_access.py

Asks MongoDB which roles and privileges the platform login holds
(connectionStatus), rather than trying a write: if the login were not read-only,
a test write would land in SOCO's data. Then reads a few platform collections.
Prints hosts, database names and role names only -- never a connection string.
Exits 0 only if the login can read and holds no data-writing action.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import _hosts_of, get_settings  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402

#: Actions that change data or users. killCursors is deliberately absent: it only
#: closes the login's own cursors and is part of MongoDB's built-in read role.
WRITE_ACTIONS = {
    "insert", "update", "remove", "createCollection", "dropCollection", "createIndex",
    "dropIndex", "dropDatabase", "renameCollectionSameDB", "collMod", "convertToCapped",
    "createUser", "dropUser", "grantRole", "revokeRole", "bypassDocumentValidation",
}
READ_CHECK = ["users", "posts", "postevents", "orders", "follows", "products"]


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        db = platform_conn.app_db(settings)
        status = await db.command({"connectionStatus": 1, "showPrivileges": True})
        info = status["authInfo"]
        roles = sorted(f"{r['role']}@{r['db']}" for r in info.get("authenticatedUserRoles", []))
        writes = sorted(
            {
                f"{action} on {p.get('resource', {}).get('db') or 'cluster'}"
                for p in info.get("authenticatedUserPrivileges", [])
                for action in p.get("actions", [])
                if action in WRITE_ACTIONS
            }
        )
        names = set(await db.list_collection_names())
        readable = {name: name in names for name in READ_CHECK}

        print(f"platform database  {settings.app_mongo_db} on {', '.join(_hosts_of(settings.app_mongo_uri))}")
        print(f"logged in          {'yes' if info.get('authenticatedUsers') else 'NO'}")
        print(f"roles              {', '.join(roles) or 'none'}")
        print(f"write actions      {', '.join(writes) or 'NONE (read-only)'}")
        print("reads              " + ", ".join(f"{n} {'ok' if ok else 'MISSING'}" for n, ok in readable.items()))
        print(f"users (sample)     {await db['users'].estimated_document_count()} documents")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()

    return 0 if info.get("authenticatedUsers") and not writes and all(readable.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
