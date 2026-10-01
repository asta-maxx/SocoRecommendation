"""FastAPI application. Wiring only. S8.

The one place things are joined together. No logic lives here -- if a decision is
being made in this file, it is in the wrong file.

    uvicorn reco.main:app --reload --port 8100
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from reco.api import health, profiles, recommendations
from reco.config import get_settings, live, sync
from reco.monitoring.logs import configure_logging, log_request
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.store.writers import ensure_engine_collections, ensure_indexes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)

    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    await platform_conn.verify_database(settings)
    await store_conn.verify_database(settings)
    try:
        await ensure_engine_collections(settings)
        await ensure_indexes(settings)
    except Exception:
        # A missing index makes scores slow and lets duplicates through; it does
        # not make the service wrong to start. Log loudly and carry on rather
        # than crash-looping a container over something an operator must fix.
        logger.exception(
            "Could not ensure indexes on startup -- check that the ml_ credential "
            "has createIndex on the ml_ prefix"
        )

    try:
        await asyncio.gather(platform_conn.warm(settings), store_conn.warm(settings))
    except Exception:
        logger.exception("could not open the database connections ahead; requests will open them")

    # ENG-02 items 3-4: the settings in force, then a reload at least once a minute.
    await sync.load_at_start(settings)
    reloader = asyncio.create_task(sync.reload_loop(settings))

    logger.info(
        "reco up: env=%s model_version=%s config_version=%s",
        settings.engine_env,
        settings.model_version,
        live.current().config_version,
    )
    yield
    reloader.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reloader
    await platform_conn.close_client()
    await store_conn.close_client()


app = FastAPI(
    title="SOCO M1 interest model",
    description=(
        "Computes one interest score per user per category. Reads the SOCO "
        "database read-only; writes only to collections prefixed ml_."
    ),
    version=get_settings().model_version,
    lifespan=lifespan,
)


# A browser calling this from a local dashboard is a cross-origin request, and
# without this the call fails before it reaches any handler.
#
# Wide open on purpose, and only defensible because of what this service is: it
# holds no credentials a caller could obtain, every route is read-only, and it
# runs on a laptop for a demonstration. Narrow ALLOWED_ORIGINS before it is
# deployed anywhere a browser it does not own can reach it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
        if o.strip()
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.middleware("http")(log_request)

app.include_router(health.router)
app.include_router(recommendations.router)
app.include_router(profiles.router)
