"""The only module in this service that writes. ST5, ST6, ST7, ST8.

Everything written by the M1 engine goes into the ml_ namespace. Nothing else is
touched -- not for a migration, not for a fixture, not for the demonstration.

The rule is enforced by _collection() below, which is the single place a writable
collection handle can be obtained. There is no other path to one, so the rule is
something a test can catch rather than something a reviewer has to notice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from pymongo import DESCENDING, UpdateOne
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from reco.config import ENGINE_COLLECTIONS, Settings
from reco.store.connection import ml_db
from reco.store.scores import InterestScore, Method, ScoreBatch

logger = logging.getLogger(__name__)

ML_PREFIX = "ml_"


class NamespaceViolation(RuntimeError):
    """Raised when something attempts to write outside the ml_ namespace.

    Deliberately not a ValueError: this is a contract breach, not bad input, and
    it should never be caught by a broad handler around a write.
    """


def _collection(database: AsyncDatabase, name: str) -> AsyncCollection:
    """The only way to get a writable collection handle.

    Refuses anything not prefixed ml_. This is the fourth of the five things not
    to do, and the only one a test can catch -- so it is an assertion in code, not
    a note in a comment.
    """
    if not isinstance(name, str) or not name.startswith(ML_PREFIX):
        raise NamespaceViolation(
            f"refusing to write to {name!r}: this service writes only to "
            f"collections prefixed {ML_PREFIX!r}. Scores never go into an "
            f"application collection, not even for a demonstration."
        )
    return database[name]


async def _ensure_index(collection: AsyncCollection, keys: list[tuple[str, int]], name: str, **options) -> None:
    """Create an index; if one with the same name exists with a different definition, replace it.

    Engine collections built to an earlier design keep their old index names
    (e.g. user_time on server_ts in the 22 Sep design), and MongoDB refuses a
    different index under an existing name.
    """
    existing = {index["name"]: index async for index in await collection.list_indexes()}
    current = existing.get(name)
    if current is not None:
        same_keys = list(current["key"].items()) == keys
        same_options = all(current.get(k) == v for k, v in options.items())
        if same_keys and same_options:
            return
        await collection.drop_index(name)
    await collection.create_index(keys, name=name, **options)


async def ensure_engine_collections(settings: Settings) -> list[str]:
    """Create every engine collection that does not exist yet, with its indexes. Idempotent.

    ENG-01: the sixteen ml_ collections. Indexes:

      ml_events, ml_orders  keyed on the platform _id (the document _id), as the
                            engine sync requires (ENG-04, DS-017 section 7);
                            retention: an expiry index on created_at, the ORIGINAL
                            event time, of at least 365 days (SD-29, X-08). The
                            platform's 90-day expiry never touches these copies,
                            and an update never moves created_at.
      ml_events             user and time; request_id; E code and time.
      ml_orders             buyer and time; checkout_id.
      ml_config_changes     unique config_version (ENG-02).

    The 22 Sep design's unique index on event_id is dropped if present: copies
    are keyed on the platform _id, and event_id is an opaque platform value.
    ml_sync_state is keyed by source collection. ml_item_state and ml_deletions
    get their indexes with ENG-27 and ENG-28.

    Returns the names created by this call.
    """
    from reco.config import live

    database = ml_db(settings)
    existing = set(await database.list_collection_names())

    created: list[str] = []
    for name in ENGINE_COLLECTIONS:
        _collection(database, name)  # the ml_ guard, before anything is created
        if name not in existing:
            await database.create_collection(name)
            created.append(name)

    retention = int(live.current().events.retention_days) * 24 * 3600

    events = _collection(database, "ml_events")
    if "uniq_event_id" in {index["name"] async for index in await events.list_indexes()}:
        await events.drop_index("uniq_event_id")
    await _ensure_index(events, [("user_id", 1), ("created_at", -1)], "user_time")
    await _ensure_index(events, [("request_id", 1)], "request_id")
    await _ensure_index(events, [("event_code", 1), ("created_at", -1)], "code_time")
    await _ensure_index(events, [("created_at", 1)], "retention", expireAfterSeconds=retention)

    orders = _collection(database, "ml_orders")
    await _ensure_index(orders, [("buyer_id", 1), ("created_at", -1)], "buyer_time")
    await _ensure_index(orders, [("checkout_id", 1)], "checkout_id")
    await _ensure_index(orders, [("created_at", 1)], "retention", expireAfterSeconds=retention)

    # ENG-02 item 4: one record per settings version. Unique, so when the API and
    # a job both see the same new version, only one records it.
    changes = _collection(database, "ml_config_changes")
    await changes.create_index(
        [("config_version", 1)], unique=True, name="uniq_config_version"
    )
    await changes.create_index([("changed_at", -1)], name="changed_at")

    logger.info(
        "Engine collections ensured in %s (%s): %d created",
        settings.ml_mongo_db,
        settings.engine_env,
        len(created),
    )
    return created


async def ensure_indexes(settings: Settings) -> None:
    """Create the score store's indexes. ST4. Idempotent.

    Two indexes:

      unique (user_id, category, method, model_version)
          The identity of a score. Method and model_version are part of it so
          that both methods, and successive generations of one method, coexist as
          distinct documents instead of overwriting one another.

      (user_id, method, computed_at desc)
          The read path filters by user and method and then needs computed_at to
          answer the P-08 staleness question on rung 4 of the ladder.
    """
    scores = _collection(ml_db(settings), settings.scores_collection)

    await scores.create_index(
        [("user_id", 1), ("category", 1), ("method", 1), ("model_version", 1)],
        unique=True,
        name="uniq_user_category_method_version",
    )
    await scores.create_index(
        [("user_id", 1), ("method", 1), ("computed_at", -1)],
        name="user_method_recency",
    )
    logger.info("Indexes ensured on %s", settings.scores_collection)


async def upsert_score(settings: Settings, score: InterestScore) -> None:
    """Write one score, keyed on (user_id, category, method, model_version). ST7.

    The score has already been validated by its own model, so a document missing
    a metadata field cannot reach this function -- it fails at construction.
    """
    scores = _collection(ml_db(settings), settings.scores_collection)
    await scores.update_one(
        score.key(),
        {"$set": score.to_document()},
        upsert=True,
    )


async def upsert_user_scores(
    settings: Settings,
    user_id: str,
    scores: Iterable[InterestScore],
) -> int:
    """Write a whole user's category map in one call. ST8.

    The refresh path writes per user, not per category: a user with 23 categories
    is one round trip, not 23. Validated as a ScoreBatch first, which checks the
    things no single document can -- one user, one method, one window, no repeated
    category, and shares summing to 1.

    Returns the number of documents written.
    """
    batch = ScoreBatch(user_id=user_id, scores=list(scores))

    collection = _collection(ml_db(settings), settings.scores_collection)
    operations = [
        UpdateOne(score.key(), {"$set": score.to_document()}, upsert=True)
        for score in batch.scores
    ]
    result = await collection.bulk_write(operations, ordered=False)
    written = result.upserted_count + result.modified_count

    logger.debug(
        "Wrote %d scores for user %s (%s upserted, %s modified)",
        len(operations),
        user_id,
        result.upserted_count,
        result.modified_count,
    )
    return written


async def remove_scores_older_than(
    settings: Settings,
    method: Method | str,
    model_version: str,
    computed_at: datetime,
) -> int:
    """Delete rows this run did not rewrite. One sweep, at the end of a refresh.

    An upsert leaves behind any category a user has stopped scoring in, and a
    stale row is worse than a missing one: the surviving rows were normalised
    over a new total, so the stale row's share was computed against a denominator
    that no longer exists and the set stops summing to 1.

    It happens whenever a category leaves a profile -- an event ageing past
    Method B's cut-off, or a category that used to resolve and now does not.

    Keyed on `computed_at` rather than on a per-user list of categories: every row
    written by one refresh carries that run's instant, so anything older is by
    definition from a previous run. One query instead of one per user, and it
    also clears users who stopped scoring altogether and so were never written.
    """
    collection = _collection(ml_db(settings), settings.scores_collection)
    result = await collection.delete_many(
        {
            "method": str(method),
            "model_version": model_version,
            "computed_at": {"$lt": computed_at},
        }
    )
    if result.deleted_count:
        logger.info(
            "Removed %d stale score rows under %s v%s",
            result.deleted_count,
            method,
            model_version,
        )
    return result.deleted_count


async def replace_collection(
    settings: Settings,
    name: str,
    documents: list[dict],
) -> int:
    """Drop an ml_ collection and refill it. Used to load generated fixtures.

    Goes through the same guard as every other write, so this cannot be pointed
    at an application collection even by accident -- which matters, because it
    drops before it writes.

    Not part of the scoring path. It exists because the generated dataset arrives
    as JSON files and the engine reads collections: without a loader the demo
    profile names collections that hold nothing.
    """
    collection = _collection(ml_db(settings), name)
    await collection.drop()
    if not documents:
        return 0
    result = await collection.insert_many(documents)
    logger.info("Loaded %d documents into %s", len(result.inserted_ids), name)
    return len(result.inserted_ids)


async def read_user_scores(
    settings: Settings,
    user_id: str,
    method: Method | str,
    model_version: str | None = None,
) -> list[InterestScore]:
    """Read back one user's scores for a given method. ST9.

    What the display and the data checks both consume. Lives here rather than in
    readers.py because readers.py is the module that reads SOCO application
    collections under the read-only credential; this reads the ml_ namespace.

    model_version defaults to the running configuration's, so a caller does not
    accidentally mix two generations of scores in one response.
    """
    collection = ml_db(settings)[settings.scores_collection]
    query = {
        "user_id": user_id,
        "method": str(method),
        "model_version": model_version or settings.model_version,
    }
    cursor = collection.find(query).sort("share", -1)
    return [InterestScore.from_document(document) async for document in cursor]


async def delete_user_scores(
    settings: Settings,
    user_id: str,
    method: Method | str,
    model_version: str | None = None,
) -> int:
    """Remove one user's scores for a method. Used by tests and by a full
    recomputation that needs to drop categories a user no longer scores in.

    Goes through _collection(), so it is bound by the same namespace guard.
    """
    collection = _collection(ml_db(settings), settings.scores_collection)
    result = await collection.delete_many(
        {
            "user_id": user_id,
            "method": str(method),
            "model_version": model_version or settings.model_version,
        }
    )
    return result.deleted_count


async def record_config_change(settings: Settings, record: dict[str, Any]) -> bool:
    """Write one settings change to ml_config_changes. ENG-02 item 4.

    Returns False when this config_version is already recorded -- another process
    got there first, which is expected, not a fault.
    """
    changes = _collection(ml_db(settings), "ml_config_changes")
    try:
        await changes.insert_one(dict(record))
    except DuplicateKeyError:
        return False
    return True


async def read_latest_config_change(settings: Settings) -> dict[str, Any] | None:
    """The most recent settings change, with its full snapshot, or None."""
    changes = ml_db(settings)["ml_config_changes"]
    return await changes.find_one({}, sort=[("changed_at", DESCENDING)])


# --- the engine sync (ENG-04) ------------------------------------------------------------


async def upsert_copies(settings: Settings, target: str, copies: list[dict[str, Any]], copied_at: datetime) -> int:
    """Write engine copies keyed on _id: a row already held is updated, never skipped
    (ENG-04 item 3). first_copied_at is set once; created_at, the original event
    time, comes from the platform row and never moves (SD-29)."""
    if not copies:
        return 0
    collection = _collection(ml_db(settings), target)
    operations = [
        UpdateOne(
            {"_id": copy["_id"]},
            {"$set": {**{k: v for k, v in copy.items() if k != "_id"}, "last_copied_at": copied_at},
             "$setOnInsert": {"first_copied_at": copied_at}},
            upsert=True,
        )
        for copy in copies
    ]
    await collection.bulk_write(operations, ordered=True)
    return len(operations)


async def read_copies(settings: Settings, target: str, ids: list[Any]) -> dict[Any, dict[str, Any]]:
    collection = ml_db(settings)[target]
    return {doc["_id"]: doc async for doc in collection.find({"_id": {"$in": list(ids)}})}


async def read_copies_touched(settings: Settings, target: str, source: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Copies of `source` rows whose original time or updated_at falls in [start, end)."""
    window = {"$gte": start, "$lt": end}
    query = {"source": source, "$or": [{"created_at": window}, {"updated_at": window}]}
    return await ml_db(settings)[target].find(query).to_list(None)


async def read_sync_state(settings: Settings, source: str) -> dict[str, Any]:
    return await ml_db(settings)["ml_sync_state"].find_one({"_id": source}) or {"_id": source}


async def write_sync_state(settings: Settings, source: str, fields: dict[str, Any]) -> None:
    """ml_sync_state: checkpoint and lag per source collection (ENG-04 item 4)."""
    state = _collection(ml_db(settings), "ml_sync_state")
    await state.update_one({"_id": source}, {"$set": fields}, upsert=True)


async def read_all_sync_state(settings: Settings) -> list[dict[str, Any]]:
    return await ml_db(settings)["ml_sync_state"].find({}).to_list(None)


async def record_sync_reconciliation(settings: Settings, result: dict[str, Any]) -> None:
    """One document per source collection per day in ml_measurements."""
    measurements = _collection(ml_db(settings), "ml_measurements")
    key = {"measure": "sync_reconciliation", "source": result["source"], "day": result["day"]}
    await measurements.replace_one(key, {**key, **result}, upsert=True)
