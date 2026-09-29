"""Read platform records, parsed by the ENG-03 rules.

    await read_records(settings, "follow", {"userId": id_match(user_id)})
    await read_switched(settings, "click", start, end, switch_date)

Every document is parsed by reco.platform.records, so a caller never sees a raw
platform field. Collection names come from reco.config.PLATFORM_COLLECTIONS.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from reco.config import PLATFORM_COLLECTIONS, Settings
from reco.platform import records
from reco.platform.categories import ProductCategoryIndex
from reco.platform.connection import app_db
from reco.platform.readers import vocabulary
from reco.platform.sources import SWITCHED, spans
from reco.store.connection import ml_db

#: ml_events names for the switched kinds (DS-017 section 6.2). Their fields
#: carry the same names as the old collections', so one parser reads both.
ML_EVENT_NAMES: dict[str, str] = {
    "request": "recommendation_request",
    "impression": "recommendation_impression",
    "click": "recommendation_click",
    "content_feedback": "content_feedback",
}

_SWITCHED_PARSERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "request": records.parse_legacy_request,
    "impression": records.parse_legacy_impression,
    "click": records.parse_legacy_click,
    "content_feedback": records.parse_legacy_content_feedback,
}


async def product_categories(settings: Settings) -> ProductCategoryIndex:
    """The categoryId -> one-of-the-23 index, from the categories collection."""
    docs = await app_db(settings)[PLATFORM_COLLECTIONS["category"]].find(
        {}, {"path": 1, "name": 1}
    ).to_list(None)
    return ProductCategoryIndex.build(vocabulary(settings), docs)


async def _parser(settings: Settings, kind: str) -> Callable[[dict[str, Any]], Any]:
    vocab = vocabulary(settings)
    if kind in {"user", "business", "post", "category"}:
        parse = getattr(records, f"parse_{kind}")
        return lambda doc: parse(doc, vocab)
    if kind == "product":
        index = await product_categories(settings)
        return lambda doc: records.parse_product(doc, index)
    return getattr(records, f"parse_{kind}")


async def read_records(
    settings: Settings,
    kind: str,
    query: dict[str, Any] | None = None,
    limit: int | None = None,
) -> list[Any]:
    """Read and parse one kind of platform record. `kind` is in records.RECORD_KINDS."""
    if kind not in records.RECORD_KINDS:
        raise ValueError(f"unknown record kind {kind!r}")
    parse = await _parser(settings, kind)
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find(query or {})
    if limit:
        cursor = cursor.limit(limit)
    return [parse(doc) async for doc in cursor]


async def read_switched(
    settings: Settings,
    kind: str,
    start: datetime,
    end: datetime,
    switch_date: date | None,
    query: dict[str, Any] | None = None,
) -> list[Any]:
    """Requests, impressions, clicks or content feedback over [start, end).

    Each part of the window is read from exactly one source (ENG-03): the old
    collection before the switch date, ml_events from it onward.
    """
    if kind not in SWITCHED:
        raise ValueError(f"{kind!r} does not switch source; use read_records")
    parse = _SWITCHED_PARSERS[kind]
    found: list[Any] = []
    for span in spans(start, end, switch_date):
        window = {"server_ts": {"$gte": span.start, "$lt": span.end}, **(query or {})}
        if span.source == "legacy":
            collection = app_db(settings)[PLATFORM_COLLECTIONS[f"legacy_{kind}"]]
        else:
            collection = ml_db(settings)["ml_events"]
            window["event_name"] = ML_EVENT_NAMES[kind]
        found.extend([parse(doc) async for doc in collection.find(window)])
    return found
