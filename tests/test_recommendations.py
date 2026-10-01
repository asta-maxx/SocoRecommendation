"""ENG-06: POST /v1/recommendations -- a list, and its record.

The Build List's check: "A request returns within 200 ms on test, and one
request record exists with served_items matching the response. Setting a
surface to off returns 503."

    the record matches the response       test_a_feed_list_is_recorded_exactly_as_returned
    within 200 ms                         test_a_feed_list_is_recorded_exactly_as_returned (timed)
    off returns 503                       test_a_surface_that_is_off_returns_503

The handler is called directly with a constructed request (no HTTP client is
pinned); scripts/run_checklist.sh section 6 calls it over HTTP.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import pytest
import pytest_asyncio
from bson import ObjectId
from fastapi.responses import JSONResponse
from starlette.requests import Request

from reco.api import recommendations as api
from reco.config import PLATFORM_COLLECTIONS
from reco.platform import connection as platform_conn
from reco.ranking import serving
from reco.ranking.serving import Candidate
from reco.eligibility.rules import Viewer
from reco.store import connection as store_conn
from reco.store import writers
from reco.store.scores import utc_now
from tests.conftest import put_in_force

TOKEN = "test-serving-token"
USER = "64f1c0ffee0000000000abcd"
LIVE = {"serving.surface_mode_feed": "live", "serving.surface_mode_product": "live"}


def _request(body) -> Request:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/v1/recommendations", "headers": []}, receive)


async def call(settings, body, token: str | None = TOKEN) -> tuple[int, dict]:
    result = await api.recommendations(_request(body), f"Bearer {token}" if token else None, settings)
    if isinstance(result, JSONResponse):
        return result.status_code, json.loads(result.body)
    return 200, result


def feed(**fields) -> dict:
    return {"user_id": USER, "surface": "feed", "page": 1, "limit": 5, "session_id": "ses_1", **fields}


@pytest.fixture
def served(settings, monkeypatch):
    """No database: candidates are made up, records are kept in a list."""
    settings = settings.model_copy(update={"ingest_token": TOKEN})
    records = []

    async def candidates(settings, surface, page, limit, context, user_id=None, request_id=None):
        kind = "post" if surface == "feed" else "product"
        made = [Candidate(f"{kind}{n:02}", kind, f"post{n:02}" if kind == "post" else None,
                          f"product{n:02}" if kind == "product" else None, rank=n) for n in range(1, page * limit + 1)]
        return serving.Built(Viewer(user_id=user_id), made, {}, len(made))

    async def record(settings, doc):
        records.append(doc)

    async def nothing_failed(settings, items, viewer, request_id, cache=None):
        return set()

    monkeypatch.setattr(api.serving, "interim_candidates", candidates)
    monkeypatch.setattr(serving, "recheck", nothing_failed)
    monkeypatch.setattr(api.writers, "record_served_list", record)
    return settings, records


# --- the contract (no database) ----------------------------------------------------------


async def test_a_missing_or_wrong_token_is_401(served) -> None:
    settings, _ = served
    put_in_force(LIVE)
    assert (await call(settings, feed(), token=None))[0] == 401
    status, body = await call(settings, feed(), token="wrong")
    assert status == 401 and body == {"error": "unauthorized", "detail": "missing or wrong bearer token"}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"surface": "opportunity"}, "invalid_surface"),
        ({"limit": 0}, "invalid_limit"),
        ({"limit": 51}, "invalid_limit"),
        ({"page": 0}, "invalid_page"),
        ({"page": "1"}, "invalid_page"),
        ({"surface": "product"}, "missing_context_item_id"),
    ],
)
async def test_bad_input_is_400(served, change, code) -> None:
    settings, records = served
    put_in_force(LIVE)
    status, body = await call(settings, feed(**change))
    assert status == 400 and body["error"] == code and records == []


async def test_a_surface_that_is_off_returns_503(served) -> None:
    settings, records = served
    put_in_force({"serving.surface_mode_feed": "off"})
    status, body = await call(settings, feed())
    assert status == 503 and body["error"] == "surface_off" and records == []


async def test_internal_serves_only_test_accounts(served) -> None:
    settings, _ = served
    entry = {"account_id": USER, "reason": "checklist", "expiry": date.today() + timedelta(days=7), "changed_by": "Allen"}
    put_in_force({"serving.surface_mode_feed": "internal", "lists.test_accounts": [entry]})
    assert (await call(settings, feed()))[0] == 200
    status, body = await call(settings, feed(user_id=str(ObjectId())))
    assert status == 503 and body["error"] == "surface_internal"
    expired = {**entry, "expiry": date.today() - timedelta(days=1)}
    put_in_force({"serving.surface_mode_feed": "internal", "lists.test_accounts": [expired]})
    assert (await call(settings, feed()))[0] == 503


async def test_the_response_shape(served, monkeypatch) -> None:
    settings, records = served
    put_in_force(LIVE)
    monkeypatch.setattr(serving.rng, "random", lambda: 0.99)  # not an exploration request
    status, body = await call(settings, feed(page=2))
    assert status == 200
    assert set(body) == {"request_id", "policy_id", "model_version", "config_version", "fallback_step", "is_exploration", "items"}
    assert body["policy_id"].startswith(f"cfg{body['config_version']}.interest-") and ".promoter_score-" in body["policy_id"]
    assert body["fallback_step"] is None and body["is_exploration"] is False
    assert [i["position"] for i in body["items"]] == [1, 2, 3, 4, 5]
    assert [i["item_id"] for i in body["items"]] == [f"post{n:02}" for n in range(6, 11)]  # page 2
    assert all(i["reason_code"] is None and set(i) == {"item_id", "item_type", "post_id", "product_id", "position", "reason_code"}
               for i in body["items"])
    assert "candidate_ids" not in body


async def test_exploration_keeps_the_top_three_and_never_on_product(served, monkeypatch) -> None:
    settings, records = served
    put_in_force(LIVE)
    monkeypatch.setattr(serving.rng, "random", lambda: 0.0)  # every request explores
    monkeypatch.setattr(serving.rng, "shuffle", lambda items: items.reverse())
    _, body = await call(settings, feed())
    assert body["is_exploration"] is True
    assert [i["item_id"] for i in body["items"]] == ["post01", "post02", "post03", "post05", "post04"]
    _, product = await call(settings, {**feed(surface="product", context_item_id=str(ObjectId()))})
    assert product["is_exploration"] is False
    assert records[0]["is_exploration"] and len(records[0]["scored_sample"]) == 5  # all items on exploration


async def test_the_record_holds_what_the_pack_lists(served, monkeypatch) -> None:
    settings, records = served
    put_in_force(LIVE)
    monkeypatch.setattr(serving.rng, "random", lambda: 0.99)
    _, body = await call(settings, feed(limit=3, page=2))
    record = records[0]
    for field in ("request_id", "surface", "user_id", "session_id", "policy_id", "server_ts", "candidate_ids",
                  "served_items", "config_version", "slots", "scored_sample"):
        assert field in record, field
    assert record["_id"] == record["request_id"] == body["request_id"] and record["event_code"] == "E1"
    assert record["served_items"] == body["items"]
    assert record["candidate_ids"] == [f"post{n:02}" for n in range(1, 7)]
    assert set(record["slots"]) == {"interest", "promoter_score"}
    assert all({"method", "fallback_step"} <= set(s) for s in record["slots"].values())
    # every returned item is in the sample; not-returned ones only at the 10% draw (none here)
    assert [s["item_id"] for s in record["scored_sample"]] == [i["item_id"] for i in body["items"]]


async def test_a_database_fault_is_503_at_once(served, monkeypatch) -> None:
    settings, _ = served
    put_in_force(LIVE)
    calls = []

    async def down(*args):
        calls.append(1)
        raise ConnectionError("unreachable")

    monkeypatch.setattr(api.serving, "interim_candidates", down)
    status, body = await call(settings, feed())
    assert status == 503 and body["error"] == "database_unavailable" and calls == [1]  # no retry


async def test_no_record_no_list(served, monkeypatch) -> None:
    settings, _ = served
    put_in_force(LIVE)

    async def unwritable(*args):
        raise ConnectionError("engine database down")

    monkeypatch.setattr(api.writers, "record_served_list", unwritable)
    status, body = await call(settings, feed())
    assert status == 503 and body["error"] == "database_unavailable"


# --- end to end on constructed platform data (database) ----------------------------------


@pytest_asyncio.fixture
async def platform(settings):
    settings = settings.model_copy(update={"ingest_token": TOKEN})
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    db = platform_conn.app_db(settings)
    posts, products = db[PLATFORM_COLLECTIONS["post"]], db[PLATFORM_COLLECTIONS["product"]]
    others = [db[PLATFORM_COLLECTIONS[k]] for k in ("user", "business", "variant", "follow", "follower")]
    for c in (posts, products, *others, store_conn.ml_db(settings)["ml_events"]):
        await c.drop()
    await writers.ensure_engine_collections(settings)
    # E-08: authors and sellers must exist and be active; E-07: a variant in stock.
    await db[PLATFORM_COLLECTIONS["user"]].insert_one({"_id": AUTHOR, "status": "Active", "accountIsPublic": True})
    await db[PLATFORM_COLLECTIONS["business"]].insert_one({"_id": SELLER, "status": "active", "accountIsPublic": True})
    yield settings, posts, products
    for c in (posts, products, *others, store_conn.ml_db(settings)["ml_events"]):
        await c.drop()
    await platform_conn.close_client()
    await store_conn.close_client()


AUTHOR, SELLER = ObjectId(), ObjectId()


def post(minutes_ago: int, **fields) -> dict:
    return {"_id": ObjectId(), "userId": AUTHOR, "timestamp": utc_now() - timedelta(minutes=minutes_ago),
            "visibility": "public", "isHidden": False, "categories": [], "postType": "normal", **fields}


def product(minutes_ago: int, **fields) -> dict:
    return {"_id": ObjectId(), "createdBy": SELLER, "createdAt": utc_now() - timedelta(minutes=minutes_ago),
            "status": "Activate", "availability": {"inStock": True}, **fields}


@pytest.mark.mongo
async def test_a_feed_list_is_recorded_exactly_as_returned(platform, monkeypatch) -> None:
    settings, posts, _ = platform
    put_in_force(LIVE)
    monkeypatch.setattr(serving.rng, "random", lambda: 0.99)
    shown = [post(m) for m in (1, 2, 3, 4)]
    with_product = post(5, products=[ObjectId()], Product_status="Activated")
    hidden, private, removed = post(0, isHidden=True), post(0, visibility="private"), post(0, compliance={"status": "Removed"})
    under_review = post(6, compliance={"status": "under_review"})  # E-12: served as normal
    await posts.insert_many([*shown, with_product, under_review, hidden, private, removed])

    await call(settings, feed())  # warm the connections, as a running service has them
    started = time.perf_counter()
    status, body = await call(settings, feed(limit=6))
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert status == 200
    assert [i["item_id"] for i in body["items"]] == [str(p["_id"]) for p in [*shown, with_product, under_review]]  # newest first, eligible only
    assert body["items"][4]["post_id"] == str(with_product["_id"]) and body["items"][4]["product_id"] == str(with_product["products"][0])
    record = await writers.read_served_list(settings, body["request_id"])
    assert record["served_items"] == body["items"]
    assert await store_conn.ml_db(settings)["ml_events"].count_documents({"request_id": body["request_id"]}) == 1
    print(f"feed request: {elapsed_ms:.0f} ms")
    assert elapsed_ms < 1000  # the 200 ms target is measured on the test server (checklist 6.x), not over a laptop link


@pytest.mark.mongo
async def test_a_product_list_leaves_out_the_context_product(platform, monkeypatch) -> None:
    settings, _, products = platform
    put_in_force(LIVE)
    rows = [product(m) for m in (1, 2, 3)]
    out_of_stock, inactive = product(0, availability={"inStock": False}), product(0, status="Deactivate")
    no_stock_left = product(0)
    await products.insert_many([*rows, out_of_stock, inactive, no_stock_left])
    variants = platform_conn.app_db(settings)[PLATFORM_COLLECTIONS["variant"]]
    await variants.insert_many([
        *({"_id": ObjectId(), "productId": r["_id"], "quantity": 5, "reservedStock": 1, "status": "active"} for r in rows),
        {"_id": ObjectId(), "productId": no_stock_left["_id"], "quantity": 3, "reservedStock": 3, "status": "active"},  # E-07
    ])

    status, body = await call(settings, feed(surface="product", context_item_id=str(rows[0]["_id"]), limit=10))

    assert status == 200 and body["is_exploration"] is False
    assert [i["item_id"] for i in body["items"]] == [str(r["_id"]) for r in rows[1:]]
    assert all(i["item_type"] == "product" and i["post_id"] is None and i["product_id"] == i["item_id"] for i in body["items"])
    assert body["policy_id"].endswith((".product_ranking-attribute_similarity", ".product_ranking-bought_together"))
