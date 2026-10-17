"""ml_promoter_scores and its monthly copy: M8's stored scores. ENG-16.

    await read_promoter_event_rows(settings, since)     postevents copies M8's components use
    await read_order_rows(settings)                     every order copy, with M8's fields
    await read_confirmed_restrictions(settings, now)    {account_id: level} of confirmed fraud cases in force
    await write_promoter_scores(settings, rows)         one batch's rows (each carries job_run_id)
    await read_promoter_score(settings, pid, method)    the current batch's row, or None
    await copy_monthly(settings, month, method)         the current batch into ml_promoter_scores_monthly

One row per (promoter, method):

    {promoter_id, kind (user / business), method (shrinkage / cohort_percentile),
     slot "promoter_score", score (0..1), confidence (0..1), flags [...],
     main_category, follower_band, cohort_group, components {raw}, percentiles {...},
     weights {in use}, own, category_average, qualified_views_30d,
     job_run_id, model_version, config_version, computed_at, data_window}

Each method is an ENG-07 batch (reco.jobs.batches.run_batch), so a request reads
only the batch marked current. Writes go through writers._collection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, UpdateOne

from reco.config import Settings
from reco.store.connection import ml_db
from reco.store.writers import _collection, _ensure_index, current_job_run_id

COLLECTION = "ml_promoter_scores"
MONTHLY = "ml_promoter_scores_monthly"
JOB = "promoter"
SLOT = "promoter_score"
_WRITE_CHUNK = 1000

#: The postevents types M8 reads: qualified views (reach, the denominators) and the
#: four actions of content quality. Undone actions and undo rows are left out here.
EVENT_TYPES = ("view", "like", "save", "share", "comment")
_EVENT_FIELDS = {f: 1 for f in ("user_id", "actor", "event_type", "post_id", "dwell_ms", "is_self", "created_at")}
_ORDER_FIELDS = {f: 1 for f in ("order_id", "buyer_id", "buyer_actor", "post_id", "promoter_id", "product_id",
                                "value", "status", "is_returned", "delivered_at", "history_conflict", "created_at")}

#: ENG-21's confirmed case, as M8 reads it (Fraud Policy 6.1: level 3 restricted,
#: 4 suspended, 5 removed). A case is in force from its outcome until its end, if any.
RESTRICTED_LEVEL = 3


async def ensure_promoter_indexes(settings: Settings) -> None:
    db = ml_db(settings)
    await _ensure_index(_collection(db, COLLECTION), [("job_run_id", ASCENDING), ("promoter_id", ASCENDING)],
                        name="run_promoter")
    await _ensure_index(_collection(db, COLLECTION), [("method", ASCENDING), ("job_run_id", ASCENDING)],
                        name="method_run")
    await _ensure_index(_collection(db, MONTHLY), [("month", ASCENDING), ("method", ASCENDING), ("promoter_id", ASCENDING)],
                        name="month_method_promoter", unique=True)


async def read_promoter_event_rows(settings: Settings, since: datetime) -> list[dict[str, Any]]:
    cursor = ml_db(settings)["ml_events"].find(
        {"kind": "postevent", "event_type": {"$in": list(EVENT_TYPES)}, "post_id": {"$ne": None},
         "created_at": {"$gte": since}, "undone_at": None, "undo_of": None},
        _EVENT_FIELDS,
    )
    return await cursor.to_list(None)


async def read_order_rows(settings: Settings) -> list[dict[str, Any]]:
    return await ml_db(settings)["ml_orders"].find({}, _ORDER_FIELDS).to_list(None)


async def read_confirmed_restrictions(settings: Settings, now: datetime) -> dict[str, int]:
    """Accounts with a confirmed fraud case at level 3 or above in force now: {account_id: level}.
    The highest level wins. Written by ENG-21; empty until it exists."""
    cursor = ml_db(settings)["ml_fraud_cases"].find(
        {"outcome": "confirmed", "level_recorded": {"$gte": RESTRICTED_LEVEL},
         "$or": [{"in_force_until": None}, {"in_force_until": {"$exists": False}}, {"in_force_until": {"$gt": now}}]},
        {"account_id": 1, "level_recorded": 1, "decided_at": 1},
    )
    levels: dict[str, int] = {}
    async for case in cursor:
        decided = case.get("decided_at")
        if decided is not None and decided.tzinfo is None:
            decided = decided.replace(tzinfo=timezone.utc)
        if decided is not None and decided > now:
            continue
        account = str(case.get("account_id") or "")
        if account:
            levels[account] = max(levels.get(account, 0), int(case["level_recorded"]))
    return levels


async def write_promoter_scores(settings: Settings, rows: list[dict[str, Any]]) -> int:
    collection = _collection(ml_db(settings), COLLECTION)
    written = 0
    for start in range(0, len(rows), _WRITE_CHUNK):
        result = await collection.insert_many(rows[start:start + _WRITE_CHUNK], ordered=False)
        written += len(result.inserted_ids)
    return written


async def read_promoter_score(settings: Settings, promoter_id: str, method: str) -> dict[str, Any] | None:
    """The promoter's row in the current batch of `method`, or None."""
    batch = await current_job_run_id(settings, JOB, method)
    if not batch:
        return None
    return await ml_db(settings)[COLLECTION].find_one({"job_run_id": batch, "promoter_id": str(promoter_id)},
                                                      {"_id": 0})


async def copy_monthly(settings: Settings, month: str, method: str) -> int:
    """ENG-16: copy the current batch of `method` into ml_promoter_scores_monthly
    under `month` (YYYY-MM). Run on the 1st; running it again the same month
    replaces that month's rows, so a re-run never doubles them."""
    batch = await current_job_run_id(settings, JOB, method)
    if not batch:
        return 0
    rows = await ml_db(settings)[COLLECTION].find({"job_run_id": batch}, {"_id": 0}).to_list(None)
    if not rows:
        return 0
    ops = [UpdateOne({"month": month, "method": method, "promoter_id": r["promoter_id"]},
                     {"$set": {**r, "month": month}}, upsert=True) for r in rows]
    monthly = _collection(ml_db(settings), MONTHLY)
    await monthly.delete_many({"month": month, "method": method,
                               "promoter_id": {"$nin": [r["promoter_id"] for r in rows]}})
    await monthly.bulk_write(ops, ordered=False)
    return len(rows)
