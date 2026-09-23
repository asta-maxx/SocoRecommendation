"""Export the service contract as JSON Schema for SOCO_BE. RE-00d.

    python scripts/export_contract_schema.py

SOCO_BE is Node and cannot import `reco.domain.service_contract`, so it validates
against this file instead. The Python models are the authority; the schema is
generated from them, never edited by hand. `test_service_contract.py` fails if the
checked-in file no longer matches the models, so a field renamed here cannot ship
without the file the backend reads changing with it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.domain.service_contract import json_schema  # noqa: E402

OUT = ROOT / "docs" / "service_contract.schema.json"


def render() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
