"""Map the SOCO database: collections, fields, types, indexes.

Reads with the read-only credential and writes a JSON description to stdout or a
file. Field NAMES and TYPES only -- no document values are ever recorded, so the
output carries no personal data and is safe to share.

    python scripts/introspect_db.py > schema.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from pathlib import Path

from bson import ObjectId
from pymongo import MongoClient

# Run as `python scripts/introspect_db.py` from the project root: sys.path[0] is
# then scripts/, so the package needs putting on the path explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reco.config import get_settings  # noqa: E402

SAMPLE = 40
MAX_DEPTH = 2


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, ObjectId):
        return "ObjectId"
    if isinstance(value, datetime):
        return "date"
    if isinstance(value, float):
        return "double"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        inner = {type_name(v) for v in value[:5]}
        return f"array<{'|'.join(sorted(inner))}>" if inner else "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def walk(document: dict, prefix: str, depth: int, out: dict) -> None:
    for key, value in document.items():
        path = f"{prefix}{key}"
        out[path].append(type_name(value))
        if isinstance(value, dict) and depth < MAX_DEPTH:
            walk(value, f"{path}.", depth + 1, out)
        elif isinstance(value, list) and value and isinstance(value[0], dict) and depth < MAX_DEPTH:
            walk(value[0], f"{path}[].", depth + 1, out)


def describe(collection) -> dict:
    total = collection.estimated_document_count()
    seen: dict[str, list[str]] = defaultdict(list)

    sampled = 0
    for document in collection.find().limit(SAMPLE):
        sampled += 1
        walk(document, "", 0, seen)

    fields = []
    for path, types in sorted(seen.items()):
        counts = Counter(t for t in types if t != "null")
        fields.append(
            {
                "name": path,
                "types": [t for t, _ in counts.most_common()] or ["null"],
                "presence": round(len(types) / sampled, 3) if sampled else 0,
            }
        )

    indexes = []
    try:
        for name, spec in collection.index_information().items():
            indexes.append(
                {
                    "name": name,
                    "key": [[k, v] for k, v in spec.get("key", [])],
                    "unique": bool(spec.get("unique", False)),
                }
            )
    except Exception:
        pass

    return {
        "name": collection.name,
        "count": total,
        "sampled": sampled,
        "fields": fields,
        "indexes": indexes,
    }


def main() -> None:
    settings = get_settings()
    client = MongoClient(settings.app_mongo_uri, serverSelectionTimeoutMS=15000)
    db = client[settings.app_mongo_db]

    collections = sorted(db.list_collection_names())
    result = {
        "database": settings.app_mongo_db,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "collection_count": len(collections),
        "sample_size": SAMPLE,
        "collections": [],
    }

    for name in collections:
        print(f"  {name}", file=sys.stderr)
        result["collections"].append(describe(db[name]))

    json.dump(result, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
