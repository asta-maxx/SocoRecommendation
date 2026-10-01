"""The engine sync: backfill, incremental reads, checkpoints and the lag alert. ENG-04 items 1-4, 7.

    await sync_once(settings)      one pass over every source (backfill first if unfinished)
    await check_lag(settings)      the lag alert, on its own
    await sync_forever(settings)   a pass every sync_interval_minutes (a setting)

Per source collection, ml_sync_state holds (its _id is the collection name):

    backfill       {done, started_at, finished_at, after_id, copied}: restartable
                   in _id order; after_id is saved after each page is written
    checkpoint     the latest updated_at written; the next read starts
                   sync_overlap_minutes before it
    current_as_of  when the last successful pass started: every row changed
                   before then has been copied. Lag = now - current_as_of
    last_run       {started_at, finished_at, outcome, copied, error}

A checkpoint is saved only after the page it covers is written (item 4), so a
failure in between re-reads that page; the copies are upserts keyed on the
platform _id, so a re-read never duplicates (items 1, 3).

Reads go through reco.platform.fetch; writes through reco.store.writers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from reco.config import Settings, live
from reco.config import sync as config_sync
from reco.monitoring.alerts import alert
from reco.platform import fetch
from reco.store import writers
from reco.store.scores import utc_now
from reco.sync.copies import SYNC_SOURCES, SyncSource, make_copy, with_history

logger = logging.getLogger("reco.sync")

#: Rows per read. The pack sets no page size; this keeps one page well inside a
#: single bulk write.
PAGE_SIZE = 500

_EARLIEST = datetime(1970, 1, 1, tzinfo=timezone.utc)


async def write_page(settings: Settings, source: SyncSource, docs: list[dict[str, Any]], now: datetime) -> int:
    """Copy one page of platform rows (upsert on _id). Orders carry their status history forward."""
    statuses = live.current().lists.order_status
    copies = [make_copy(source, doc, statuses) for doc in docs]
    if source.kind == "order":
        held = await writers.read_copies(settings, source.target, [c["_id"] for c in copies])
        copies = [with_history(c, held.get(c["_id"])) for c in copies]
    return await writers.upsert_copies(settings, source.target, copies, now)


async def backfill(settings: Settings, source: SyncSource) -> int:
    """Item 1: copy everything the platform holds, in _id order. Restarts where it stopped."""
    state = await writers.read_sync_state(settings, source.collection)
    done = state.get("backfill") or {}
    if done.get("done"):
        return 0
    started = done.get("started_at") or utc_now()
    after, copied = done.get("after_id"), done.get("copied", 0)
    if not done:
        await writers.write_sync_state(
            settings, source.collection,
            {"backfill": {"done": False, "started_at": started, "after_id": None, "copied": 0}},
        )
    while docs := await fetch.read_page_by_id(settings, source.kind, after, PAGE_SIZE):
        copied += await write_page(settings, source, docs, utc_now())
        after = docs[-1]["_id"]
        await writers.write_sync_state(settings, source.collection, {"backfill.after_id": after, "backfill.copied": copied})
    finished = {"backfill.done": True, "backfill.finished_at": utc_now()}
    if state.get("checkpoint") is None:
        # The incremental read starts from when the backfill started, so a row
        # changed while the backfill ran is read again.
        finished["checkpoint"] = started
    await writers.write_sync_state(settings, source.collection, finished)
    logger.info("backfill finished", extra={"source": source.collection, "copied": copied})
    return copied


async def incremental(settings: Settings, source: SyncSource) -> int:
    """Items 2-4: rows with updated_at from (checkpoint - overlap), in (updated_at, _id)
    order with keyset paging; the checkpoint moves after each page is written."""
    state = await writers.read_sync_state(settings, source.collection)
    checkpoint: datetime | None = state.get("checkpoint")
    overlap = timedelta(minutes=live.current().events.sync_overlap_minutes)
    since = checkpoint - overlap if checkpoint else _EARLIEST
    position, copied = None, 0
    while docs := await fetch.read_page_by_updated_at(settings, source.kind, since, position, PAGE_SIZE):
        copied += await write_page(settings, source, docs, utc_now())
        last = docs[-1]
        position = (last["updated_at"], last["_id"])
        if checkpoint is None or last["updated_at"] > checkpoint:
            checkpoint = last["updated_at"]
            await writers.write_sync_state(settings, source.collection, {"checkpoint": checkpoint})
    return copied


async def sync_source(settings: Settings, source: SyncSource) -> int:
    started = utc_now()
    try:
        copied = await backfill(settings, source)
        copied += await incremental(settings, source)
    except Exception as exc:
        await writers.write_sync_state(settings, source.collection, {"last_run": {
            "started_at": started, "finished_at": utc_now(), "outcome": "failed", "error": repr(exc)[:500],
        }})
        alert("sync_failed", "engine sync failed; restart from the last checkpoint",
              source=source.collection, error=repr(exc)[:500])
        raise
    await writers.write_sync_state(settings, source.collection, {
        "current_as_of": started,
        "last_run": {"started_at": started, "finished_at": utc_now(), "outcome": "succeeded", "copied": copied},
    })
    logger.info("sync pass", extra={"source": source.collection, "copied": copied})
    return copied


async def sync_once(settings: Settings) -> dict[str, int]:
    """One pass over every source. One source failing doesn't stop the others; the pass
    still fails at the end, so the job exits non-zero."""
    copied: dict[str, int] = {}
    failed: list[str] = []
    for source in SYNC_SOURCES:
        try:
            copied[source.collection] = await sync_source(settings, source)
        except Exception:
            logger.exception("sync failed", extra={"source": source.collection})
            failed.append(source.collection)
    await check_lag(settings)
    if failed:
        raise RuntimeError(f"engine sync failed for {', '.join(failed)}")
    return copied


async def check_lag(settings: Settings, now: datetime | None = None) -> list[dict[str, Any]]:
    """Item 7: alert when a source is more than sync_lag_alert_minutes behind, or its
    last run failed. Returns each source's status."""
    now = now or utc_now()
    limit = live.current().events.sync_lag_alert_minutes
    held = {state["_id"]: state for state in await writers.read_all_sync_state(settings)}
    statuses = []
    for source in SYNC_SOURCES:
        state = held.get(source.collection, {})
        as_of = state.get("current_as_of")
        lag = round((now - as_of).total_seconds() / 60, 1) if as_of else None
        outcome = (state.get("last_run") or {}).get("outcome")
        status = {"source": source.collection, "lag_minutes": lag, "last_outcome": outcome,
                  "alert": (lag is None and bool(state)) or (lag is not None and lag > limit) or outcome == "failed"}
        if status["alert"]:
            alert("sync_lag", "engine sync is behind or its last run failed; restart from the last checkpoint",
                  source=source.collection, lag_minutes=lag, limit_minutes=limit, last_outcome=outcome)
        statuses.append(status)
    return statuses


async def sync_forever(settings: Settings) -> None:
    """A pass every sync_interval_minutes. Settings are re-read before each pass, so a
    changed interval takes effect with no restart."""
    while True:
        await config_sync.reload(settings)
        try:
            await sync_once(settings)
        except Exception:
            pass  # already alerted and logged; the next pass restarts from the checkpoints
        await asyncio.sleep(live.current().events.sync_interval_minutes * 60)
