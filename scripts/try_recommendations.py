"""Call POST /v1/recommendations on a running engine, time it, and check the record (ENG-06).

    INGEST_TOKEN=... .venv/bin/python scripts/try_recommendations.py http://127.0.0.1:8100 feed
    INGEST_TOKEN=... ML_MONGO_DB=reco_demo .venv/bin/python scripts/try_recommendations.py URL product [product id]

On product without a product id, the newest eligible product is the context.

Sends 20 requests (the first warms the connections and is not timed), prints
status, items and the p95 time, then reads each request's E1 record from the
engine database and checks served_items matches the response exactly. Prints
ids of items only -- never the token or a connection string.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.platform.fetch import read_newest  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.writers import read_served_list  # noqa: E402

USER = os.environ.get("TRY_USER_ID", "64f1c0ffee0000000000abcd")
CALLS = 20


def post(url: str, body: dict) -> tuple[int, dict, float]:
    request = urllib.request.Request(
        f"{url}/v1/recommendations", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('INGEST_TOKEN', '')}"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, payload = response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        status, payload = error.code, json.loads(error.read() or b"{}")
    return status, payload, (time.perf_counter() - started) * 1000


async def matches(responses: list[dict]) -> tuple[int, list[str]]:
    """Each response against its request record (review of 26 Oct, point 1): exactly one
    record per request, with the same request_id, the item ids in the same order, the
    same policy (the methods), the fallback rung, and a method for every slot."""
    settings = get_settings()
    store_conn.init_client(settings)
    problems: list[str] = []
    try:
        good = 0
        from reco.store.connection import ml_db

        for body in responses:
            rid = body["request_id"]
            count = await ml_db(settings)["ml_events"].count_documents({"request_id": rid, "event_code": "E1"})
            record = await read_served_list(settings, rid)
            checks = {
                "one record": count == 1,
                "request_id": bool(record) and record.get("request_id") == rid,
                "items and order": bool(record) and [i["item_id"] for i in record.get("served_items") or []]
                == [i["item_id"] for i in body["items"]] and record.get("served_items") == body["items"],
                "policy (methods)": bool(record) and record.get("policy_id") == body["policy_id"],
                "fallback rung": bool(record) and record.get("fallback_step") == body["fallback_step"],
                "a method per slot": bool(record) and all(s.get("method") for s in record.get("slot_methods") or [None]),
            }
            if all(checks.values()):
                good += 1
            else:
                problems.append(f"{rid}: " + ", ".join(k for k, v in checks.items() if not v))
        return good, problems
    finally:
        await store_conn.close_client()


async def newest_product() -> str:
    settings = get_settings()
    platform_conn.init_client(settings)
    try:
        return (await read_newest(settings, "product", 1))[0].product_id
    finally:
        await platform_conn.close_client()


def main(url: str, surface: str, context: str | None) -> int:
    if surface == "product" and not context:
        context = asyncio.run(newest_product())
    body = {"user_id": USER, "surface": surface, "page": 1, "limit": 10, "session_id": "ses_try"}
    if context:
        body["context_item_id"] = context
    status, first, _ = post(url, body)
    if status != 200:
        print(f"HTTP {status}: {first}")
        return 1
    timings, responses = [], []
    for _ in range(CALLS - 1):
        status, payload, ms = post(url, body)
        if status != 200:
            print(f"HTTP {status}: {payload}")
            return 1
        timings.append(ms)
        responses.append(payload)
    timings.sort()
    p95 = timings[int(0.95 * (len(timings) - 1))]
    print(f"{surface}: HTTP 200 x{len(timings)}, {len(first['items'])} items, policy_id {first['policy_id']}, "
          f"fallback_step {first['fallback_step']}")
    print(f"  first items: {[i['item_id'][-6:] + ':' + i['item_type'] for i in first['items'][:3]]}")
    print(f"  p95 {p95:.0f} ms (median {timings[len(timings) // 2]:.0f} ms) -> {'within' if p95 <= 200 else 'OVER'} 200 ms")
    good, problems = asyncio.run(matches(responses))
    print(f"  records matching the response (one each; request_id, items in order, methods, fallback rung): "
          f"{good} of {len(responses)}")
    for line in problems[:5]:
        print(f"    mismatch {line}")
    # With the test-only limits in force (far from the database) the speed is reported,
    # not judged: the 200 ms check needs a server next to the database.
    test_limits = os.environ.get("REQUEST_BUDGET_MS") or os.environ.get("SOURCE_TIME_LIMIT_MS")
    if test_limits:
        print(f"  speed not judged: test-only limits in force (REQUEST_BUDGET_MS={os.environ.get('REQUEST_BUDGET_MS')}, "
              f"SOURCE_TIME_LIMIT_MS={os.environ.get('SOURCE_TIME_LIMIT_MS')})")
    return 0 if good == len(responses) and (p95 <= 200 or test_limits) else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(args[0], args[1], args[2] if len(args) > 2 else None))
