"""GET /health. ENG-02 item 5, SD-28.

200 when both database connections work -- the platform database (read-only) and
the engine's own database. 503 when either does not. SD-26: if either database
cannot be read the service must answer at once so SOCO_BE falls back, and the
health check reports the same condition.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from reco.config import Settings, get_settings
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response, settings: Settings = Depends(get_settings)) -> dict:
    connections = {
        "app": await platform_conn.ping(settings),
        "ml": await store_conn.ping(settings),
    }
    healthy = all(connections.values())
    if not healthy:
        response.status_code = 503
    return {
        "status": "ok" if healthy else "unavailable",
        # Which of dev, test and production this is (ENG-01).
        "environment": settings.engine_env,
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
