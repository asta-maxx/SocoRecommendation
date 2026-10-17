"""ml_product_scores: M5's stored lists, both methods. ENG-17.

    await read_popularity_rows(settings, since)           clicks and add-to-carts copies, by product_id
    await read_basket_orders(settings)                    every order copy, with method two's fields
    await write_product_scores(settings, rows)            one batch's rows (each carries job_run_id)
    await current_batch(settings, method, now, hours)     (job_run_id, why): the batch requests read
    await read_product_list(settings, batch, product_id)  one viewed product's list, by rank
    await read_category_list(settings, batch, category)   fallback step 2's list, by rank
    await ensure_product_score_indexes(settings)          called from writers.ensure_indexes

One row per (list, rank). Two kinds of list:

    list "similar" / "bought_together"   context_product_id (the product viewed),
        product_id, score, rank (1 = best), components (method one: each component's
        value, None where missing) or lift, co_purchases (method two),
        label (method two: "intent" over carts until APP-22 passes, else "checkout")
    list "category_popular"              category_id (top-level), product_id,
        score (clicks + add-to-carts, 30 days), rank: fallback step 2

and on every row: method, slot "product_ranking", job_run_id, model_version,
config_version, computed_at, data_window (ENG-07). Both methods' batches carry the
category lists, so each batch answers its own requests whole.

Each method is an ENG-07 batch (reco.jobs.batches.run_batch), so a request reads
only the batch marked current. Writes go through writers._collection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from reco.config import Settings
from reco.store.connection import ml_db
from reco.store.writers import _collection, _ensure_index

COLLECTION = "ml_product_scores"
JOB = "product_ranking"
SLOT = "product_ranking"
SIMILAR = "similar"
BOUGHT_TOGETHER = "bought_together"
CATEGORY_POPULAR = "category_popular"

#: The postevents types M5's popularity counts (ENG-17: "clicks on the product's cards
#: plus add-to-carts"; add-to-carts from add_to_cart rows only, by product_id).
#: product_click is the older builds' spelling of click (sheet 4).
POPULARITY_EVENT_TYPES = ("click", "product_click", "add_to_cart")
_EVENT_FIELDS = {f: 1 for f in ("user_id", "event_type", "product_id", "created_at")}
_ORDER_FIELDS = {f: 1 for f in ("order_id", "buyer_id", "product_id", "checkout_id", "status", "is_incognito",
                                "created_at")}
_WRITE_CHUNK = 5000
#: A stored list is at most product.stored_per_category (1,000 at most) rows: one reply.
_READ_BATCH = 1000


async def ensure_product_score_indexes(settings: Settings) -> None:
    """(job_run_id, context_product_id, rank): a request reads one product's list of
    the current batch in rank order. (job_run_id, category_id, rank): step 2's list.
    (method, job_run_id): removing a superseded or failed batch."""
    collection = _collection(ml_db(settings), COLLECTION)
    await _ensure_index(collection, [("job_run_id", 1), ("context_product_id", 1), ("rank", 1)], "run_context_rank")
    await _ensure_index(collection, [("job_run_id", 1), ("category_id", 1), ("rank", 1)], "run_category_rank")
    await _ensure_index(collection, [("method", 1), ("job_run_id", 1)], "method_run")


async def read_popularity_rows(settings: Settings, since: datetime) -> list[dict[str, Any]]:
    """The engine's copies of click and add_to_cart rows with a product id since `since`
    (undo rows and undone actions left out)."""
    cursor = ml_db(settings)["ml_events"].find(
        {"kind": "postevent", "event_type": {"$in": list(POPULARITY_EVENT_TYPES)}, "product_id": {"$ne": None},
         "created_at": {"$gte": since}, "undone_at": None, "undo_of": None},
        _EVENT_FIELDS,
    )
    return await cursor.to_list(None)


async def read_basket_orders(settings: Settings) -> list[dict[str, Any]]:
    """Every order copy, with the fields method two reads (never a buyer's name)."""
    return await ml_db(settings)["ml_orders"].find({}, _ORDER_FIELDS).to_list(None)


async def write_product_scores(settings: Settings, rows: list[dict[str, Any]]) -> int:
    """Insert one batch's rows. Each already carries its job_run_id."""
    collection = _collection(ml_db(settings), COLLECTION)
    written = 0
    for start in range(0, len(rows), _WRITE_CHUNK):
        result = await collection.insert_many(rows[start:start + _WRITE_CHUNK], ordered=False)
        written += len(result.inserted_ids)
    return written


async def current_batch(settings: Settings, method: str, now: datetime, stale_after_hours: float) -> tuple[str | None, str]:
    """The current batch of `method` and why: (job_run_id, "current"), or (None, why)
    when none is current yet or the current one is older than `stale_after_hours`
    (ENG-22 check 10: a stale batch is not read, the ladder takes over)."""
    run = await ml_db(settings)["ml_job_runs"].find_one(
        {"job": JOB, "method": method, "is_current": True}, {"finished_at": 1},
        sort=[("finished_at", DESCENDING)],
    )
    if run is None:
        return None, "no current batch"
    finished = run.get("finished_at")
    if finished is not None and finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    if finished is None or now - finished > timedelta(hours=stale_after_hours):
        return None, "stale"
    return run["_id"], "current"


async def read_product_list(settings: Settings, job_run_id: str | None, product_id: str) -> list[str]:
    """One viewed product's stored list from batch `job_run_id`, by rank (product ids)."""
    if not job_run_id or not product_id:
        return []
    cursor = ml_db(settings)[COLLECTION].find(
        {"job_run_id": job_run_id, "context_product_id": str(product_id)}, {"_id": 0, "product_id": 1, "rank": 1},
    ).sort("rank", ASCENDING).batch_size(_READ_BATCH)
    return [row["product_id"] async for row in cursor]


async def read_category_list(settings: Settings, job_run_id: str | None, category_id: str | None) -> list[str]:
    """Fallback step 2's stored list for a top-level category, most popular first."""
    if not job_run_id or not category_id:
        return []
    cursor = ml_db(settings)[COLLECTION].find(
        {"job_run_id": job_run_id, "category_id": str(category_id), "list": CATEGORY_POPULAR},
        {"_id": 0, "product_id": 1, "rank": 1},
    ).sort("rank", ASCENDING).batch_size(_READ_BATCH)
    return [row["product_id"] async for row in cursor]
