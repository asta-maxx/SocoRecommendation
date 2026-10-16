"""The post index in ml_item_state: what the candidate sources read. ENG-12 (ENG-27 adds the rest).

    await write_post_index(settings, rows)          one batch (rows carry job_run_id)
    await read_by_categories(settings, cats, since, limit)        source 1 / 3 pool
    await read_by_authors(settings, authors, since, limit)        source 2
    await read_most_viewed(settings, since, limit, categories)    sources 3 and 4

One row per post created in the last 30 days (retrieval.post_age_days), kind
"post": post_id, author_id, categories (one of the 23), created_at, is_repost,
qualified_views_7d. Written whole as an ENG-07 batch (job "post_index", method
"post_index"); a request reads only the batch marked current. ENG-27 keeps the
same collection current for eligibility (accounts, products, and the post fields
the ENG-08 rules need).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING

from reco.config import Settings
from reco.store.connection import ml_db
from reco.store.writers import _collection, current_job_run_id

JOB = "post_index"
METHOD = "post_index"
_FIELDS = {"_id": 0, "post_id": 1, "author_id": 1, "categories": 1, "created_at": 1, "qualified_views_7d": 1}


async def ensure_post_index_indexes(settings: Settings) -> None:
    items = _collection(ml_db(settings), "ml_item_state")
    await items.create_index([("job_run_id", ASCENDING), ("categories", ASCENDING), ("created_at", DESCENDING)],
                             name="post_categories")
    await items.create_index([("job_run_id", ASCENDING), ("author_id", ASCENDING), ("created_at", DESCENDING)],
                             name="post_author")
    await items.create_index([("job_run_id", ASCENDING), ("qualified_views_7d", DESCENDING), ("created_at", DESCENDING)],
                             name="post_views")


async def write_post_index(settings: Settings, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    result = await _collection(ml_db(settings), "ml_item_state").insert_many(rows)
    return len(result.inserted_ids)


async def current_batch(settings: Settings) -> str | None:
    return await current_job_run_id(settings, JOB, METHOD)


async def read_by_categories(settings: Settings, batch: str, categories: list[str], since: datetime,
                             limit: int) -> list[dict[str, Any]]:
    """Posts in any of `categories`, newest first."""
    cursor = ml_db(settings)["ml_item_state"].find(
        {"job_run_id": batch, "categories": {"$in": categories}, "created_at": {"$gte": since}}, _FIELDS
    ).sort([("created_at", DESCENDING), ("post_id", DESCENDING)]).limit(limit)
    return await cursor.to_list(None)


async def read_by_authors(settings: Settings, batch: str, authors: list[str], since: datetime,
                          limit: int) -> list[dict[str, Any]]:
    """Posts by any of `authors`, newest first."""
    cursor = ml_db(settings)["ml_item_state"].find(
        {"job_run_id": batch, "author_id": {"$in": authors}, "created_at": {"$gte": since}}, _FIELDS
    ).sort([("created_at", DESCENDING), ("post_id", DESCENDING)]).limit(limit)
    return await cursor.to_list(None)


async def read_most_viewed(settings: Settings, batch: str, since: datetime, limit: int,
                           categories: list[str] | None = None) -> list[dict[str, Any]]:
    """Posts with qualified views in the last 7 days, most viewed first; ties newest first
    (Kala, 16 Oct). Limited to `categories` when given (trending)."""
    query: dict[str, Any] = {"job_run_id": batch, "qualified_views_7d": {"$gt": 0}, "created_at": {"$gte": since}}
    if categories is not None:
        query["categories"] = {"$in": categories}
    cursor = ml_db(settings)["ml_item_state"].find(query, _FIELDS).sort(
        [("qualified_views_7d", DESCENDING), ("created_at", DESCENDING), ("post_id", DESCENDING)]).limit(limit)
    return await cursor.to_list(None)
