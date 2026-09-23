"""Export the category vocabulary to JSON for the engine to load.

    python scripts/export_categories.py --categories-js path/to/categories.js
    python scripts/export_categories.py            # falls back, see below

The authority is `backend/SOCO_BE/src/constants/categories.js`, which holds
`CANONICAL_CATEGORIES` and `LEGACY_LABEL_MAP`. This exports both so the engine
loads them rather than carrying a retyped copy -- retyping creates a fourth
vocabulary alongside the three that already exist.

WITHOUT categories.js this falls back to `reference/post_picker_categories.txt`,
which carries the canonical 23 and nothing else. The result is marked
`legacy_map_loaded: false`, and the engine says so loudly on every startup:
legacy names are then DROPPED AND COUNTED rather than merged. That is correct per
DS-008 section 3.2 and it is incomplete -- U06 exists to demonstrate a merge, and
no merge can happen until the map arrives.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reco" / "platform" / "categories.json"
FALLBACK_LIST = ROOT / "reference" / "post_picker_categories.txt"


def from_categories_js(path: Path) -> dict:
    """Pull both structures out of the JavaScript source.

    Deliberately narrow: it reads the two array/object literals and nothing else.
    If the file's shape changes this fails loudly rather than exporting half a
    vocabulary.
    """
    text = path.read_text(encoding="utf-8")

    canonical_match = re.search(
        r"CANONICAL_CATEGORIES\s*=\s*\[(.*?)\]", text, re.S
    )
    if not canonical_match:
        raise SystemExit(f"CANONICAL_CATEGORIES not found in {path}")
    canonical = re.findall(r"['\"]([^'\"]+)['\"]", canonical_match.group(1))

    legacy: dict[str, str | None] = {}
    legacy_match = re.search(r"LEGACY_LABEL_MAP\s*=\s*\{(.*?)\n\}", text, re.S)
    if legacy_match:
        for line in legacy_match.group(1).splitlines():
            entry = re.match(
                r"\s*['\"]([^'\"]+)['\"]\s*:\s*(null|['\"]([^'\"]*)['\"])", line
            )
            if entry:
                legacy[entry.group(1)] = None if entry.group(2) == "null" else entry.group(3)

    return {
        "canonical": canonical,
        "legacy_map": legacy,
        "legacy_map_loaded": bool(legacy_match),
        "source": str(path),
    }


def from_fallback_list(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"{path} not found and no --categories-js given.")
    canonical = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return {
        "canonical": [c for c in canonical if c],
        "legacy_map": {},
        "legacy_map_loaded": False,
        "source": f"{path} (canonical only -- LEGACY_LABEL_MAP not available)",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories-js", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.categories_js:
        data = from_categories_js(args.categories_js)
    else:
        data = from_fallback_list(FALLBACK_LIST)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1), encoding="utf-8")

    print(f"{args.out}")
    print(f"  canonical    {len(data['canonical'])}")
    print(f"  legacy_map   {len(data['legacy_map'])}")
    print(f"  source       {data['source']}")
    if not data["legacy_map_loaded"]:
        print()
        print("  WARNING: LEGACY_LABEL_MAP is not in this export.")
        print("  Legacy names will be DROPPED AND COUNTED, not merged.")
        print("  U06 demonstrates a merge and cannot until categories.js arrives.")
        sys.exit(0)


if __name__ == "__main__":
    main()
