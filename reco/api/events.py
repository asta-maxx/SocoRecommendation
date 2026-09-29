"""POST /v1/events. ENG-04, DS-017 section 7.

Called by SOCO_BE only, from a queue, with Authorization: Bearer <INGEST_TOKEN>.

    200  {"accepted": n, "duplicates": n, "rejected": [{"event_id", "reason"}]}
    400  {"error": "invalid_body" | "too_many_events", "detail": ...}
    401  {"error": "unauthorized", "detail": ...}
    503  {"error": "engine_database_unavailable", "detail": ...}

A single bad event never fails the call: it is listed under "rejected" and the
rest are stored. Only a malformed call as a whole is a 400.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from reco.config import Settings, get_settings
from reco.events.ingest import BatchRefused, ingest

router = APIRouter(tags=["events"])
logger = logging.getLogger("reco.events")


def _error(status: int, code: str, detail: str) -> JSONResponse:
    """DS-017 section 4.6: the body is {"error": "<code>", "detail": "<text>"}."""
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def token_ok(settings: Settings, authorization: str | None) -> bool:
    """Authorization: Bearer <INGEST_TOKEN>, compared in constant time."""
    if not settings.ingest_token:
        logger.error("INGEST_TOKEN is not set; refusing every call to /v1/events")
        return False
    scheme, _, token = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        token.strip().encode(), settings.ingest_token.encode()
    )


@router.post("/v1/events")
async def post_events(request: Request, settings: Settings = Depends(get_settings)):
    if not token_ok(settings, request.headers.get("authorization")):
        return _error(401, "unauthorized", "missing or wrong bearer token")
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "invalid_body", "the body is not JSON")
    try:
        result = await ingest(settings, body)
    except BatchRefused as refused:
        return _error(400, refused.code, refused.detail)
    except Exception:
        # The engine database could not be written. SOCO_BE retries the batch
        # with the same event_ids, so nothing is lost or doubled.
        logger.exception("could not store events")
        return _error(503, "engine_database_unavailable", "events were not stored; retry with the same event_ids")
    logger.info(
        "events received",
        extra={"accepted": result.accepted, "duplicates": result.duplicates, "rejected": len(result.rejected)},
    )
    return result.reply()
