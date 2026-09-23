"""Load the generated dataset into the ml_demo_* collections.

    python scripts/load_demo_data.py

The generator (Kala's, DS-015 task 8) produces JSON files. The engine reads
collections -- that is the whole point of task 6, and it is what removes the need
for a demo branch. Something has to bridge the two, and no numbered task covers
it, so this is it.

Idempotent: each collection is dropped and refilled, so running it twice leaves
the same three collections rather than six copies of everything.

Writes only to ml_ names, through the same guard as every other write in the
service. Timestamps are converted from ISO strings to real BSON dates, because a
string sorts and compares differently and would quietly break every age
calculation downstream.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.writers import replace_collection  # noqa: E402

DEMO_DIR = ROOT / "reference" / "demo"

#: file -> the settings attribute naming its target collection.
SOURCES = {
    "ml_demo_events.json": "events_collection",
    "ml_demo_users.json": "users_collection",
    "ml_demo_orders.json": "orders_collection",
}

#: Fields holding an instant. Anything here that arrives as an ISO string is
#: converted; a null stays null, because a missing timestamp is a deliberate
#: case that two of the drop-and-count rules depend on.
DATE_FIELDS = ("timestamp", "placed_at", "cancelled_at", "created_at")


def with_real_dates(document: dict) -> dict:
    out = dict(document)
    for field in DATE_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value:
            try:
                out[field] = datetime.fromisoformat(value)
            except ValueError:
                pass
    return out


async def main() -> None:
    settings = get_settings()

    if settings.data_profile != "demo":
        raise SystemExit(
            f"DATA_PROFILE is {settings.data_profile!r}. This loads the demo "
            f"dataset into the demo collections; run it with DATA_PROFILE=demo "
            f"so it cannot write generated data where live data belongs."
        )

    if not DEMO_DIR.exists():
        raise SystemExit(
            f"{DEMO_DIR} not found. Unpack reference/demo.zip into reference/."
        )

    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        total = 0
        for filename, attribute in SOURCES.items():
            path = DEMO_DIR / filename
            if not path.exists():
                raise SystemExit(f"{path} is missing.")

            documents = [
                with_real_dates(d)
                for d in json.loads(path.read_text(encoding="utf-8"))
            ]
            target = getattr(settings, attribute)
            written = await replace_collection(settings, target, documents)
            print(f"  {target:<32} {written:>6} documents")
            total += written

        print(f"\nLoaded {total} documents into {settings.ml_mongo_db}.")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()


if __name__ == "__main__":
    asyncio.run(main())
