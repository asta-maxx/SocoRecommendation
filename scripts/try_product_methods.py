"""ENG-17's check, "Both methods serve": one product request for a user assigned each method.

    ML_MONGO_DB=reco_demo .venv/bin/python scripts/try_product_methods.py

Runs after the product_ranking job has written both batches (checklist 16.3). Picks a
context product that method one's current batch has a list for, and two real users,
one assigned `attribute_similarity` and one `bought_together` (ENG-05). For each,
calls POST /v1/recommendations in process (the real request path, with the product
surface switched on for this run only) and checks:

    the answer is 200 with items, never the context product;
    the E1 record names the user's method in slot_methods, with the fallback step
    and the steps used, and its served_items match the response exactly.

Prints ids and counts only, never a token or a connection string. Exit 0 when both
methods served, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.responses import JSONResponse  # noqa: E402
from starlette.requests import Request  # noqa: E402

from reco.api import recommendations as api  # noqa: E402
from reco.config import get_settings, live  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.platform import fetch  # noqa: E402
from reco.slots.assignment import assign  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store import product_scores, writers  # noqa: E402

TOKEN = "try-product-methods"
LIMIT = 10


def _request(body: dict) -> Request:
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/v1/recommendations", "headers": []}, receive)


async def main() -> int:
    settings = get_settings().model_copy(update={"ingest_token": TOKEN})
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    read = live.read_file(settings.settings_file)
    if read.tunables is None:
        print(f"settings file unreadable: {read.fault}")
        return 1
    live.put_in_force(read.tunables.with_changes({"serving.surface_mode_product": "live"}), "try_product_methods")
    one, two = read.tunables.slots.product_ranking.method_one, read.tunables.slots.product_ranking.method_two
    try:
        now = datetime.now(timezone.utc)
        batch, why = await product_scores.current_batch(settings, one, now, read.tunables.interest.stale_after_hours)
        if not batch:
            print(f"no current {one} batch ({why}): run the product_ranking job first")
            return 1
        row = await store_conn.ml_db(settings)[product_scores.COLLECTION].find_one(
            {"job_run_id": batch, "context_product_id": {"$ne": None}}, {"context_product_id": 1})
        context = row["context_product_id"] if row else None
        users = [u.user_id for u in await fetch.read_records(settings, "user", limit=2000)]
        chosen = {}
        for user_id in users:
            method = assign("product_ranking", user_id, read.tunables).method
            chosen.setdefault(method, user_id)
            if len(chosen) == 2:
                break
        print(f"context product {context}; users: " + ", ".join(f"{m} -> {u}" for m, u in sorted(chosen.items())))
        ok = 0
        for method in (one, two):
            user_id = chosen.get(method)
            if not user_id or not context:
                print(f"{method}: no user or context to try")
                continue
            body = {"user_id": user_id, "surface": "product", "page": 1, "limit": LIMIT, "session_id": None,
                    "context_item_id": context}
            result = await api.recommendations(_request(body), f"Bearer {TOKEN}", settings)
            if isinstance(result, JSONResponse):
                print(f"{method}: HTTP {result.status_code} {json.loads(result.body)}")
                continue
            items = [i["item_id"] for i in result["items"]]
            record = await writers.read_served_list(settings, result["request_id"])
            slot = next((s for s in (record or {}).get("slot_methods", []) if s.get("slot") == "product_ranking"), {})
            checks = {
                "items": bool(items),
                "context never shown": context not in items,
                "method recorded": slot.get("method") == method,
                "record matches": bool(record) and record.get("served_items") == result["items"],
            }
            served = all(checks.values())
            ok += served
            print(f"{method}: {'served' if served else 'NOT served'}: {len(items)} items, fallback_step "
                  f"{result['fallback_step']}, steps used {slot.get('steps_used')}, label {slot.get('label')}; "
                  + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in checks.items()))
        print(f"both methods served: {'yes' if ok == 2 else 'no'} ({ok} of 2)")
        return 0 if ok == 2 else 1
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
