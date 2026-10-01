"""POST /v1/recommendations: return a list and record it. ENG-06, DS-017 v2.5 section 4.

    Authorization: Bearer <INGEST_TOKEN>
    {"user_id": "...", "surface": "feed", "page": 1, "limit": 20, "session_id": "ses_..."}
    {"user_id": "...", "surface": "product", "context_item_id": "...", "page": 1, "limit": 10, "session_id": "..."}

    200  {request_id, policy_id, model_version, config_version, fallback_step, is_exploration, items}
    400  invalid surface, limit or page, or no context_item_id on product
    401  missing or wrong token
    503  surface off (or internal and not a test account), or a database fault

Error bodies are {"error": "<code>", "detail": "<text>"} (DS-017 4.6). A
database that can't be read is an error at once, never retried (SD-26).

For every list the engine writes its recommendation_request (E1) record to
ml_events first: request_id, surface, user_id, session_id, policy_id, server_ts
(UTC, milliseconds), candidate_ids (never returned), served_items (exactly as
returned), config_version, each slot's intended method and fallback step, and
the scored sample.

Interim, until ENG-09, ENG-17 and ENG-19: the list is eligible items newest
first (reco.ranking.serving); no slot's score is read, so fallback_step is null
and each slot records the method it would use. Both surfaces stay off in
production until then (settings serving.surface_mode_*).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from reco.api.auth import token_ok
from reco.config import Settings, get_settings, live
from reco.config.accounts import is_test_account
from reco.ranking import serving
from reco.slots.assignment import Assignment, assign, method_number, policy_id
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.api.recommendations")

router = APIRouter()

SURFACES = ("feed", "product")

#: The slots each surface's list uses: the feed ranks with interest (M1) and the
#: promoter score (M8, ENG-19); product rails with product ranking (M5, ENG-17).
SLOTS_BY_SURFACE = {"feed": ("interest", "promoter_score"), "product": ("product_ranking",)}

#: Recorded on the E1 so a list built before the rankers exist is never mistaken
#: for a ranked one.
INTERIM_ORDERING = "interim_newest_first"


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def _bad_request(body: Any) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    if not isinstance(body, dict):
        return None, _error(400, "invalid_body", "the body must be a JSON object")
    surface = body.get("surface")
    if surface not in SURFACES:
        return None, _error(400, "invalid_surface", "surface must be feed or product")
    page, limit = body.get("page"), body.get("limit")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return None, _error(400, "invalid_page", "page must be a whole number from 1")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        return None, _error(400, "invalid_limit", "limit must be a whole number from 1 to 50")
    context = body.get("context_item_id")
    if surface == "product" and not (isinstance(context, str) and ObjectId.is_valid(context)):
        return None, _error(400, "missing_context_item_id", "context_item_id (a 24-character product id) is required on product")
    user_id = body.get("user_id")
    return {
        "user_id": user_id if isinstance(user_id, str) and user_id.strip() else None,
        "surface": surface,
        "page": page,
        "limit": limit,
        "session_id": body.get("session_id") if isinstance(body.get("session_id"), str) else None,
        "context_item_id": context if surface == "product" else None,
    }, None


def _slot_record(a: Assignment) -> dict[str, Any]:
    return {"method": a.method, "method_number": method_number(a), "bucket": a.bucket,
            "from_default": a.from_default, "fallback_step": None}


@router.post("/v1/recommendations")
async def recommendations(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
):
    if not token_ok(settings, authorization):
        return _error(401, "unauthorized", "missing or wrong bearer token")
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_body", "the body must be JSON")
    asked, problem = _bad_request(body)
    if problem:
        return problem

    tunables = live.current()  # one reading of the settings for the whole request
    surface = asked["surface"]
    mode = getattr(tunables.serving, f"surface_mode_{surface}")
    if mode == "off":
        return _error(503, "surface_off", f"the {surface} surface is off")
    if mode == "internal" and not is_test_account(asked["user_id"]):
        return _error(503, "surface_internal", f"the {surface} surface serves test accounts only")

    assignments = [assign(slot, asked["user_id"] or "", tunables) for slot in SLOTS_BY_SURFACE[surface]]
    request_id = str(uuid.uuid4())
    server_ts = utc_now()
    try:
        candidates = await serving.interim_candidates(
            settings, surface, asked["page"], asked["limit"], asked["context_item_id"]
        )
    except Exception as exc:
        logger.error("platform database unreadable", extra={"request_id": request_id, "error": repr(exc)[:300]})
        return _error(503, "database_unavailable", "the platform database could not be read")

    start = (asked["page"] - 1) * asked["limit"]
    page_items = candidates[start:start + asked["limit"]]
    exploration = serving.decide_exploration(surface, tunables.serving.exploration_percent)
    if exploration:
        page_items = serving.explore(page_items, tunables.serving.exploration_top_kept)
    items = [c.card(position) for position, c in enumerate(page_items, start=1)]

    response = {
        "request_id": request_id,
        "policy_id": policy_id(*assignments, config_version=tunables.config_version),
        "model_version": settings.model_version,
        "config_version": tunables.config_version,
        "fallback_step": None,
        "is_exploration": exploration,
        "items": items,
    }
    record = {
        "_id": request_id,
        "request_id": request_id,
        "event_code": "E1",
        "event_type": "recommendation_request",
        "kind": "served_list",
        "source": "engine",
        "surface": surface,
        "user_id": asked["user_id"],
        "session_id": asked["session_id"],
        "page": asked["page"],
        "limit": asked["limit"],
        "context_item_id": asked["context_item_id"],
        "policy_id": response["policy_id"],
        "model_version": settings.model_version,
        "config_version": tunables.config_version,
        "server_ts": server_ts,
        "created_at": server_ts,  # the retention expiry runs from it (ENG-01)
        "candidate_ids": [c.item_id for c in candidates],
        "served_items": items,
        "slots": {a.slot: _slot_record(a) for a in assignments},
        "fallback_step": None,
        "is_exploration": exploration,
        "is_fallback": False,
        "ordering": INTERIM_ORDERING,
        "scored_sample": serving.scored_sample(
            candidates, {c.item_id for c in page_items}, exploration, tunables.serving.sample_random_percent
        ),
    }
    try:
        await writers.record_served_list(settings, record)
    except Exception as exc:
        logger.error("engine database unwritable", extra={"request_id": request_id, "error": repr(exc)[:300]})
        return _error(503, "database_unavailable", "the served list could not be recorded")
    logger.info("served list", extra={"request_id": request_id, "surface": surface, "items": len(items),
                                      "policy_id": response["policy_id"], "is_exploration": exploration})
    return response
