"""The engine database connection. SD-06, AS-09.

The engine's own database, holding every ml_ collection. Writes happen only
through reco.store.writers, which refuses any collection outside the ml_
namespace. The platform database is a separate, read-only connection in
reco.platform.connection.
"""

from __future__ import annotations

import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from reco.config import Settings

logger = logging.getLogger(__name__)

_client: AsyncMongoClient | None = None

#: Connections kept open (pymongo's minPoolSize). The pack sets no value.
MIN_POOL = 10


def _credential_of(uri: str) -> str | None:
    """The username in a connection string, or None if it carries no credential."""
    if "@" not in uri:
        return None
    authority = uri.split("//", 1)[-1].split("@", 1)[0]
    return authority.split(":", 1)[0] or None


def init_client(settings: Settings) -> None:
    """Open the engine client. Called once, from startup."""
    global _client

    if not settings.ml_mongo_uri:
        raise RuntimeError(  # noqa: TRY003 - the guidance is the point of the error
            "ML_MONGO_URI is not set. The engine will not fall back to the "
            "platform login to write -- that login is read-only by design."
        )

    platform_user = _credential_of(settings.app_mongo_uri)
    if platform_user is not None and platform_user == _credential_of(settings.ml_mongo_uri):
        logger.warning(
            "APP_MONGO_URI and ML_MONGO_URI authenticate as the same user. "
            "Acceptable locally; in production the platform login must be "
            "read-only and separate from the engine's login (DB-02)."
        )

    _client = AsyncMongoClient(
        settings.ml_mongo_uri,
        tz_aware=True,
        # Connections opened ahead, so a request never waits for one to be set up
        # (serving reads several things at once, ENG-06/ENG-08).
        minPoolSize=MIN_POOL,
        serverSelectionTimeoutMS=int(settings.mongo_timeout_seconds * 1000),
    )
    logger.info(
        "Engine client opened: db=%s (env=%s)", settings.ml_mongo_db, settings.engine_env
    )


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
    _client = None


def ml_db(settings: Settings) -> AsyncDatabase:
    """The engine database. Only reco.store.writers may write here."""
    if _client is None:
        raise RuntimeError("Engine client is not open -- call init_client() first")
    return _client[settings.ml_mongo_db]


async def verify_database(settings: Settings) -> None:
    """Note when the engine database does not exist yet; the first write creates it."""
    if _client is None:
        raise RuntimeError("Engine client is not open -- call init_client() first")
    try:
        names = set(await _client.list_database_names())
    except Exception:
        # A correctly scoped engine login may not hold listDatabases at all.
        logger.debug("Could not list databases on the engine connection -- skipping check")
        return
    if settings.ml_mongo_db not in names:
        logger.info(
            "ML_MONGO_DB=%r does not exist yet; the first write creates it.",
            settings.ml_mongo_db,
        )


async def ping(settings: Settings) -> bool:
    """Whether the engine database can be reached, for the health check."""
    try:
        await ml_db(settings).command("ping")
        return True
    except Exception:
        logger.exception("Ping failed on the engine connection")
        return False
