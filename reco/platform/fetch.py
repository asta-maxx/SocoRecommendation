"""Read platform records, parsed by the ENG-03 rules.

    await read_records(settings, "follow", {"userId": id_match(user_id)})

Every document is parsed by reco.platform.records, so a caller never sees a raw
platform field. Collection names come from reco.config.PLATFORM_COLLECTIONS.
"""

from __future__ import annotations

from typing import Any, Callable

from reco.config import PLATFORM_COLLECTIONS, Settings, live
from reco.platform import records
from reco.platform.categories import ProductCategoryIndex
from reco.platform.connection import app_db
from reco.platform.readers import vocabulary


async def product_categories(settings: Settings) -> ProductCategoryIndex:
    """The category id -> one-of-the-23 index, from the categories collection and the category map."""
    docs = await app_db(settings)[PLATFORM_COLLECTIONS["category"]].find(
        {}, {"path": 1, "name": 1}
    ).to_list(None)
    return ProductCategoryIndex.build(vocabulary(settings), docs, live.current().lists.category_map)


async def _parser(settings: Settings, kind: str) -> Callable[[dict[str, Any]], Any]:
    vocab = vocabulary(settings)
    lists = live.current().lists
    if kind in {"user", "business", "post", "category"}:
        parse = getattr(records, f"parse_{kind}")
        return lambda doc: parse(doc, vocab, lists.category_map)
    if kind == "product":
        index = await product_categories(settings)
        return lambda doc: records.parse_product(doc, index)
    if kind == "order":
        return lambda doc: records.parse_order(doc, lists.order_status)
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


# --- reads for the engine sync (ENG-04) -------------------------------------------------
#
# Raw documents, not records: the sync keeps the platform row as well as the
# parsed fields on each copy. Every read is ordered, so a page boundary never
# drops or repeats a row.


def _oid(value: Any) -> Any:
    """A stored id as the type the platform uses for _id (ObjectId where it parses)."""
    from bson import ObjectId

    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else value


async def read_page_by_id(settings: Settings, kind: str, after_id: Any, limit: int) -> list[dict[str, Any]]:
    """Backfill: rows in _id order, after `after_id` (None = from the start)."""
    query = {"_id": {"$gt": _oid(after_id)}} if after_id is not None else {}
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find(query).sort("_id", 1).limit(limit)
    return await cursor.to_list(None)


async def read_page_by_updated_at(
    settings: Settings, kind: str, since: Any, after: tuple[Any, Any] | None, limit: int
) -> list[dict[str, Any]]:
    """Incremental: rows with updated_at >= since, ordered by (updated_at, _id), after the
    keyset position `after` = (updated_at, _id). Two rows with the same updated_at
    across a page boundary are both read (ENG-04 check d)."""
    if after is None:
        query: dict[str, Any] = {"updated_at": {"$gte": since}}
    else:
        at, last_id = after
        query = {"$or": [{"updated_at": {"$gt": at}}, {"updated_at": at, "_id": {"$gt": _oid(last_id)}}]}
    cursor = (
        app_db(settings)[PLATFORM_COLLECTIONS[kind]]
        .find(query)
        .sort([("updated_at", 1), ("_id", 1)])
        .limit(limit)
    )
    return await cursor.to_list(None)


async def read_by_ids(settings: Settings, kind: str, ids: list[Any]) -> list[dict[str, Any]]:
    """Specific platform rows, for the reconciliation's re-read."""
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find({"_id": {"$in": [_oid(i) for i in ids]}})
    return await cursor.to_list(None)


async def read_touched(settings: Settings, kind: str, time_fields: tuple[str, ...], start: Any, end: Any) -> list[dict[str, Any]]:
    """Rows created or changed in [start, end): the reconciliation's day.

    Created: any of `time_fields` in the day, or, for a row without them, its _id
    (ENG-03 reads the time from the _id where the field is missing)."""
    from bson import ObjectId

    window = {"$gte": start, "$lt": end}
    query = {"$or": [
        *({field: window} for field in time_fields),
        {"updated_at": window},
        {"_id": {"$gte": ObjectId.from_datetime(start), "$lt": ObjectId.from_datetime(end)}},
    ]}
    return await app_db(settings)[PLATFORM_COLLECTIONS[kind]].find(query).to_list(None)


# --- reads for serving (ENG-06) ---------------------------------------------------------

#: The time each kind is ordered by, newest first.
_NEWEST_BY = {"post": "timestamp", "product": "createdAt"}

#: Narrowed at the database so fewer rows travel; the eligibility module still
#: checks every record (ENG-06: re-checked when each list is built).
_SERVABLE = {
    "post": {"visibility": "public", "isHidden": {"$ne": True}},
    "product": {"status": {"$regex": r"^\s*activate\s*$", "$options": "i"}, "availability.inStock": True},
}

_EMPTY_INDEX = ProductCategoryIndex()


async def read_newest(settings: Settings, kind: str, limit: int, skip: int = 0) -> list[Any]:
    """Posts or products, newest first, parsed. A serving read: products skip the
    category lookup (no list built here needs a product's category yet)."""
    if kind == "product":
        parse: Callable[[dict[str, Any]], Any] = lambda doc: records.parse_product(doc, _EMPTY_INDEX)  # noqa: E731
    else:
        parse = await _parser(settings, kind)
    cursor = (
        app_db(settings)[PLATFORM_COLLECTIONS[kind]]
        .find(_SERVABLE[kind])
        .sort([(_NEWEST_BY[kind], -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )
    return [parse(doc) async for doc in cursor]
