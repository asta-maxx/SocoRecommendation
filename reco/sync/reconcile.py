"""The daily reconciliation of the engine copies. ENG-04 item 8, DB-16 step 4.

    await reconcile_day(settings)            the previous day (IST)
    await reconcile_day(settings, day)       a given day, "YYYY-MM-DD"

Per source collection, for the day's rows (created or changed that day):

    ids       the platform's set and the engine's set must match
    fields    for rows on both sides, the compared fields (SYNC_SOURCES) must
              match the platform row exactly

Equal counts alone do not pass. Every mismatch is logged and re-read from the
platform (copied again). One result per source per day goes into
ml_measurements; DB-16 needs it passed on 7 days in a row before the old
collections are dropped.

The pack doesn't say which day boundary; the jobs run on IST (2 AM IST, ENG-07),
so the day is the IST day.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from reco.config import Settings
from reco.platform import fetch
from reco.store import writers
from reco.store.scores import utc_now
from reco.sync.copies import SYNC_SOURCES, SyncSource
from reco.sync.run import write_page

logger = logging.getLogger("reco.sync")

IST = timezone(timedelta(hours=5, minutes=30))

#: How many ids a result lists per kind of mismatch; the counts are always whole.
LISTED = 50


def day_bounds(day: str | None = None, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """(day, start, end) in UTC for an IST day; by default the day before `now`."""
    if day is None:
        day = ((now or utc_now()).astimezone(IST).date() - timedelta(days=1)).isoformat()
    start = datetime.combine(date.fromisoformat(day), time(0), tzinfo=IST)
    return day, start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _differences(source: SyncSource, platform: dict[str, Any], held: dict[str, Any]) -> list[str]:
    kept = held.get("platform") or {}
    return [field for field in source.compared if platform.get(field) != kept.get(field)]


async def reconcile_source(settings: Settings, source: SyncSource, day: str, start: datetime, end: datetime) -> dict[str, Any]:
    on_platform = {doc["_id"]: doc for doc in await fetch.read_touched(settings, source.kind, source.time_fields, start, end)}
    touched = {doc["_id"] for doc in await writers.read_copies_touched(settings, source.target, source.collection, start, end)}
    held = await writers.read_copies(settings, source.target, list(on_platform))

    missing = [i for i in on_platform if i not in held]
    mismatched = {i: diff for i, doc in on_platform.items() if i in held and (diff := _differences(source, doc, held[i]))}
    extra = [i for i in touched if i not in on_platform]

    # Re-read everything that didn't match. An extra id the platform still holds
    # changed after the day (a stale copy); one it no longer holds was deleted
    # there (ENG-28 handles deletions) and is only reported.
    reread_docs = [on_platform[i] for i in missing + list(mismatched)]
    still_there = await fetch.read_by_ids(settings, source.kind, extra) if extra else []
    reread_docs += still_there
    reread = await write_page(settings, source, reread_docs, utc_now()) if reread_docs else 0

    result = {
        "source": source.collection,
        "day": day,
        "checked_at": utc_now(),
        "platform_ids": len(on_platform),
        "engine_ids": len(touched | set(held)),
        "missing": len(missing),
        "mismatched": len(mismatched),
        "extra": len(extra),
        "extra_not_on_platform": len(extra) - len(still_there),
        "reread": reread,
        "passed": not (missing or mismatched or extra),
        "missing_ids": [str(i) for i in missing[:LISTED]],
        "mismatched_fields": {str(i): diff for i, diff in list(mismatched.items())[:LISTED]},
        "extra_ids": [str(i) for i in extra[:LISTED]],
    }
    await writers.record_sync_reconciliation(settings, result)
    level = logging.INFO if result["passed"] else logging.WARNING
    logger.log(level, "sync reconciliation", extra={k: v for k, v in result.items() if not k.endswith(("_ids", "_fields"))})
    return result


async def reconcile_day(settings: Settings, day: str | None = None) -> list[dict[str, Any]]:
    day, start, end = day_bounds(day)
    return [await reconcile_source(settings, source, day, start, end) for source in SYNC_SOURCES]
