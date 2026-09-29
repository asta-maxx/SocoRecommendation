"""Receive a batch of events: check, de-duplicate, store, reply. ENG-04 items 1, 3-6.

The rules are the Build List's (ENG-04 item 3) and DS-017 section 7, and no
others. Each field check applies only to events that carry the field:

  - every event carries event_id, event_name and user_id (ENG-04);
  - event_name is one of the eight Wave 1A names (ENG-04);
  - a position of 0 is rejected (impressions and clicks);
  - a surface other than feed or product is rejected (requests);
  - an item_type other than post or product is rejected (impressions and clicks);
  - request_id must be present on recommendation_request, _impression and _click.

Everything else is stored exactly as sent. Duplicates are found by event_id:
repeats inside one batch here, and repeats of earlier batches by the unique
index on ml_events (ENG-01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reco.config import Settings
from reco.platform.ids import as_utc
from reco.store import writers
from reco.store.scores import utc_now

#: ENG-04: "Event names". The Wave 1A events; the deferred ones (E7, E8, E10,
#: E11) and the closed one (E12) are not accepted.
EVENT_NAMES: frozenset[str] = frozenset(
    {
        "recommendation_request",
        "recommendation_impression",
        "recommendation_click",
        "add_to_cart",
        "order_placed",
        "order_state_changed",
        "social_interaction",
        "content_feedback",
    }
)

#: ENG-04: request_id is required on these; may be empty on the others.
REQUEST_ID_REQUIRED: frozenset[str] = frozenset(
    {"recommendation_request", "recommendation_impression", "recommendation_click"}
)

SURFACES: frozenset[str] = frozenset({"feed", "product"})
ITEM_TYPES: frozenset[str] = frozenset({"post", "product"})

#: DS-017 section 7, [Assumed: AS-05]: up to 100 events per call.
MAX_EVENTS_PER_CALL = 100


class BatchRefused(Exception):
    """The call as a whole is malformed (400). Individual events are never refused this way."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def reason_to_reject(event: Any) -> str | None:
    """Why ENG-04 rejects this event, or None if it is accepted."""
    if not isinstance(event, dict):
        return "an event must be a JSON object"
    for required in ("event_id", "event_name", "user_id"):
        if _blank(event.get(required)):
            return f"{required} is missing (every event carries event_id, event_name and user_id)"
    if not isinstance(event["event_id"], str):
        return "event_id must be a string (a UUID v4)"
    name = event["event_name"]
    if name not in EVENT_NAMES:
        return f"event_name {name!r} is not a Wave 1A event"
    if "position" in event and event["position"] == 0:
        return "position 0 is not allowed: positions count from 1"
    if "surface" in event and event["surface"] not in SURFACES:
        return f"surface {event['surface']!r} is not feed or product"
    if "item_type" in event and event["item_type"] not in ITEM_TYPES:
        return f"item_type {event['item_type']!r} is not post or product"
    if name in REQUEST_ID_REQUIRED and _blank(event.get("request_id")):
        return f"request_id is missing, and {name} must carry one"
    return None


def to_document(event: dict[str, Any], received_at: Any) -> dict[str, Any]:
    """The event as stored: exactly as sent, plus the time it was received.

    server_ts becomes a stored date when it is a readable time, so the
    (user_id, server_ts) index and the ENG-03 day windows work. client_ts is
    kept exactly as sent (DS-017 section 3).
    """
    document = dict(event)
    server_ts = as_utc(event.get("server_ts"))
    if server_ts is not None:
        document["server_ts"] = server_ts
    document["received_at"] = received_at
    return document


@dataclass
class IngestResult:
    accepted: int = 0
    duplicates: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def reply(self) -> dict[str, Any]:
        """ENG-04 item 6."""
        return {"accepted": self.accepted, "duplicates": self.duplicates, "rejected": self.rejected}


def read_batch(body: Any) -> list[Any]:
    """The events list from a request body, or BatchRefused (400)."""
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        raise BatchRefused("invalid_body", 'the body must be {"events": [ ... ]}')
    events = body["events"]
    if len(events) > MAX_EVENTS_PER_CALL:
        raise BatchRefused(
            "too_many_events", f"{len(events)} events in one call; at most {MAX_EVENTS_PER_CALL}"
        )
    return events


async def ingest(settings: Settings, body: Any) -> IngestResult:
    """ENG-04: check each event, drop duplicates, store the rest in ml_events."""
    events = read_batch(body)
    result = IngestResult()
    received_at = utc_now()
    to_store: list[dict[str, Any]] = []
    seen: set[str] = set()

    for event in events:
        reason = reason_to_reject(event)
        if reason is not None:
            event_id = event.get("event_id") if isinstance(event, dict) else None
            result.rejected.append({"event_id": event_id, "reason": reason})
            continue
        if event["event_id"] in seen:  # the same event twice in one batch
            result.duplicates += 1
            continue
        seen.add(event["event_id"])
        to_store.append(to_document(event, received_at))

    stored, duplicate = await writers.insert_events(settings, to_store)
    result.accepted += len(stored)
    result.duplicates += len(duplicate)
    return result
