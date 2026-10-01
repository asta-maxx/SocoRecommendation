"""Which eligibility rules (E-01 to E-12) leave what out, on SOCO's real data. ENG-08. Read-only.

    .venv/bin/python scripts/show_exclusions.py                    # as a made-up viewer
    .venv/bin/python scripts/show_exclusions.py <user id>          # as a real user

Builds the first feed page and the first product page the way the engine does
(newest first, every rule applied) without serving or recording anything, and
counts the exclusions per rule from the eligibility log. Prints counts and rule
names only -- no ids.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.eligibility.rules import RULES  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.ranking import serving  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402

VIEWER = "64f1c0ffee0000000000abcd"


class Count(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.rules: Counter = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "rule", None):
            self.rules[(record.item_type, record.rule)] += 1


async def main(user_id: str) -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    counter = Count()
    log = logging.getLogger("reco.eligibility")
    log.addHandler(counter)
    log.setLevel(logging.INFO)
    try:
        for surface in ("feed", "product"):
            built = await serving.interim_candidates(settings, surface, 1, 10, None, user_id, "show-exclusions")
            print(f"{surface}: {len(built.candidates)} eligible of {built.rows_read} read")
        print("left out, by rule:")
        for (item_type, rule), n in sorted(counter.rules.items(), key=lambda x: (x[0][1], x[0][0])):
            print(f"  {rule}  {item_type:8} {n:5}  {RULES[rule]}")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else VIEWER)))
