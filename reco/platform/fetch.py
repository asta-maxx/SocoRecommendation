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
from reco.platform.ids import id_match, maybe_str
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
    # Only the fields the engine reads (F8: store records also hold PAN, Aadhaar, GST
    # and bank details, which are never read or copied).
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find(query or {}, _FIELDS.get(kind))
    if limit:
        cursor = cursor.limit(limit)
    return [parse(doc) async for doc in cursor]


# --- reads for the engine sync (ENG-04) -------------------------------------------------
#
# Raw documents, not records: the sync keeps the platform row as well as the
# parsed fields on each copy. Every read is ordered, so a page boundary never
# drops or repeats a row.


#: Raw reads for the sync keep the whole row, except where a collection holds personal
#: fields the engine must never read (returnrequests, ENG-30 point 7).
_SYNC_FIELDS: dict[str, dict[str, int] | None] = {
    "return_request": {f: 1 for f in records.RETURN_REQUEST_FIELDS},
}


def _oid(value: Any) -> Any:
    """A stored id as the type the platform uses for _id (ObjectId where it parses)."""
    from bson import ObjectId

    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else value


async def read_page_by_id(settings: Settings, kind: str, after_id: Any, limit: int) -> list[dict[str, Any]]:
    """Backfill: rows in _id order, after `after_id` (None = from the start)."""
    query = {"_id": {"$gt": _oid(after_id)}} if after_id is not None else {}
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find(query, _SYNC_FIELDS.get(kind)).sort("_id", 1).limit(limit)
    return await cursor.to_list(None)


async def read_page_by_updated_at(
    settings: Settings, kind: str, since: Any, after: tuple[Any, Any] | None, limit: int, field: str = "updated_at"
) -> list[dict[str, Any]]:
    """Incremental: rows with updated_at >= since, ordered by (updated_at, _id), after the
    keyset position `after` = (updated_at, _id). Two rows with the same updated_at
    across a page boundary are both read (ENG-04 check d)."""
    if after is None:
        query: dict[str, Any] = {field: {"$gte": since}}
    else:
        at, last_id = after
        query = {"$or": [{field: {"$gt": at}}, {field: at, "_id": {"$gt": _oid(last_id)}}]}
    cursor = (
        app_db(settings)[PLATFORM_COLLECTIONS[kind]]
        .find(query, _SYNC_FIELDS.get(kind))
        .sort([(field, 1), ("_id", 1)])
        .limit(limit)
    )
    return await cursor.to_list(None)


async def read_by_ids(settings: Settings, kind: str, ids: list[Any]) -> list[dict[str, Any]]:
    """Specific platform rows, for the reconciliation's re-read."""
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find({"_id": {"$in": [_oid(i) for i in ids]}}, _SYNC_FIELDS.get(kind))
    return await cursor.to_list(None)


async def read_touched(
    settings: Settings, kind: str, time_fields: tuple[str, ...], start: Any, end: Any, updated_field: str = "updated_at"
) -> list[dict[str, Any]]:
    """Rows created or changed in [start, end): the reconciliation's day.

    Created: any of `time_fields` in the day, or, for a row without them, its _id
    (ENG-03 reads the time from the _id where the field is missing)."""
    from bson import ObjectId

    window = {"$gte": start, "$lt": end}
    query = {"$or": [
        *({field: window} for field in time_fields),
        {updated_field: window},
        {"_id": {"$gte": ObjectId.from_datetime(start), "$lt": ObjectId.from_datetime(end)}},
    ]}
    return await app_db(settings)[PLATFORM_COLLECTIONS[kind]].find(query, _SYNC_FIELDS.get(kind)).to_list(None)


# --- reads for serving (ENG-06) ---------------------------------------------------------

#: The time each kind is ordered by, newest first.
_NEWEST_BY = {"post": "timestamp", "product": "createdAt"}

#: No filter at the database: every item goes through the eligibility rules,
#: so every exclusion is logged with its rule (ENG-08).
_EMPTY_INDEX = ProductCategoryIndex()

