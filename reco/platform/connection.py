"""The platform database connection. Read-only. SD-06, DB-02.

Only the platform module holds this client, so only the platform module can read
SOCO's database. It uses the read-only login, with
readPreference=secondaryPreferred so reading never competes with the
application's own writes.

The engine's own database is a separate connection in reco.store.connection.
PyMongo's own async client is used. Motor is deprecated in favour of async
support inside PyMongo -- do not reintroduce it.
"""

from __future__ import annotations

import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from reco.config import Settings
from reco.store.connection import ml_db

logger = logging.getLogger(__name__)

_client: AsyncMongoClient | None = None

#: Connections kept open (pymongo's minPoolSize). The pack sets no value.
MIN_POOL = 10


def init_client(settings: Settings) -> None:
    """Open the platform client. Called once, from startup."""
    global _client
    # tz_aware so timestamps come back as aware datetimes. A bounded server
    # selection wait, so an unreachable cluster fails loudly at startup instead
    # of hanging -- a paused Atlas cluster is the ordinary way this happens.
    _client = AsyncMongoClient(
        settings.app_mongo_uri,
        tz_aware=True,
        # Connections opened ahead, so a request never waits for one to be set up
        # (serving reads several things at once, ENG-06/ENG-08).
        minPoolSize=MIN_POOL,
        # SD-26, DS-017 4.6: no retries inside a request. The driver would otherwise
        # retry a failed read or write once by itself.
        retryReads=False,
        retryWrites=False,
        serverSelectionTimeoutMS=int(settings.mongo_timeout_seconds * 1000),
    )
    logger.info("Platform client opened: db=%s (read-only)", settings.app_mongo_db)


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
    _client = None


def app_db(settings: Settings) -> AsyncDatabase:
    """The SOCO platform database. Read from this; never write to it."""
    if _client is None:
        raise RuntimeError("Platform client is not open -- call init_client() first")
    return _client[settings.app_mongo_db]


def source_db(settings: Settings, collection: str) -> AsyncDatabase:
    """The database a SOURCE collection lives in, chosen by its name.

    Under the demo profile the sources are ml_demo_* collections, which the
    generator wrote into the engine database. Under the live profile they are
    platform collections, read through the read-only login.

    So the connection follows the collection rather than the caller. Reading
    ml_demo_events through the platform login would query a collection that does
    not exist there and return nothing, without raising.
    """
    if collection.startswith("ml_"):
        return ml_db(settings)
    return app_db(settings)


async def verify_database(settings: Settings) -> None:
    """Warn loudly if the platform database name does not exist on the server.

    MongoDB database names are CASE SENSITIVE, and reading a database that does
    not exist is not an error -- every query simply returns nothing, which looks
    like a user with no activity rather than like a bug.
    """
    if _client is None:
        raise RuntimeError("Platform client is not open -- call init_client() first")
    try:
        names = set(await _client.list_database_names())
    except Exception:
        logger.exception("Could not list databases on the platform connection")
        return

    if settings.app_mongo_db not in names:
        near = [d for d in names if d.lower() == settings.app_mongo_db.lower()]
        hint = (
            f" Did you mean {near[0]!r}? Database names are case sensitive."
            if near
            else f" Visible there: {sorted(names)}."
        )
        logger.warning(
            "APP_MONGO_DB=%r does not exist on the platform connection, so every "
            "read will return nothing without raising.%s",
            settings.app_mongo_db,
            hint,
        )


async def ping(settings: Settings) -> bool:
    """Whether the platform database can be reached, for the health check."""
    try:
        await app_db(settings).command("ping")
        return True
    except Exception:
        logger.exception("Ping failed on the platform connection")
        return False


async def warm(settings: Settings, connections: int = MIN_POOL) -> None:
    """Open the pool's connections now, in parallel, so the first requests don't pay
    for setting them up (a request has SOCO_BE's 250 ms at most, APP-15)."""
    import asyncio

    db = app_db(settings)
    # Warm the members reads actually go to (the URI's read preference, e.g. a
    # secondary), not only the primary that a plain ping would reach.
    await asyncio.gather(*(db.command("ping", read_preference=db.read_preference) for _ in range(connections)))
