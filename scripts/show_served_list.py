"""Show the engine's record (E1) of one served list, and check it against the response (ENG-06). Read-only.

    curl ... > /tmp/eng06-feed.json
    ML_MONGO_DB=reco_demo .venv/bin/python scripts/show_served_list.py /tmp/eng06-feed.json

The file is a saved POST /v1/recommendations response. Prints the record's
headline fields, how many records exist for the request_id, and whether
served_items equals the response's items. Ids are counted, not printed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.writers import read_served_list  # noqa: E402


async def main(response: dict) -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        record = await read_served_list(settings, response["request_id"])
        if record is None:
            print("no record for this request_id")
            return 1
        count = await store_conn.ml_db(settings)["ml_events"].count_documents({"request_id": response["request_id"]})
        print("records for this request_id:", count)
        print({k: record[k] for k in ("event_code", "source", "surface", "policy_id", "fallback_step", "is_exploration", "ordering")})
        print("server_ts:", record["server_ts"].isoformat(timespec="milliseconds"))
        print("slots:", {slot: value["method"] for slot, value in record["slots"].items()})
        print(len(record["candidate_ids"]), "candidate ids,", len(record["served_items"]), "served,",
              len(record["scored_sample"]), "in the sample")
        matches = record["served_items"] == response["items"]
        print("served_items match the response:", matches)
        return 0 if count == 1 and matches else 1
    finally:
        await store_conn.close_client()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(json.loads(Path(sys.argv[1]).read_text()))))
