"""Fill a test platform database with constructed platform-shaped data. ENG-29 item 8.

    .venv/bin/python scripts/seed_test_platform.py soco_platform_test

Writes every platform collection the engine reads (tests/platform_dataset.py)
into the named database on the ENGINE cluster (ML_MONGO_URI; the platform login
is read-only). Each collection is emptied first, so a run always leaves the same
data. Then every document is read back through the ENG-03 parsers and the
result printed.

Refuses any name without "test" in it, and the configured platform and engine
databases, so it can never write into real data. To point the engine at it:
APP_MONGO_URI=<engine cluster URI> APP_MONGO_DB=soco_platform_test.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import AsyncMongoClient  # noqa: E402

from reco.config import get_settings  # noqa: E402
from tests.platform_dataset import build_dataset  # noqa: E402
from tests.test_platform_dataset import parse_everything  # noqa: E402


async def main(name: str) -> int:
    settings = get_settings()
    if "test" not in name or name in (settings.app_mongo_db, settings.ml_mongo_db):
        print(f"refusing {name!r}: the name must contain 'test' and be neither the platform nor the engine database")
        return 2
    dataset, cases = build_dataset()
    client = AsyncMongoClient(settings.ml_mongo_uri, tz_aware=True)
    try:
        db = client[name]
        for collection, documents in dataset.items():
            await db[collection].delete_many({})
            if documents:
                await db[collection].insert_many(documents)
            print(f"  {collection:24} {len(documents):3} documents")
    finally:
        await client.close()
    failures = parse_everything(dataset)
    print(f"{sum(map(len, dataset.values()))} documents in {name}; {len(cases)} named cases; "
          f"{'all parse' if not failures else f'{len(failures)} failed to parse: {failures[:5]}'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
