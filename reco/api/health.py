"""GET /health. S9.

Done when the container starts and this returns 200.

Returns 200 whenever the process is serving. Mongo reachability is reported in
the body rather than turned into a non-200, because an unreachable database is
rung 5 of the fallback ladder -- the platform serves the delivered ordering
without calling this engine -- and an orchestrator restarting the container would
not help with that.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from reco.config import Settings, get_settings
from reco.data import mongo

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    connections = await mongo.ping(settings)
    return {
        "status": "ok",
        "model_version": settings.model_version,
        # Which collections this process is actually on. Reported because the
        # demo and live runs are the same code, so "which data is this?" is
        # otherwise unanswerable from the outside -- including on demo day.
        "data_profile": settings.data_profile,
        "collections": {
            "events_source": settings.events_collection,
            "scores_target": settings.scores_collection,
        },
        "mongo": connections,
    }
