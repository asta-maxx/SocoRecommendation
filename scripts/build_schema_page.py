"""Build the collection map page from a live introspection of the database.

    python scripts/build_schema_page.py

Runs the introspection, injects the result into the page template, and writes
docs/schema.html. Field names and BSON types only -- no document values -- so the
page is safe to share.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "scripts" / "schema_page_template.html"
OUTPUT = ROOT / "docs" / "schema.html"
PLACEHOLDER = "/*__SCHEMA__*/"


def main() -> None:
    print("Reading the database…", file=sys.stderr)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "introspect_db.py")],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit("Introspection failed.")

    schema = json.loads(result.stdout)

    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE.name} has no {PLACEHOLDER} placeholder.")

    # </script> inside embedded JSON would close the surrounding tag early.
    payload = json.dumps(schema, separators=(",", ":")).replace("</", "<\\/")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(template.replace(PLACEHOLDER, payload), encoding="utf-8")

    print(
        f"{OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB, "
        f"{schema['collection_count']} collections)"
    )


if __name__ == "__main__":
    main()
