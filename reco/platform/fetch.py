"""Read platform records, parsed by the ENG-03 rules.

    await read_records(settings, "follow", {"userId": id_match(user_id)})

Every document is parsed by reco.platform.records, so a caller never sees a raw
platform field. Collection names come from reco.config.PLATFORM_COLLECTIONS.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from reco.config import PLATFORM_COLLECTIONS, Settings, live
from reco.platform import records
from reco.platform.categories import ProductCategoryIndex, canonical_name
from reco.platform.connection import app_db
from reco.platform.ids import maybe_str
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
        return lambda doc: records.parse_order(doc, lists.order_status, lists.tracking_stages)
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
def _servable(kind: str) -> dict[str, Any]:
    if kind == "post":
        return {"visibility": "public", "isHidden": {"$ne": True}}
    # 'Activate', ignoring case, or any spelling the settings map to it (ENG-29 item 2).
    spellings = "|".join(re.escape(v) for v in records.spellings_of("activate"))
    return {"status": {"$regex": rf"^\s*({spellings})\s*$", "$options": "i"}, "availability.inStock": True}

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
        .find(_servable(kind))
        .sort([(_NEWEST_BY[kind], -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )
    return [parse(doc) async for doc in cursor]


# --- categories in use (ENG-29 item 1) ----------------------------------------------------


async def categories_in_use(settings: Settings) -> dict[str, dict[str, int]]:
    """Every category label the platform uses, and how many items use it, by where it
    is used: post categories, users' interests, business categories, and the top
    of each product's category path (categoryPathIds[0], else basicInfo.categoryId,
    looked up in the categories tree)."""
    db = app_db(settings)
    found: dict[str, dict[str, int]] = {}

    def add(label: Any, where: str, count: int) -> None:
        if isinstance(label, str) and label.strip():
            found.setdefault(label.strip(), {}).setdefault(where, 0)
            found[label.strip()][where] += count

    for kind, field, where in (("post", "categories", "posts"), ("user", "interest", "user interests"),
                               ("business", "category", "businesses")):
        pipeline = [{"$project": {"v": f"${field}"}}, {"$unwind": "$v"}, {"$group": {"_id": "$v", "n": {"$sum": 1}}}]
        async for row in await db[PLATFORM_COLLECTIONS[kind]].aggregate(pipeline):
            add(row["_id"], where, row["n"])

    tree = {
        maybe_str(doc["_id"]): (doc.get("path") or [doc.get("name")])[0]
        async for doc in db[PLATFORM_COLLECTIONS["category"]].find({}, {"path": 1, "name": 1})
    }
    pipeline = [
        {"$project": {"c": {"$ifNull": [{"$arrayElemAt": ["$categoryPathIds", 0]}, "$basicInfo.categoryId"]}}},
        {"$group": {"_id": "$c", "n": {"$sum": 1}}},
    ]
    async for row in await db[PLATFORM_COLLECTIONS["product"]].aggregate(pipeline):
        top = tree.get(maybe_str(row["_id"]))
        label = top if top else ("(no category id)" if row["_id"] is None else f"(category id {maybe_str(row['_id'])} not in the tree)")
        add(label, "products", row["n"])
    return found


async def unmapped_categories(settings: Settings) -> list[dict[str, Any]]:
    """Labels in use that match none of the 23 by name or through the category map:
    left out of category scoring until mapped, never guessed."""
    vocab = vocabulary(settings)
    category_map = live.current().lists.category_map
    return sorted(
        ({"label": label, "used_by": uses, "items": sum(uses.values())}
         for label, uses in (await categories_in_use(settings)).items()
         if canonical_name(vocab, label, category_map) is None),
        key=lambda row: -row["items"],
    )
