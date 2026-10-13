"""Platform popularity for rung 3 of the ladder, computed nightly. ENG-09, ENG-07.

    await compute_popularity(settings, now, job_run_id)   -> rows written

Rung 3 serves "platform-wide category popularity over the last 30 days
(qualified views per category)". Counting that on every request would read the
whole activity copy each time, and a request never calculates (SD-17), so it is
a nightly batch like every other score: written whole, then made current
(reco.jobs.batches); a request reads only the current batch.

Counted from the engine's copy of postevents (ENG-04): one qualified view per
viewer per post (ENG-10), in the window, test accounts left out (ENG-29 item 3).
A post counts towards each of its categories that is one of the 23 (ENG-03).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from reco.config import Settings, live
from reco.config.accounts import test_account_ids
from reco.platform import fetch
from reco.store import writers

#: Posts read per platform query while resolving categories.
_POST_BATCH = 500


def data_window(now: datetime) -> dict[str, datetime | None]:
    return {"from": now - timedelta(days=live.current().interest.popularity_window_days), "to": now}


async def count_by_category(settings: Settings, now: datetime) -> tuple[Counter[str], dict[str, int]]:
    """Qualified views per category over the window, and what was left out."""
    tunables = live.current()
    since = data_window(now)["from"]
    pairs = await writers.read_qualified_views(settings, since, tunables.events.qualified_view_seconds * 1000)
    tests = test_account_ids()
    kept = [p for p in pairs if str(p.get("user_id") or "").lower() not in tests]
    post_ids = sorted({p["post_id"] for p in kept})
    categories: dict[str, list[str]] = {}
    for start in range(0, len(post_ids), _POST_BATCH):
        categories |= await fetch.read_post_categories(settings, post_ids[start:start + _POST_BATCH])
    counts: Counter[str] = Counter()
    uncategorised = 0
    for pair in kept:
        found = categories.get(pair["post_id"]) or []
        uncategorised += not found
        counts.update(found)
    return counts, {"views": len(pairs), "test_account_views": len(pairs) - len(kept), "uncategorised_views": uncategorised}


async def compute_popularity(settings: Settings, now: datetime, job_run_id: str) -> tuple[int, dict[str, int]]:
    """Write one batch of popularity rows, one per category with any qualified view."""
    counts, detail = await count_by_category(settings, now)
    window = data_window(now)
    stamp: dict[str, Any] = {
        "measure": writers.POPULARITY_MEASURE,
        "method": writers.POPULARITY_METHOD,
        "slot": "interest",
        "job_run_id": job_run_id,
        "window_days": live.current().interest.popularity_window_days,
        "data_window": window,
        "computed_at": now,
        "config_version": live.current().config_version,
        "model_version": settings.model_version,
    }
    rows = [{**stamp, "category": category, "qualified_views": n} for category, n in counts.most_common()]
    return await writers.write_popularity(settings, rows), detail
