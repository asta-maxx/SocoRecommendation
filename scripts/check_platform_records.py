"""Read every platform record through the ENG-03 rules (Build List v1.3). Read-only. ENG-03 check.

    .venv/bin/python scripts/check_platform_records.py

For each record kind: how many documents were read, how many could not be
parsed (and why), and the facts ENG-03 cares about -- categories mapped to the
23, ids stored as text, times recovered from _id. Prints counts only: no names,
emails or other personal fields.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import PLATFORM_COLLECTIONS, _hosts_of, get_settings, live  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.platform import records  # noqa: E402
from reco.platform.fetch import product_categories  # noqa: E402
from reco.platform.readers import vocabulary  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402

TIME_FIELD = {
    "user": "timestamp", "business": "timestamp", "post": "timestamp", "postevent": "created_at",
    "follow": "createdAt", "order": "created_at", "cart_line": "timestamp", "product": "createdAt",
    "served_list": "server_ts",
}


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    vocab = vocabulary(settings)
    lists = live.current().lists
    failures = 0
    try:
        db = platform_conn.app_db(settings)
        names = set(await db.list_collection_names())
        index = await product_categories(settings)
        print(f"platform {settings.app_mongo_db} on {_hosts_of(settings.app_mongo_uri)[0]} (read-only)\n")
        print(f"{'kind':26}{'read':>6}{'failed':>8}{'time from _id':>15}   notes")
        for kind in records.RECORD_KINDS:
            collection = PLATFORM_COLLECTIONS[kind]
            if collection not in names:
                print(f"{kind:26}{'-':>6}{'-':>8}{'-':>15}   collection '{collection}' does not exist yet")
                continue
            parse = getattr(records, f"parse_{kind}")
            read, errors, from_id, notes = 0, Counter(), 0, Counter()
            async for doc in db[collection].find({}):
                read += 1
                try:
                    if kind in {"user", "business", "post", "category"}:
                        record = parse(doc, vocab, lists.category_map)
                    elif kind == "product":
                        record = parse(doc, index)
                    elif kind == "order":
                        record = parse(doc, lists.order_status)
                    else:
                        record = parse(doc)
                except Exception as exc:  # report, don't stop: this is the check
                    errors[f"{type(exc).__name__}: {str(exc)[:60]}"] += 1
                    continue
                field = TIME_FIELD.get(kind)
                if field and doc.get(field) is None:
                    from_id += 1
                if kind == "post":
                    notes["with a category of the 23"] += bool(record.categories)
                elif kind == "product":
                    notes["category is one of the 23"] += record.category is not None
                elif kind == "category":
                    notes["top level is one of the 23"] += record.top_level is not None
                elif kind == "follow":
                    notes["text ids"] += isinstance(doc.get("userId"), str)
                elif kind == "user":
                    notes["active"] += record.is_active
                elif kind == "order":
                    notes["with checkout_id"] += record.checkout_id is not None
                    notes["with tracking_info"] += bool(record.tracking)
                    notes["returned"] += record.is_returned
                elif kind == "postevent":
                    notes["with an E code"] += record.event_code is not None
                    notes["business actor"] += record.actor == "business"
                    notes["with updated_at"] += record.updated_at is not None
                    notes["page visits"] += record.is_page_visit
                elif kind == "served_list":
                    notes["fallback lists"] += record.is_fallback
                elif kind == "variant":
                    notes["in stock"] += (record.stock or 0) > 0
            failures += sum(errors.values())
            note = ", ".join(f"{k} {v}/{read}" for k, v in notes.items())
            print(f"{kind:26}{read:>6}{sum(errors.values()):>8}{from_id:>15}   {note}")
            for error, count in errors.most_common(3):
                print(f"{'':26}  ! {count} x {error}")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()
    print(f"\n{'PASS' if not failures else 'FAIL'}: {failures} document(s) could not be read")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
