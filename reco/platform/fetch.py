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
