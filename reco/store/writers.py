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
from pymongo.errors import BulkWriteError, DuplicateKeyError
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


async def ensure_engine_collections(settings: Settings) -> list[str]:
    """Create every engine collection that does not exist yet. ENG-01. Idempotent.

    Also creates the ml_config_changes indexes (ENG-02) and the ml_events indexes, which the build list states outright
    (ENG-04, DS-017 section 7): unique on event_id, and indexed on user and time
    and on request_id. No expiry index: ml_events keeps at least 365 days (X-08),
    and no expiry is added unless Allen and Aravinth agree it in writing.

    The other collections get their indexes with the item that first writes them.

    Returns the names created by this call.
    """
    database = ml_db(settings)
    existing = set(await database.list_collection_names())

    created: list[str] = []
    for name in ENGINE_COLLECTIONS:
        _collection(database, name)  # the ml_ guard, before anything is created
        if name not in existing:
            await database.create_collection(name)
            created.append(name)

    events = _collection(database, "ml_events")
    await events.create_index([("event_id", 1)], unique=True, name="uniq_event_id")
    await events.create_index([("user_id", 1), ("server_ts", -1)], name="user_time")
    await events.create_index([("request_id", 1)], name="request_id")

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


async def insert_events(settings: Settings, documents: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Store events in ml_events. ENG-04 items 4-5.

    The unique index on event_id (ENG-01) is the de-duplication: an event whose
    event_id is already stored -- a retry, or a repeat within the same batch --
    is refused by the database, not overwritten. Returns (stored event_ids,
    duplicate event_ids).
    """
    if not documents:
        return [], []
    events = _collection(ml_db(settings), "ml_events")
    duplicates: set[int] = set()
    try:
        await events.insert_many([dict(d) for d in documents], ordered=False)
    except BulkWriteError as exc:
        for error in exc.details.get("writeErrors", []):
            if error.get("code") == 11000:
                duplicates.add(error["index"])
            else:
                raise
    stored = [d["event_id"] for i, d in enumerate(documents) if i not in duplicates]
    duplicate = [d["event_id"] for i, d in enumerate(documents) if i in duplicates]
    return stored, duplicate


# --- ENG-04 item 7: reconciliation results and the switch date ------------------------


async def read_events(settings: Settings, event_name: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """ml_events rows of one name with server_ts in [start, end)."""
    events = ml_db(settings)["ml_events"]
    return await events.find(
        {"event_name": event_name, "server_ts": {"$gte": start, "$lt": end}}
    ).to_list(None)


async def record_reconciliation(settings: Settings, result: dict[str, Any]) -> None:
    """One document per day in ml_measurements (measure 'event_reconciliation').

    Re-running a day replaces its result, so the latest run of a day is the one
    that counts.
    """
    measurements = _collection(ml_db(settings), "ml_measurements")
    await measurements.replace_one(
        {"measure": "event_reconciliation", "day": result["day"]},
        {"measure": "event_reconciliation", **result},
        upsert=True,
    )


async def read_reconciliations(settings: Settings, days: list[str]) -> dict[str, dict[str, Any]]:
    measurements = ml_db(settings)["ml_measurements"]
    found = measurements.find({"measure": "event_reconciliation", "day": {"$in": days}})
    return {doc["day"]: doc async for doc in found}


async def record_switch_date(settings: Settings, switch_date: str, evidence: list[str]) -> bool:
    """Record the ENG-03 switch date once. A date already recorded is never moved.

    Returns True if this call recorded it.
    """
    measurements = _collection(ml_db(settings), "ml_measurements")
    result = await measurements.update_one(
        {"measure": "event_source_switch"},
        {"$setOnInsert": {"measure": "event_source_switch", "switch_date": switch_date,
                          "evidence_days": evidence, "recorded_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return result.upserted_id is not None


async def read_switch_date(settings: Settings) -> str | None:
    """The recorded switch date (YYYY-MM-DD), or None while there is none yet."""
    doc = await ml_db(settings)["ml_measurements"].find_one({"measure": "event_source_switch"})
    return doc["switch_date"] if doc else None
