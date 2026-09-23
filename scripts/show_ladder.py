"""Walk the fallback ladder for a user and show which rung served them.

    python scripts/show_ladder.py                 # the demo users that matter
    python scripts/show_ladder.py U07 U11 U04     # named users

U07 is rung 2 -- declared interests, no activity. U11 is rung 3 -- neither.
They are different code paths, which is why both are demonstrated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.config import live, sync  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.scores import Method  # noqa: E402
from reco.fallback.read_path import get_profile  # noqa: E402

META = ROOT / "reference" / "demo" / "ml_demo_meta.json"
DEFAULT_USERS = ["U01", "U04", "U07", "U11", "U20"]


def dataset_reference_date() -> datetime | None:
    if not META.exists():
        return None
    return datetime.fromisoformat(
        json.loads(META.read_text(encoding="utf-8"))["reference_date"]
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("users", nargs="*", default=DEFAULT_USERS)
    parser.add_argument("--method", default=Method.RECENCY_DECAY.value)
    parser.add_argument(
        "--now",
        action="store_true",
        help="use the clock instead of the dataset's reference date",
    )
    args = parser.parse_args()

    settings = get_settings()
    reference = None if args.now else dataset_reference_date()

    print(f"profile   {settings.data_profile}")
    print(f"reading   {settings.scores_collection}")
    print(f"anchored  {reference or 'now'}")
    print()

    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    await sync.load_at_start(settings)
    interest = live.current().interest
    print(f"stale     {interest.stale_after_hours}h   "
          f"popularity window {interest.popularity_window_days}d")
    try:
        for user_id in (args.users or DEFAULT_USERS):
            p = await get_profile(
                settings, user_id, method=Method(args.method), reference_date=reference
            )

            label = f"RUNG {int(p.rung)}"
            personal = "personalised" if p.personalised else "NOT personalised"
            through = (
                f"  (fell through from rung {int(p.fell_through_from)})"
                if p.fell_through_from
                else ""
            )
            stamp = f"{p.method or '-'} v{p.model_version}"

            print(f"{user_id}   {label}  {p.rung_description}{through}")
            print(f"        {personal} · stamp {stamp}")
            if p.popularity_window_days:
                print(f"        popularity over the last {p.popularity_window_days} days")
            if not p.categories:
                print("        (no categories)")
            for c in p.top(5):
                raw = f"  raw {c.raw:8.2f}" if c.raw is not None else ""
                n = f"  n={c.event_count}" if c.event_count is not None else ""
                print(f"          {c.category:<28} {c.share:6.3f}{raw}{n}")
            print()
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()


if __name__ == "__main__":
    asyncio.run(main())
