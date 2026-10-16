"""ml_user_candidates: M2 method two's stored lists. ENG-14.

    await read_engaged_rows(settings)            the postevents copies the profiles use
    await write_user_candidates(settings, rows)  one batch's rows (each carries job_run_id)
    await read_user_candidates(settings, uid)    the current batch's list, by rank
    await ensure_candidate_indexes(settings)     called from writers.ensure_indexes

One row per (user, post):

    {user_id, post_id, score (cosine 0..1), rank (1 = most similar),
     method: "similar_posts", slot: "retrieval", job_run_id, model_version,
     config_version, computed_at, data_window: {"from", "to"}}

Written as an ENG-07 batch (reco.jobs.batches.run_batch), so a request reads only
the batch marked current, never a half-written one. Writes go through
writers._collection, the ml_ namespace guard.
"""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING

from reco.config import Settings
from reco.store.connection import ml_db
from reco.store.writers import _collection, _ensure_index, current_job_run_id

COLLECTION = "ml_user_candidates"
JOB = "similar_posts"
METHOD = "similar_posts"
SLOT = "retrieval"

#: The postevents types a profile can use; the maths (reco.ranking.similar) decides
#: which rows count. Feedback and impressions are never read.
ENGAGED_EVENT_TYPES = ("view", "click", "product_click", "like", "save", "comment", "share", "add_to_cart")

_ENGAGED_FIELDS = {f: 1 for f in ("user_id", "actor", "event_type", "post_id", "dwell_ms", "undone_at", "undo_of",
                                  "is_self", "created_at")}

_WRITE_CHUNK = 5000

#: A stored list is at most retrieval.similar_top_stored (200, fixed for Wave 1A) rows.
#: MongoDB's first batch is 101 documents by default, which would make a 200-row
#: list two round trips; this keeps the whole list in the first reply.
_READ_BATCH = 1000


async def ensure_candidate_indexes(settings: Settings) -> None:
    """(job_run_id, user_id, rank): a request reads one user's list of the current
    batch in rank order from the index alone. (method, job_run_id): removing a
    superseded or failed batch (writers.delete_batches_except)."""
    collection = _collection(ml_db(settings), COLLECTION)
    await _ensure_index(collection, [("job_run_id", 1), ("user_id", 1), ("rank", 1)], "run_user_rank")
    await _ensure_index(collection, [("method", 1), ("job_run_id", 1)], "method_run")


async def read_engaged_rows(settings: Settings) -> list[dict[str, Any]]:
    """The engine's copies of postevents rows of a type a profile can use, with a
    post id, not undone and not on the user's own post (the maths checks again)."""
    cursor = ml_db(settings)["ml_events"].find(
        {"kind": "postevent", "event_type": {"$in": list(ENGAGED_EVENT_TYPES)}, "post_id": {"$ne": None},
         "undone_at": None, "undo_of": None, "is_self": {"$ne": True}},
        _ENGAGED_FIELDS,
    )
    return await cursor.to_list(None)


async def write_user_candidates(settings: Settings, rows: list[dict[str, Any]]) -> int:
    """Insert one batch's rows. Each already carries its job_run_id."""
    collection = _collection(ml_db(settings), COLLECTION)
    written = 0
    for start in range(0, len(rows), _WRITE_CHUNK):
        result = await collection.insert_many(rows[start:start + _WRITE_CHUNK], ordered=False)
        written += len(result.inserted_ids)
    return written


async def read_user_candidates(settings: Settings, user_id: str) -> list[dict[str, Any]]:
    """One user's stored method-two list from the CURRENT batch only, by rank:
    [{"post_id", "score", "rank"}]. Empty when the user has no list or no batch is
    current yet. Requests only read; the list is computed nightly (ENG-14)."""
    job_run_id = await current_job_run_id(settings, JOB, METHOD)
    if job_run_id is None or not user_id:
        return []
    cursor = ml_db(settings)[COLLECTION].find(
        {"job_run_id": job_run_id, "user_id": str(user_id)},
        {"_id": 0, "post_id": 1, "score": 1, "rank": 1},
    ).sort("rank", ASCENDING).batch_size(_READ_BATCH)
    return await cursor.to_list(None)
