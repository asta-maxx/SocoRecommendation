"""What the engine sync copies, and the shape of each copy. ENG-04 items 1, 5, 9.

    SYNC_SOURCES   the platform collections the sync reads, the engine collection
                   each is copied into, and the fields the daily reconciliation
                   compares
    make_copy      one platform row -> one engine copy (pure: no database)
    with_history   an order copy with its status history carried forward

A copy is keyed on the platform row's _id. It carries:

    source, source_id      the platform collection and the row's _id as text
    kind                   the record kind (postevent, order, served_list)
    the parsed record      every field ENG-03 reads (event_id, undo_of,
                           undone_at, the E code, item identity, ...)
    created_at             the ORIGINAL event time, from the platform row; the
                           retention expiry runs from it (ENG-01, item 6), so an
                           update never resets it
    updated_at             the platform row's, the sync key
    platform               the platform row as read, so the reconciliation can
                           compare field values exactly (item 8)

rec_serve_log (ENG-29 item 7) is read the same way as recommendationrequests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reco.config import PLATFORM_COLLECTIONS
from reco.config.tunables import OrderStatusValues
from reco.platform import records
from reco.platform.ids import as_utc, to_str


@dataclass(frozen=True)
class SyncSource:
    kind: str  # the record kind in reco.platform.records
    target: str  # the engine collection the copies go into
    time_fields: tuple[str, ...]  # the platform row's own time, for the reconciliation's day
    compared: tuple[str, ...]  # field values the reconciliation compares (item 8)
    #: Written once, never changed (rec_serve_log): no updated_at is needed; new
    #: rows are read by _id, carrying on from the backfill's position.
    append_only: bool = False

    @property
    def collection(self) -> str:
        return PLATFORM_COLLECTIONS[self.kind]


#: Item 1: postevents, orders and recommendationrequests; ENG-29 adds rec_serve_log. For orders,
#: tracking_info is compared in place of statusLog and return_info, which the
#: platform does not have (ENG-29 item 4).
SYNC_SOURCES: tuple[SyncSource, ...] = (
    SyncSource("postevent", "ml_events", ("created_at",), ("undone_at", "undo_of", "updated_at")),
    SyncSource("order", "ml_orders", ("created_at",), ("order_status", "tracking_info", "updated_at")),
    SyncSource("served_list", "ml_events", ("server_ts", "created_at"), ("seen_ids", "updated_at")),
    # ENG-29 item 7. One row per list request, written once (DS-017 4.3), so it
    # has no updated_at: new rows are read by _id (append_only).
    SyncSource("serve_log", "ml_events", ("time", "timestamp", "created_at"), ("origin", "outcome", "elapsed_ms"),
               append_only=True),
)


def source_named(collection: str) -> SyncSource:
    for source in SYNC_SOURCES:
        if source.collection == collection:
            return source
    raise ValueError(f"the sync does not read {collection!r}")


def make_copy(source: SyncSource, doc: dict[str, Any], statuses: OrderStatusValues) -> dict[str, Any]:
    """The engine copy of one platform row."""
    if source.kind == "postevent":
        fields = records.parse_postevent(doc).model_dump()
    elif source.kind == "order":
        fields = records.parse_order(doc, statuses).model_dump()  # tracking stages from the settings in force
    elif source.kind == "served_list":
        fields = records.parse_served_list(doc).model_dump()
        # The served list is the E1 record. Copies of the platform's lists are
        # fallback lists unless their policy_id says cfg (F06).
        fields |= {
            "event_type": "served_list",
            "event_code": "E1",
            "scored": False,
            "seen_ids": [to_str(i) for i in doc.get("seen_ids") or []],
        }
    elif source.kind == "serve_log":
        fields = records.parse_serve_log(doc).model_dump() | {"event_type": "serve_log", "event_code": None, "scored": False}
    else:  # pragma: no cover - SYNC_SOURCES lists only these
        raise ValueError(f"no copy rule for {source.kind!r}")
    return {
        **fields,
        "_id": doc["_id"],
        "source": source.collection,
        "source_id": to_str(doc["_id"]),
        "kind": source.kind,
        "platform": {k: v for k, v in doc.items() if k != "_id"},
    }


def with_history(copy: dict[str, Any], held: dict[str, Any] | None) -> dict[str, Any]:
    """Item 9: carry the order's status history forward, adding the status now seen
    if it differs from the last one held, with its time (updated_at).

    ENG-29 item 4 makes tracking_info the order's history; this record of what
    the sync itself observed is kept as a cross-check.
    """
    history = list((held or {}).get("status_history") or [])
    status = copy.get("status")
    if status is not None and (not history or history[-1]["status"] != status):
        at = as_utc(copy.get("updated_at")) or copy.get("created_at")
        history.append({"status": status, "at": at})
    return {**copy, "status_history": history}
