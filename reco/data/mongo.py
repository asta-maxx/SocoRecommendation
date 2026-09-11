"""Two MongoDB clients, held apart on purpose.

  app  reads SOCO application collections. Read-only credential (PT-01), with
       readPreference=secondaryPreferred so reading never competes with the
       application's own writes.
  ml   writes ml_ collections. A separate, write-capable credential whose
       privileges are scoped to the ml_ prefix and nothing else (Q14 Option A,
       requested as B5).

They are never interchanged: readers.py is handed the app database and writers.py
the ml database. Both may point at the same server locally; in production they
must not be the same user, and this module refuses to start if they are.

PyMongo's own async client is used. Motor is deprecated in favour of async
support inside PyMongo -- do not reintroduce it.
"""

from __future__ import annotations

import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from reco.config import Settings

logger = logging.getLogger(__name__)

_app_client: AsyncMongoClient | None = None
_ml_client: AsyncMongoClient | None = None


def _credential_of(uri: str) -> str | None:
    """The username in a connection string, or None if it carries no credential.

    Used only to warn when both connection strings authenticate as the same user,
    which would silently give the read path write access.
    """
    if "@" not in uri:
        return None
    authority = uri.split("//", 1)[-1].split("@", 1)[0]
    return authority.split(":", 1)[0] or None


def init_clients(settings: Settings) -> None:
    """Open both clients. Called once, from the application lifespan."""
    global _app_client, _ml_client

    if not settings.ml_mongo_uri:
        raise RuntimeError(  # noqa: TRY003 - the guidance is the point of the error
            "ML_MONGO_URI is not set. The service will not fall back to the "
            "application credential to write scores -- that credential is "
            "read-only by design and silently reusing it here would put the "
            "namespace guard behind an accident. Set ML_MONGO_URI (see "
            "HANDOFF.md for the db.createUser command)."
        )

    app_user = _credential_of(settings.app_mongo_uri)
    ml_user = _credential_of(settings.ml_mongo_uri)
    if app_user is not None and app_user == ml_user:
        logger.warning(
            "APP_MONGO_URI and ML_MONGO_URI authenticate as the same user. "
            "Acceptable locally; in production the read path must not hold write "
            "privileges -- see HANDOFF.md section 3."
        )

    # tz_aware so computed_at comes back as an aware datetime rather than a naive
    # one that would then fail the model's own validator on read.
    _app_client = AsyncMongoClient(settings.app_mongo_uri, tz_aware=True)
    _ml_client = AsyncMongoClient(settings.ml_mongo_uri, tz_aware=True)

    logger.info(
        "Mongo clients opened: app db=%s (read-only), ml db=%s (ml_ writes only)",
        settings.app_mongo_db,
        settings.ml_mongo_db,
    )


async def close_clients() -> None:
    """Close both clients. Called once, from the application lifespan."""
    global _app_client, _ml_client
    for client in (_app_client, _ml_client):
        if client is not None:
            await client.close()
    _app_client = None
    _ml_client = None


def app_db(settings: Settings) -> AsyncDatabase:
    """The SOCO application database. Read from this; never write to it."""
    if _app_client is None:
        raise RuntimeError("Mongo clients are not open -- call init_clients() first")
    return _app_client[settings.app_mongo_db]


def ml_db(settings: Settings) -> AsyncDatabase:
    """The database holding ml_ collections. Only writers.py may write here."""
    if _ml_client is None:
        raise RuntimeError("Mongo clients are not open -- call init_clients() first")
    return _ml_client[settings.ml_mongo_db]


def source_db(settings: Settings, collection: str) -> AsyncDatabase:
    """The database a SOURCE collection lives in, chosen by its name.

    Under the demo profile the event source is ml_demo_events, which the
    generator wrote into the ml_ namespace -- it could not write to an
    application collection. Under the live profile it is postevents, which lives
    in the application database behind the read-only credential.

    So the connection follows the collection rather than the caller. Reading
    ml_demo_events through the app credential would query a collection that does
    not exist there and return nothing, without raising.
    """
    if collection.startswith("ml_"):
        return ml_db(settings)
    return app_db(settings)


async def verify_databases(settings: Settings) -> None:
    """Warn loudly if a configured database name does not exist on the server.

    MongoDB database names are CASE SENSITIVE, and reading a database that does
    not exist is not an error -- every query against it simply returns nothing.
    That is the same silent-absence failure as querying an identifier with the
    wrong type: it looks like a user with no activity rather than like a bug, and
    it can survive all the way to a demonstration.

    A warning rather than a refusal, because the ml_ database is legitimately
    absent until the first write creates it.
    """
    if _app_client is None or _ml_client is None:
        raise RuntimeError("Mongo clients are not open -- call init_clients() first")

    # Each name is checked against ITS OWN client. The two connection strings may
    # address different clusters -- during the build they generally do -- so
    # checking both against one listing would report confident nonsense.
    try:
        app_databases = set(await _app_client.list_database_names())
    except Exception:
        logger.exception("Could not list databases on the app connection")
        app_databases = None

    if app_databases is not None and settings.app_mongo_db not in app_databases:
        near = [d for d in app_databases if d.lower() == settings.app_mongo_db.lower()]
        hint = (
            f" Did you mean {near[0]!r}? Database names are case sensitive."
            if near
            else f" Visible there: {sorted(app_databases)}."
        )
        logger.warning(
            "APP_MONGO_DB=%r does not exist on the app connection, so every read "
            "will return nothing without raising.%s",
            settings.app_mongo_db,
            hint,
        )

    try:
        ml_databases = set(await _ml_client.list_database_names())
    except Exception:
        # A correctly scoped ml_ credential may not hold listDatabases at all.
        # That is not a fault; it just means this check cannot run.
        logger.debug("Could not list databases on the ml connection -- skipping check")
        return

    if settings.ml_mongo_db not in ml_databases:
        logger.info(
            "ML_MONGO_DB=%r does not exist yet; the first score written creates it.",
            settings.ml_mongo_db,
        )


async def ping(settings: Settings) -> dict[str, bool]:
    """Liveness of both connections, for the health endpoint."""
    result = {"app": False, "ml": False}
    for name, database in (("app", app_db(settings)), ("ml", ml_db(settings))):
        try:
            await database.command("ping")
            result[name] = True
        except Exception:
            logger.exception("Mongo ping failed for the %s connection", name)
    return result
