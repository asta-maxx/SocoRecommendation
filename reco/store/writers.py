"""The only module in this service that writes. ST5, ST6, ST7, ST8.

Everything written by the M1 engine goes into the ml_ namespace. Nothing else is
touched -- not for a migration, not for a fixture, not for the demonstration.

The rule is enforced by _collection() below, which is the single place a writable
collection handle can be obtained. There is no other path to one, so the rule is
something a test can catch rather than something a reviewer has to notice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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

    ENG-01: the sixteen ml_ collections, and ml_return_requests (ENG-30 point 7). Indexes:

      ml_events, ml_orders  keyed on the platform _id (the document _id), as the
                            engine sync requires (ENG-04, DS-017 section 7);
                            retention: an expiry index on created_at, the ORIGINAL
                            event time, of at least 365 days (SD-29, X-08). The
                            platform's 90-day expiry never touches these copies,
                            and an update never moves created_at.
      ml_events             user and time; request_id; E code and time.
      ml_orders             buyer and time; checkout_id.
      ml_config_changes     unique per transition: previous, new, the entry it follows (ENG-02, F5).

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
    returns = _collection(database, "ml_return_requests")
    await _ensure_index(returns, [("order_id", 1), ("is_active", 1)], "order_open")
    await _ensure_index(returns, [("created_at", 1)], "retention", expireAfterSeconds=retention)

    changes = _collection(database, "ml_config_changes")
    # Kala F5 (16 Oct): one entry per transition, so a rollback to a version used
    # before is recorded too. The old one-entry-per-version index is replaced.
    if "uniq_config_version" in await changes.index_information():
        await changes.drop_index("uniq_config_version")
    await changes.create_index(
        [("previous_version", 1), ("config_version", 1), ("follows", 1)], unique=True, name="uniq_transition"
    )
    await changes.create_index([("changed_at", -1)], name="changed_at")

    # ENG-07: one record per job run; the current batch of each job and method
    # is the run marked is_current.
    runs = _collection(database, "ml_job_runs")
    await _ensure_index(runs, [("job", 1), ("method", 1), ("is_current", 1), ("finished_at", -1)], "job_current")
    await _ensure_index(runs, [("started_at", -1)], "started_at")

    logger.info(
        "Engine collections ensured in %s (%s): %d created",
        settings.ml_mongo_db,
        settings.engine_env,
        len(created),
    )
    return created


async def ensure_indexes(settings: Settings) -> None:
    """Create the score store's indexes. ST4. Idempotent.

    Three indexes:

      unique (user_id, category, method, model_version, job_run_id)
          The identity of a score. Method and model_version are part of it so
          that both methods, and successive generations of one method, coexist as
          distinct documents instead of overwriting one another; job_run_id so a
          new batch is written beside the current one (ENG-07).

      (method, job_run_id)
          Clearing a superseded or failed batch.

      (user_id, method, computed_at desc)
          The read path filters by user and method and then needs computed_at to
          answer the P-08 staleness question on rung 4 of the ladder.
    """
    scores = _collection(ml_db(settings), settings.scores_collection)

    # ENG-07: a nightly job writes a whole new batch beside the current one, so
    # the batch (job_run_id) is part of a score's identity. The pre-ENG-07 index
    # without it is replaced.
    if "uniq_user_category_method_version" in {i["name"] async for i in await scores.list_indexes()}:
        await scores.drop_index("uniq_user_category_method_version")
    await _ensure_index(
        scores,
        [("user_id", 1), ("category", 1), ("method", 1), ("model_version", 1), ("job_run_id", 1)],
        "uniq_user_category_method_version_run",
        unique=True,
    )
    await _ensure_index(scores, [("method", 1), ("job_run_id", 1)], "method_run")
    await scores.create_index(
        [("user_id", 1), ("method", 1), ("computed_at", -1)],
        name="user_method_recency",
    )
    logger.info("Indexes ensured on %s", settings.scores_collection)

    # ENG-14: method two's stored lists, read per user from the current batch.
    from reco.store.candidates import ensure_candidate_indexes

    await ensure_candidate_indexes(settings)

    # ENG-17: M5's stored lists, read per viewed product from the current batch.
    from reco.store.product_scores import ensure_product_score_indexes

    await ensure_product_score_indexes(settings)


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
        # ENG-07: only the batch marked current -- never a half-written one.
        # With no current batch yet, only rows written outside a job run.
        "job_run_id": await current_job_run_id(settings, "interest", str(method)),
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

    Returns False when this transition is already recorded (same versions, after
    the same entry) -- another process got there first, which is expected.
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


# --- nightly batches (ENG-07) -----------------------------------------------------------


async def record_job_run(settings: Settings, record: dict[str, Any]) -> None:
    """A new run in ml_job_runs; its _id is the job_run_id."""
    await _collection(ml_db(settings), "ml_job_runs").insert_one(record)


async def update_job_run(settings: Settings, job_run_id: str, fields: dict[str, Any]) -> None:
    await _collection(ml_db(settings), "ml_job_runs").update_one({"_id": job_run_id}, {"$set": fields})


async def abandon_running(settings: Settings, job: str, method: str | None, now: datetime) -> int:
    """Runs of this job still marked running were stopped without finishing (killed):
    record them as failed. Called as the next run starts."""
    result = await _collection(ml_db(settings), "ml_job_runs").update_many(
        {"job": job, "method": method, "outcome": "running"},
        {"$set": {"outcome": "failed", "error": "abandoned: stopped before it finished", "finished_at": now}},
    )
    return result.modified_count


async def current_job_run_id(settings: Settings, job: str, method: str | None) -> str | None:
    """The batch requests read for this job and method, or None if none is current yet."""
    run = await ml_db(settings)["ml_job_runs"].find_one(
        {"job": job, "method": method, "is_current": True}, sort=[("finished_at", DESCENDING)]
    )
    return run["_id"] if run else None


async def mark_current(settings: Settings, job: str, method: str | None, job_run_id: str) -> str | None:
    """Make a finished batch the one requests read. Returns the batch it replaced.

    The new batch is marked first and the old one unmarked after, so at every
    moment some complete batch is current (a reader takes the latest finished)."""
    runs = _collection(ml_db(settings), "ml_job_runs")
    previous = await current_job_run_id(settings, job, method)
    await runs.update_one({"_id": job_run_id}, {"$set": {"is_current": True}})
    await runs.update_many({"job": job, "method": method, "_id": {"$ne": job_run_id}, "is_current": True},
                           {"$set": {"is_current": False}})
    return previous


async def delete_batches_except(
    settings: Settings, collection: str, method: str | None, keep: list[str | None], only: str | None = None
) -> int:
    """Remove a method's score rows from any batch not in `keep` (the current and the
    one it replaced, so a request already reading that one finishes on it), or,
    with `only`, the rows of that one batch (a failed run's partial rows)."""
    query: dict[str, Any] = {"method": method}
    query["job_run_id"] = only if only is not None else {"$nin": keep}
    result = await _collection(ml_db(settings), collection).delete_many(query)
    return result.deleted_count


async def read_job_runs(settings: Settings, limit: int = 20) -> list[dict[str, Any]]:
    return await ml_db(settings)["ml_job_runs"].find({}).sort("started_at", DESCENDING).limit(limit).to_list(None)


# --- served lists (ENG-06) ----------------------------------------------------------------


async def record_served_list(settings: Settings, record: dict[str, Any]) -> None:
    """The engine's own E1 (recommendation_request) record, in ml_events, keyed on its
    request_id. Written before the list is returned: no record, no list."""
    await _collection(ml_db(settings), "ml_events").insert_one(record)


async def read_served_list(settings: Settings, request_id: str) -> dict[str, Any] | None:
    return await ml_db(settings)["ml_events"].find_one({"_id": request_id, "event_code": "E1"})


async def read_served_item_ids(settings: Settings, user_id: str | None, surface: str, since: datetime) -> set[str]:
    """ENG-19 paging: every item served to this user on this surface since `since`,
    from the engine's own request records (E1)."""
    if not user_id:
        return set()
    cursor = ml_db(settings)["ml_events"].find(
        {"event_code": "E1", "user_id": user_id, "surface": surface, "server_ts": {"$gte": since}},
        {"served_items.item_id": 1})
    return {item["item_id"] async for row in cursor for item in row.get("served_items") or [] if item.get("item_id")}


async def record_measurement(settings: Settings, key: dict[str, Any], fields: dict[str, Any]) -> None:
    """One document per key in ml_measurements, replaced when the same key is measured again."""
    await _collection(ml_db(settings), "ml_measurements").replace_one(key, {**key, **fields}, upsert=True)


async def read_viewer_feedback(settings: Settings, user_id: str, since: datetime) -> list[dict[str, Any]]:
    """The viewer's content feedback (E13) in the engine's copy of postevents, leaving
    out undone rows (ENG-08): every mute_author (E-02 sets no time limit), and the
    other kinds since `since` (E-03's window)."""
    query = {"user_id": user_id, "event_type": "feedback", "undone_at": None,
             "$or": [{"feedback_type": "mute_author"}, {"created_at": {"$gte": since}}]}
    projection = {"feedback_type": 1, "target_id": 1, "target_type": 1, "post_id": 1, "product_id": 1,
                  "item_id": 1, "influencer_id": 1}
    return await ml_db(settings)["ml_events"].find(query, projection).to_list(None)


async def read_running_jobs(settings: Settings, started_before: datetime) -> list[dict[str, Any]]:
    """Job runs still marked running that started before `started_before`."""
    query = {"outcome": "running", "started_at": {"$lt": started_before}}
    return await ml_db(settings)["ml_job_runs"].find(query).to_list(None)


# --- the fallback ladder (ENG-09) ---------------------------------------------------------

#: postevents types that count as a qualified action besides a qualified view (ENG-10's
#: sources for M1: clicks, likes, saves, comments, shares and add-to-carts). Feedback
#: (not interested, hide) lowers a score rather than building one, so it isn't here.
QUALIFYING_EVENT_TYPES = ("click", "product_click", "like", "save", "comment", "share", "add_to_cart")

#: ml_measurements rows of the nightly platform popularity (ENG-09 rung 3).
POPULARITY_MEASURE = "category_popularity"
POPULARITY_METHOD = "platform_popularity"


async def qualified_action_rows(
    settings: Settings, user_id: str, since: datetime, view_ms: float, limit: int | None = None
) -> list[dict[str, Any]]:
    """ENG-09 rung 1, Kala's rules (16 Oct, 2a): the user's qualified actions since
    `since` from the engine's own copies, one row each ({"post_id"}), at most `limit`.

    postevents: a view with dwell_ms of at least `view_ms` (one per post), or one of
    QUALIFYING_EVENT_TYPES; never an undo row, an action later undone, or an action
    on the user's own post (is_self). Orders: one per order placed, unless its
    order_status is Cancelled, Rejected or Returned, or it has an open return request
    (ENG-30 points 6, 10). Seed posts are left out by the caller (they are known from
    the platform), and business follows are added by the caller. ENG-10 counts
    with the same rules (reco.slots.interest.copies), so the totals are equal.
    """
    pipeline: list[dict[str, Any]] = [
        {"$match": {
            "kind": "postevent", "user_id": user_id, "created_at": {"$gte": since},
            "undone_at": None, "undo_of": None, "is_self": {"$ne": True},
            "$or": [{"event_type": {"$in": list(QUALIFYING_EVENT_TYPES)}},
                    {"event_type": "view", "dwell_ms": {"$gte": view_ms}}],
        }},
        # A qualified view counts once per post; every other action counts once.
        {"$group": {"_id": {"$cond": [{"$and": [{"$eq": ["$event_type", "view"]}, {"$ne": [{"$ifNull": ["$post_id", None]}, None]}]},
                                      {"$concat": ["view:", "$post_id"]},
                                      {"$toString": "$_id"}]},
                    "post_id": {"$first": "$post_id"}}},
    ]
    if limit:
        pipeline.append({"$limit": limit})
    rows = [{"post_id": row.get("post_id")} async for row in await ml_db(settings)["ml_events"].aggregate(pipeline)]
    if limit and len(rows) >= limit:
        return rows
    # A user's orders in 90 days are few: read their state and test it as M1 does.
    from reco.config import live
    from reco.platform.records import status_is

    statuses = live.current().lists.order_status
    reversed_ = (statuses.cancelled, statuses.rejected, statuses.returned)
    orders = await ml_db(settings)["ml_orders"].find(
        {"buyer_id": user_id, "created_at": {"$gte": since}}, {"status": 1, "order_id": 1, "post_id": 1}
    ).to_list(None)
    ids = [str(o.get("order_id") or o["_id"]) for o in orders]
    open_ids = {r["order_id"] async for r in ml_db(settings)["ml_return_requests"].find(
        {"order_id": {"$in": ids}, "is_active": True}, {"order_id": 1})} if ids else set()
    for order_id, order in zip(ids, orders):
        if not any(status_is(order.get("status"), s) for s in reversed_) and order_id not in open_ids:
            rows.append({"post_id": order.get("post_id")})
    return rows[:limit] if limit else rows


async def read_qualified_views(settings: Settings, since: datetime, view_ms: float) -> list[dict[str, Any]]:
    """ENG-09 rung 3: every (viewer, post) pair with a qualified view since `since`, from
    the engine's copy of postevents. One row per pair, so a post viewed twice by one
    person counts once."""
    cursor = await ml_db(settings)["ml_events"].aggregate([
        {"$match": {"kind": "postevent", "event_type": "view", "dwell_ms": {"$gte": view_ms},
                    "created_at": {"$gte": since}, "undone_at": None, "post_id": {"$ne": None}}},
        {"$group": {"_id": {"user_id": "$user_id", "post_id": "$post_id"}}},
    ])
    return [row["_id"] async for row in cursor]


async def write_popularity(settings: Settings, rows: list[dict[str, Any]]) -> int:
    """One nightly batch of platform popularity rows (each carries its job_run_id)."""
    if not rows:
        return 0
    result = await _collection(ml_db(settings), "ml_measurements").insert_many(rows)
    return len(result.inserted_ids)


async def read_popularity(settings: Settings) -> list[dict[str, Any]]:
    """The current batch of platform popularity (never a half-written one), largest
    first. Empty when no batch has been made current yet."""
    job_run_id = await current_job_run_id(settings, "popularity", POPULARITY_METHOD)
    if job_run_id is None:
        return []
    cursor = ml_db(settings)["ml_measurements"].find(
        {"measure": POPULARITY_MEASURE, "job_run_id": job_run_id}
    ).sort("qualified_views", DESCENDING)
    return await cursor.to_list(None)


# --- M1 on the engine's copies (ENG-10) ------------------------------------------------------

#: The postevents types M1 reads from the engine's copy (ENG-10). Impressions,
#: remove_from_cart and the other new platform events are stored but carry no
#: weight; purchases come from the order, follows from the platform's follows.
M1_EVENT_TYPES = ("view", "click", "product_click", "like", "save", "comment", "share", "add_to_cart", "feedback")

_M1_EVENT_FIELDS = {f: 1 for f in ("user_id", "actor", "event_type", "post_id", "product_id", "dwell_ms",
                                   "feedback_type", "target_id", "target_type", "undone_at", "undo_of",
                                   "is_self", "created_at")}
_M1_ORDER_FIELDS = {f: 1 for f in ("order_id", "buyer_id", "buyer_actor", "product_id", "post_id", "status",
                                   "cancelled_at", "is_returned", "created_at")}


async def read_m1_event_copies(settings: Settings) -> list[dict[str, Any]]:
    """Every copied postevents row of a type M1 weighs (ENG-04 copies; one source per action)."""
    cursor = ml_db(settings)["ml_events"].find(
        {"kind": "postevent", "event_type": {"$in": list(M1_EVENT_TYPES)}}, _M1_EVENT_FIELDS
    )
    return await cursor.to_list(None)


async def read_order_copies(settings: Settings) -> list[dict[str, Any]]:
    """Every copied order (ml_orders): purchases, and their reversals, come from the order."""
    return await ml_db(settings)["ml_orders"].find({}, _M1_ORDER_FIELDS).to_list(None)


async def delete_unnamed_scores(settings: Settings) -> int:
    """ENG-10: "Delete any old time-windows rows that carry no method name, and
    recompute them." Rows with no method at all; the nightly run recomputes them."""
    result = await _collection(ml_db(settings), settings.scores_collection).delete_many(
        {"$or": [{"method": {"$exists": False}}, {"method": None}, {"method": ""}]}
    )
    return result.deleted_count


# --- return requests (ENG-30 point 7) ----------------------------------------------------------


async def read_open_return_orders(settings: Settings) -> set[str]:
    """Orders with an open return request (a copy with isActive true)."""
    cursor = ml_db(settings)["ml_return_requests"].find({"is_active": True}, {"order_id": 1})
    return {row["order_id"] async for row in cursor if row.get("order_id")}


async def return_requests_current(settings: Settings, now: datetime, hours: int) -> tuple[bool, str]:
    """ENG-30 point 7: the copy is current when its last sync completed within `hours`
    and its last reconciliation passed. Returns (current, why). A missing record is
    never proof that no request exists, so 'not current' is said out loud."""
    state = await ml_db(settings)["ml_sync_state"].find_one({"_id": "returnrequests"}) or {}
    last = state.get("last_run") or {}
    if last.get("outcome") != "succeeded" or not last.get("finished_at"):
        return False, "no completed sync of returnrequests"
    finished = last["finished_at"] if last["finished_at"].tzinfo else last["finished_at"].replace(tzinfo=timezone.utc)
    if now - finished > timedelta(hours=hours):
        return False, f"last sync of returnrequests finished {finished.isoformat()}, over {hours} h ago"
    check = await ml_db(settings)["ml_measurements"].find_one(
        {"measure": "sync_reconciliation", "source": "returnrequests"}, sort=[("day", DESCENDING)]
    )
    if not check:
        return False, "returnrequests has no reconciliation yet"
    if not check.get("passed"):
        return False, f"the last reconciliation of returnrequests ({check.get('day')}) did not pass"
    return True, "current"

