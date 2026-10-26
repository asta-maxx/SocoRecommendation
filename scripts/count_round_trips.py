"""How many database round trips one served list makes (the review of 26 Oct 2026, point 1).

    ML_MONGO_DB=<an engine database with current batches> .venv/bin/python scripts/count_round_trips.py

Calls POST /v1/recommendations in process (the real request path, both surfaces
switched on for this run only), once for the feed and once for each product
method, and counts every command sent to MongoDB during each request, split by
platform and engine database and by collection. Commands sent in parallel
(asyncio.gather) still count one each; the "sequential steps" figure is the
number of waves of commands that had to wait for the one before (the round trips
that add up on a slow link). Prints counts only, never a token or a connection
string.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import monitoring  # noqa: E402


class Counting(monitoring.CommandListener):
    def __init__(self) -> None:
        self.events: list[tuple[float, float, str, str, str]] = []  # start, end, db, command, collection
        self._open: dict[int, tuple[float, str, str, str]] = {}

    def started(self, event) -> None:
        cmd = event.command_name
        coll = event.command.get(cmd) if isinstance(event.command.get(cmd), str) else ""
        self._open[event.request_id] = (time.perf_counter(), event.database_name, cmd, coll)

    def _end(self, event) -> None:
        start, db, cmd, coll = self._open.pop(event.request_id, (time.perf_counter(), "?", event.command_name, ""))
        self.events.append((start, time.perf_counter(), db, cmd, coll))

    succeeded = _end
    failed = _end


LISTENER = Counting()
monitoring.register(LISTENER)

from fastapi.responses import JSONResponse  # noqa: E402
from starlette.requests import Request  # noqa: E402

from reco.api import recommendations as api  # noqa: E402
from reco.config import get_settings, live  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.platform import fetch  # noqa: E402
from reco.slots.assignment import assign  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store import product_scores  # noqa: E402

TOKEN = "count-round-trips"
IGNORED = {"hello", "isMaster", "ismaster", "ping", "endSessions", "saslStart", "saslContinue"}


def _request(body: dict) -> Request:
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/v1/recommendations", "headers": []}, receive)


def waves(events) -> int:
    """Sequential steps: commands that overlap in time count as one wave."""
    count, end = 0, -1.0
    for start, stop, *_ in sorted(events):
        if start >= end:
            count += 1
            end = stop
        else:
            end = max(end, stop)
    return count


async def one(settings, body, label: str) -> None:
    LISTENER.events.clear()
    started = time.perf_counter()
    result = await api.recommendations(_request(body), f"Bearer {TOKEN}", settings)
    ms = (time.perf_counter() - started) * 1000
    events = [e for e in LISTENER.events if e[3] not in IGNORED]
    status = result.status_code if isinstance(result, JSONResponse) else 200
    by_db = Counter("platform" if e[2] == settings.app_mongo_db else "engine" for e in events)
    by_coll = Counter(f"{'platform' if e[2] == settings.app_mongo_db else 'engine'}.{e[4] or e[3]}" for e in events)
    print(f"{label}: HTTP {status}, {ms:.0f} ms from here; {len(events)} database commands "
          f"(platform {by_db['platform']}, engine {by_db['engine']}), {waves(events)} sequential steps")
    for name, n in sorted(by_coll.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {n:3}  {name}")


async def main() -> int:
    settings = get_settings().model_copy(update={"ingest_token": TOKEN})
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    read = live.read_file(settings.settings_file)
    live.put_in_force(read.tunables.with_changes(
        {"serving.surface_mode_feed": "live", "serving.surface_mode_product": "live"}), "count_round_trips")
    try:
        users = [u.user_id for u in await fetch.read_records(settings, "user", limit=500)]
        one_m, two_m = read.tunables.slots.product_ranking.method_one, read.tunables.slots.product_ranking.method_two
        by_method = {}
        for user_id in users:
            by_method.setdefault(assign("product_ranking", user_id, read.tunables).method, user_id)
        from datetime import datetime, timezone
        batch, _ = await product_scores.current_batch(settings, one_m, datetime.now(timezone.utc), 48)
        row = await store_conn.ml_db(settings)[product_scores.COLLECTION].find_one(
            {"job_run_id": batch, "context_product_id": {"$ne": None}}, {"context_product_id": 1}) if batch else None
        context = row["context_product_id"] if row else None
        await one(settings, {"user_id": users[0], "surface": "feed", "page": 1, "limit": 20, "session_id": None},
                  "warm-up (connections opened, not counted)")
        await one(settings, {"user_id": users[1], "surface": "feed", "page": 1, "limit": 20, "session_id": None},
                  "feed, page 1, limit 20")
        for method in (one_m, two_m):
            if by_method.get(method) and context:
                await one(settings, {"user_id": by_method[method], "surface": "product", "page": 1, "limit": 10,
                                     "session_id": None, "context_item_id": context}, f"product ({method}), limit 10")
        return 0
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