#: Serving and eligibility read only the fields the parsers use. Product documents
#: carry images, specifications and policies; reading them whole is most of the time.
_FIELDS: dict[str, dict[str, int]] = {
    "post": {f: 1 for f in ("userId", "userModel", "timestamp", "categories", "postType", "postTypeDetailed", "isHidden",
                            "visibility", "compliance", "Product_status", "ageGroup", "isRepost", "products", "productId",
                            "_seedTag", "repostDetails.originalPostId")},
    "product": {f: 1 for f in ("createdBy", "createdAt", "status", "availability", "categoryPathIds", "basicInfo.categoryId",
                               "crossSellProducts", "deliveryConfig.returnWindow",
                               "deliveryConfig.isReturnApplicable")},
    "user": {f: 1 for f in ("status", "moderation.state", "city", "DOB", "accountIsPublic", "restriction_level", "interest",
                            "timestamp", "createdAt")},
    "business": {f: 1 for f in ("user_id", "category", "status", "accountIsPublic", "restriction_level", "timestamp")},
    "variant": {f: 1 for f in ("productId", "sellerId", "salePrice", "originalPrice", "quantity", "reservedStock", "status")},
}


async def read_newest(settings: Settings, kind: str, limit: int, skip: int = 0) -> list[Any]:
    """Posts or products, newest first, parsed. A serving read: products skip the
    category lookup (no list built here needs a product's category yet)."""
    if kind == "product":
        parse: Callable[[dict[str, Any]], Any] = lambda doc: records.parse_product(doc, _EMPTY_INDEX)  # noqa: E731
    else:
        parse = await _parser(settings, kind)
    cursor = (
        app_db(settings)[PLATFORM_COLLECTIONS[kind]]
        .find({}, _FIELDS[kind])
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


# --- reads for eligibility (ENG-08) -------------------------------------------------------


def _any_form(ids: list[Any]) -> dict[str, list[Any]]:
    """$in over every id in both its text and ObjectId form."""
    forms: list[Any] = []
    for value in ids:
        if value is not None:
            forms.extend(id_match(value)["$in"])
    return {"$in": forms}


async def read_where(settings: Settings, kind: str, field: str, ids: list[Any]) -> list[Any]:
    """Parsed records of `kind` whose `field` is any of `ids` (text or ObjectId).
    Products skip the category lookup, as serving reads do."""
    if not ids:
        return []
    if kind == "product":
        parse: Callable[[dict[str, Any]], Any] = lambda doc: records.parse_product(doc, _EMPTY_INDEX)  # noqa: E731
    else:
        parse = await _parser(settings, kind)
    cursor = app_db(settings)[PLATFORM_COLLECTIONS[kind]].find({field: _any_form(list(ids))}, _FIELDS.get(kind))
    return [parse(doc) async for doc in cursor]


async def read_blocks(settings: Settings, account_ids: list[str]) -> list[records.BlockRecord]:
    """Block rows in followers touching any of these accounts, either side (E-01).
    Read when each list is built, so a block takes effect on the next list."""
    if not account_ids:
        return []
    either = _any_form(account_ids)
    cursor = app_db(settings)[PLATFORM_COLLECTIONS["follower"]].find(
        {"status": {"$regex": r"^\s*blocked\s*$", "$options": "i"}, "$or": [{"follower_id": either}, {"user_id": either}]}
    )
    return [block async for doc in cursor if (block := records.parse_block(doc)) is not None]


# --- the fallback ladder (ENG-09) ---------------------------------------------------------


async def read_user_with(
    settings: Settings, user_id: str, extra: tuple[str, ...] = ()
) -> tuple[records.UserRecord | None, dict[str, Any]]:
    """One user's record (declared interests matched to the 23), plus the raw values of
    `extra` fields the caller names. (None, {}) when there is no such user.

    `extra` is how the ladder reads the old delivered score, a field ENG-03 lets only
    reco/fallback name."""
    if not user_id:
        return None, {}
    projection = {**_FIELDS["user"], **{field: 1 for field in extra}}
    doc = await app_db(settings)[PLATFORM_COLLECTIONS["user"]].find_one({"_id": id_match(user_id)}, projection)
    if doc is None:
        return None, {}
    parse = await _parser(settings, "user")
    return parse(doc), {field: doc.get(field) for field in extra}


async def read_business_follows(settings: Settings, user_id: str, since: Any) -> int:
    """How many businesses the user has followed since `since` (follows with
    followingReference businessRegister; ENG-10's source for business follows)."""
    if not user_id:
        return 0
    follows = await read_records(settings, "follow", {"userId": id_match(user_id)})
    return sum(1 for f in follows if f.followed_kind == "business" and f.created_at and f.created_at >= since)


async def read_post_categories(settings: Settings, post_ids: list[str]) -> dict[str, list[str]]:
    """Each post's categories, matched to the 23 (unmatched ones dropped, ENG-03)."""
    return {post.post_id: post.categories for post in await read_where(settings, "post", "_id", post_ids)}


async def read_posts(settings: Settings, post_ids: list[str]) -> dict[str, records.PostRecord]:
    """The posts, parsed (categories matched to the 23; is_seed for ENG-30 point 9)."""
    return {post.post_id: post for post in await read_where(settings, "post", "_id", post_ids)}


# --- M1 on the engine's copies (ENG-10) ------------------------------------------------------


async def read_product_categories(settings: Settings, product_ids: list[str]) -> dict[str, str | None]:
    """Each product's category, one of the 23 through the category tree, or None (ENG-03)."""
    if not product_ids:
        return {}
    index = await product_categories(settings)
    cursor = app_db(settings)[PLATFORM_COLLECTIONS["product"]].find({"_id": _any_form(product_ids)}, _FIELDS["product"])
    return {p.product_id: p.category async for doc in cursor if (p := records.parse_product(doc, index))}


async def read_business_categories(settings: Settings, business_ids: list[str]) -> dict[str, str | None]:
    """Each business's category (businessregisters.category), matched to the 23 by name, or None."""
    return {b.business_id: b.category for b in await read_where(settings, "business", "_id", business_ids)}


# --- M2 method two (ENG-14) ------------------------------------------------------------------


async def read_posts_since(settings: Settings, since: Any) -> list[records.PostRecord]:
    """Every post created at or after `since` (posts.timestamp, else the _id's time,
    ENG-03), parsed, newest first (ties: post id). ENG-14's nightly pool; the caller
    applies eligibility."""
    from bson import ObjectId

    query = {"$or": [
        {"timestamp": {"$gte": since}},
        {"timestamp": None, "_id": {"$gte": ObjectId.from_datetime(since)}},
    ]}
    parse = await _parser(settings, "post")
    cursor = app_db(settings)[PLATFORM_COLLECTIONS["post"]].find(query, _FIELDS["post"])
    posts = [post async for doc in cursor if (post := parse(doc)).created_at is not None and post.created_at >= since]
    posts.sort(key=lambda p: (-p.created_at.timestamp(), p.post_id))
    return posts


# --- M8 promoter score (ENG-16) --------------------------------------------------------------


async def read_all_blocks(settings: Settings) -> list[records.BlockRecord]:
    """Every block row in followers (status blocked): ENG-16 leaves blocked follows out
    of a promoter's follower count (Kala, 16 Oct)."""
    cursor = app_db(settings)[PLATFORM_COLLECTIONS["follower"]].find(
        {"status": {"$regex": r"^\s*blocked\s*$", "$options": "i"}})
    return [block async for doc in cursor if (block := records.parse_block(doc)) is not None]


async def can_read(settings: Settings, kind: str) -> bool:
    """Whether the engine's login can read one row of this collection (ENG-30 point 7:
    if returnrequests cannot be read at all, M8's commerce components stay off)."""
    from pymongo.errors import PyMongoError

    try:
        await app_db(settings)[PLATFORM_COLLECTIONS[kind]].find_one({}, {"_id": 1})
    except PyMongoError:
        return False
    return True


#: ENG-30 point 4: only these fields of commissionconfigs are read.
COMMISSION_FIELDS = ("scope", "scopeId", "enabled", "poolPercent", "minOrderAmount", "holdDays", "updatedAt")


async def read_commission_configs(settings: Settings) -> list[dict[str, Any]]:
    """Every commissionconfigs row, in full (ENG-30 point 4). A read failure raises."""
    cursor = app_db(settings)[PLATFORM_COLLECTIONS["commission_config"]].find({}, {f: 1 for f in COMMISSION_FIELDS})
    return [doc async for doc in cursor]

