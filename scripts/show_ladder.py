"""Walk the fallback ladder (ENG-09) for users and show which rung served each.

    python scripts/show_ladder.py                    # 20 platform users, and a count per rung
    python scripts/show_ladder.py --sample 200       # more users
    python scripts/show_ladder.py <user id> ...      # named users, in detail

Reads only: the user's score and qualified actions from the engine's copies, the
user's declared interests and old delivered score from the platform, and the
current popularity batch. Prints ids and category names, nothing personal.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.config import live, sync  # noqa: E402
from reco.fallback.read_path import count_qualified_actions, get_profile  # noqa: E402
from reco.store.writers import read_user_scores  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.platform import fetch  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.scores import Method  # noqa: E402


def show(user_id: str, p) -> None:
    print(f"{user_id}  RUNG {int(p.rung)}  step {p.fallback_step or '-'}"
          f"{'  (cold start)' if p.cold_start else ''}")
    print(f"        {p.rung_description}"
          + (f"  (fell through from rung {int(p.fell_through_from)})" if p.fell_through_from else ""))
    if not p.categories:
        print("        (no categories: the list is eligible posts newest first)")
    for c in p.top(5):
        raw = f"  raw {c.raw:8.2f}" if c.raw is not None else ""
        n = f"  n={c.event_count}" if c.event_count is not None else ""
        print(f"          {c.category:<28} {c.share:6.3f}{raw}{n}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("users", nargs="*")
    parser.add_argument("--sample", type=int, default=20, help="platform users to walk when none are named")
    parser.add_argument("--method", default=Method.RECENCY_DECAY.value)
    parser.add_argument("--all", action="store_true", help="walk every platform user (review of 26 Oct, point 6)")
    args = parser.parse_args()

    settings = get_settings()
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    await sync.load_at_start(settings)
    interest = live.current().interest
    print(f"engine db {settings.ml_mongo_db}   method {args.method}")
    print(f"rung 1 needs {interest.personal_min_actions} qualified actions in {interest.personal_window_days} days "
          f"and a score under {interest.stale_after_hours:g} h; popularity over {interest.popularity_window_days} days")
    print()
    try:
        users = args.users or [u.user_id for u in await fetch.read_records(
            settings, "user", limit=None if args.all else args.sample)]
        steps: Counter[str] = Counter()
        enough = fresh = 0
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        for user_id in users:
            p = await get_profile(settings, user_id, method=Method(args.method))
            steps[p.fallback_step or "rung_1"] += 1
            # Review of 26 Oct, point 6: the two inputs of rung 1, counted separately.
            enough += await count_qualified_actions(settings, user_id, now) >= interest.personal_min_actions
            scores = await read_user_scores(settings, user_id, Method(args.method))
            newest = max((s.computed_at for s in scores if s.computed_at), default=None)
            if newest is not None and newest.tzinfo is None:
                newest = newest.replace(tzinfo=timezone.utc)
            fresh += newest is not None and now - newest < timedelta(hours=interest.stale_after_hours)
            if args.users:
                show(user_id, p)
                print()
        print(f"{len(users)} users by step: " + ", ".join(f"{k} {v}" for k, v in sorted(steps.items())))
        print(f"users with {interest.personal_min_actions} or more qualified actions in {interest.personal_window_days} "
              f"days: {enough}")
        print(f"users with a score under {interest.stale_after_hours:g} hours old ({args.method}): {fresh}")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()


if __name__ == "__main__":
    asyncio.run(main())
