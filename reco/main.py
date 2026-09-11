"""FastAPI application. Wiring only. S8.

The one place things are joined together. No logic lives here -- if a decision is
being made in this file, it is in the wrong file.

    uvicorn reco.main:app --reload --port 8100
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from reco.api import health, profiles
from reco.config import get_settings
from reco.data import mongo
from reco.data.writers import ensure_indexes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    mongo.init_clients(settings)
    await mongo.verify_databases(settings)
    try:
        await ensure_indexes(settings)
    except Exception:
        # A missing index makes scores slow and lets duplicates through; it does
        # not make the service wrong to start. Log loudly and carry on rather
        # than crash-looping a container over something an operator must fix.
        logger.exception(
            "Could not ensure indexes on startup -- check that the ml_ credential "
            "has createIndex on the ml_ prefix"
        )

    logger.info("reco up: model_version=%s", settings.model_version)
    yield
    await mongo.close_clients()


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

app.include_router(health.router)
app.include_router(profiles.router)
