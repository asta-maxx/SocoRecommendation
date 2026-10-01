"""ENG-04: the engine sync, on constructed platform-shaped data.

The Build List's checks, each a test here:

    (a) the reconciliation shows matching ids and field values   test_reconciliation_*
    (b) a like undone after it was copied updates the copy        test_an_undo_updates_the_existing_copy
    (c) stopped for an hour, restarted: nothing lost or doubled   test_an_hour_stopped_loses_and_duplicates_nothing
    (d) same updated_at across a page boundary: both copied       test_same_updated_at_across_a_page_boundary
    (e) a failure before the checkpoint re-reads that batch       test_a_failure_before_the_checkpoint_rereads_the_batch
    (f) the alert fires in a test outage                          test_the_alert_fires_*
    (g) the retention setting is shown                            test_retention_is_the_setting

The platform side is the throwaway reco_test_platform database; the tests write
it directly, as the platform would.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
import pytest_asyncio
from bson import ObjectId

from reco.config import PLATFORM_COLLECTIONS, live
from reco.config.tunables import OrderStatusValues
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.store import writers
from reco.store.scores import utc_now
from reco.sync import reconcile, run
from reco.sync.copies import SYNC_SOURCES, make_copy, source_named, with_history

POSTEVENTS = PLATFORM_COLLECTIONS["postevent"]
ORDERS = PLATFORM_COLLECTIONS["order"]
SERVED = PLATFORM_COLLECTIONS["served_list"]
ENGINE = ("ml_events", "ml_orders", "ml_sync_state", "ml_measurements", "ml_job_runs")


def postevent(event_type: str = "like", **fields) -> dict:
    now = utc_now()
    return {
        "_id": ObjectId(), "event_type": event_type, "event_id": f"ev_{ObjectId()}",
        "user_id": ObjectId(), "user_model": "users", "post_id": ObjectId(), "item_type": "post",
        "surface": "home_for_you", "created_at": now, "updated_at": now, **fields,
    }


def order(status: str = "Placed", **fields) -> dict:
    now = utc_now()
    return {
        "_id": ObjectId(), "user_id": ObjectId(), "userModel": "users", "product_id": ObjectId(),
        "order_status": status, "tracking_info": [{"status": status, "timestamp": now}],
        "total_price": 499, "created_at": now, "updated_at": now, **fields,
    }


def served_list(**fields) -> dict:
    now = utc_now()
    return {
        "_id": ObjectId(), "request_id": f"req_{ObjectId()}", "user_id": ObjectId(),
        "surface": "home_for_you", "policy_id": "fallback.recent", "candidate_ids": [ObjectId()],
        "seen_ids": [], "server_ts": now, "updated_at": now, **fields,
    }


# --- copies (no database) ---------------------------------------------------------------


def test_a_copy_keeps_the_source_fields_and_the_e_code() -> None:
    doc = postevent("unlike", undo_of="ev_1", undone_at=None)
    copy = make_copy(source_named(POSTEVENTS), doc, OrderStatusValues())
    assert copy["_id"] == doc["_id"]
    assert copy["source"] == POSTEVENTS and copy["source_id"] == str(doc["_id"])
    assert copy["event_id"] == doc["event_id"] and copy["undo_of"] == "ev_1"
    assert copy["event_code"] == "E9" and copy["surface"] == "feed"
    assert copy["created_at"] is not None and copy["updated_at"] is not None
    assert copy["platform"]["event_type"] == "unlike" and "_id" not in copy["platform"]


def test_a_served_list_copy_is_an_e1_with_its_seen_ids() -> None:
    seen = ObjectId()
    copy = make_copy(source_named(SERVED), served_list(seen_ids=[seen]), OrderStatusValues())
    assert copy["event_code"] == "E1" and copy["is_fallback"] and copy["seen_ids"] == [str(seen)]


def test_status_history_adds_only_a_new_status() -> None:
    first = with_history({"status": "Placed", "updated_at": utc_now()}, None)
    same = with_history({"status": "Placed", "updated_at": utc_now()}, first)
    later = with_history({"status": "Delivered", "updated_at": utc_now()}, same)
    assert [h["status"] for h in later["status_history"]] == ["Placed", "Delivered"]


def test_the_sync_reads_the_four_sources() -> None:
    assert [s.collection for s in SYNC_SOURCES] == [POSTEVENTS, ORDERS, SERVED, "rec_serve_log"]


def test_retention_is_the_setting() -> None:
    """(g) At least 365 days from the original event time (the index is in test_engine_environment)."""
    assert live.current().events.retention_days >= 365


# --- against a database -----------------------------------------------------------------


@pytest_asyncio.fixture
async def synced(settings):
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    platform = platform_conn.app_db(settings)
    engine = store_conn.ml_db(settings)

    async def clear() -> None:
        for name in (POSTEVENTS, ORDERS, SERVED, "rec_serve_log"):
            await platform[name].drop()
        for name in ENGINE:
            await engine[name].drop()

    await clear()
    await writers.ensure_engine_collections(settings)
    try:
        yield settings, platform, engine
    finally:
        await clear()
        await platform_conn.close_client()
        await store_conn.close_client()


@pytest.mark.mongo
async def test_the_backfill_copies_everything_keyed_on_the_platform_id(synced) -> None:
    settings, platform, engine = synced
    events = [postevent() for _ in range(3)]
    await platform[POSTEVENTS].insert_many(events)
    await platform[ORDERS].insert_many([order(), order()])
    await platform[SERVED].insert_one(served_list())

    copied = await run.sync_once(settings)

    assert copied[POSTEVENTS] >= 3 and copied[ORDERS] >= 2 and copied[SERVED] >= 1
    assert await engine["ml_events"].count_documents({}) == 4
    assert await engine["ml_orders"].count_documents({}) == 2
    assert {d["_id"] for d in await engine["ml_events"].find({"source": POSTEVENTS}).to_list(None)} == {e["_id"] for e in events}
    state = await writers.read_sync_state(settings, POSTEVENTS)
    assert state["backfill"]["done"] and state["checkpoint"] is not None

    await run.sync_once(settings)  # restartable: a second pass duplicates nothing
    assert await engine["ml_events"].count_documents({}) == 4


@pytest.mark.mongo
async def test_the_backfill_restarts_where_it_stopped(synced, monkeypatch) -> None:
    settings, platform, engine = synced
    monkeypatch.setattr(run, "PAGE_SIZE", 2)
    events = sorted((postevent() for _ in range(5)), key=lambda e: e["_id"])
    await platform[POSTEVENTS].insert_many(events)
    # A backfill that stopped after its first page.
    await writers.write_sync_state(settings, POSTEVENTS, {"backfill": {
        "done": False, "started_at": utc_now(), "after_id": events[1]["_id"], "copied": 2}})

    copied = await run.backfill(settings, source_named(POSTEVENTS))

    assert copied == 5  # 2 before the stop + the 3 after it
    assert await engine["ml_events"].count_documents({}) == 3  # only the rest was read


@pytest.mark.mongo
async def test_an_undo_updates_the_existing_copy(synced) -> None:
    """(b)"""
    settings, platform, engine = synced
    like = postevent("like")
    await platform[POSTEVENTS].insert_one(like)
    await run.sync_once(settings)
    before = await engine["ml_events"].find_one({"_id": like["_id"]})

    undone = utc_now()
    await platform[POSTEVENTS].update_one({"_id": like["_id"]}, {"$set": {"undone_at": undone, "updated_at": undone}})
    await run.sync_once(settings)

    after = await engine["ml_events"].find_one({"_id": like["_id"]})
    assert await engine["ml_events"].count_documents({}) == 1
    assert after["undone_at"] is not None
    assert after["created_at"] == before["created_at"]  # the original time never resets
    assert after["first_copied_at"] == before["first_copied_at"]


@pytest.mark.mongo
async def test_an_order_keeps_its_status_history(synced) -> None:
    settings, platform, engine = synced
    placed = order("Placed")
    await platform[ORDERS].insert_one(placed)
    await run.sync_once(settings)
    for status in ("Delivered", "Return Requested"):
        now = utc_now()
        await platform[ORDERS].update_one({"_id": placed["_id"]}, {"$set": {"order_status": status, "updated_at": now}})
        await run.sync_once(settings)

    copy = await engine["ml_orders"].find_one({"_id": placed["_id"]})
    assert [h["status"] for h in copy["status_history"]] == ["Placed", "Delivered", "Return Requested"]
    assert copy["is_returned"]


@pytest.mark.mongo
async def test_an_hour_stopped_loses_and_duplicates_nothing(synced) -> None:
    """(c) Rows changed through an hour the sync was stopped are all read on restart."""
    settings, platform, engine = synced
    await platform[POSTEVENTS].insert_one(postevent())
    await run.sync_once(settings)
    hour_ago = utc_now() - timedelta(hours=1)
    await writers.write_sync_state(settings, POSTEVENTS, {"checkpoint": hour_ago, "current_as_of": hour_ago})
    during = [postevent(updated_at=hour_ago + timedelta(minutes=m)) for m in range(0, 60, 6)]
    await platform[POSTEVENTS].insert_many(during)

    await run.sync_once(settings)

    assert await engine["ml_events"].count_documents({}) == 11
    assert len(await engine["ml_events"].distinct("_id")) == 11


@pytest.mark.mongo
async def test_same_updated_at_across_a_page_boundary(synced, monkeypatch) -> None:
    """(d)"""
    settings, platform, engine = synced
    await run.sync_once(settings)  # backfill of nothing: the incremental read takes over
    monkeypatch.setattr(run, "PAGE_SIZE", 2)
    same = utc_now()
    await platform[POSTEVENTS].insert_many([postevent(updated_at=same) for _ in range(5)])

    copied = await run.incremental(settings, source_named(POSTEVENTS))

    assert copied == 5
    assert await engine["ml_events"].count_documents({}) == 5


@pytest.mark.mongo
async def test_a_failure_before_the_checkpoint_rereads_the_batch(synced, monkeypatch) -> None:
    """(e) The copies were written but the checkpoint wasn't saved: the next run reads them again."""
    settings, platform, engine = synced
    await run.sync_once(settings)
    held = (await writers.read_sync_state(settings, POSTEVENTS))["checkpoint"]
    rows = [postevent(updated_at=utc_now() + timedelta(minutes=5)) for _ in range(3)]
    await platform[POSTEVENTS].insert_many(rows)

    save = writers.write_sync_state

    async def fail_on_checkpoint(settings, source, fields):
        if "checkpoint" in fields:
            raise RuntimeError("stopped before the checkpoint")
        await save(settings, source, fields)

    monkeypatch.setattr(writers, "write_sync_state", fail_on_checkpoint)
    with pytest.raises(RuntimeError):
        await run.sync_source(settings, source_named(POSTEVENTS))
    monkeypatch.setattr(writers, "write_sync_state", save)
    assert (await writers.read_sync_state(settings, POSTEVENTS))["checkpoint"] == held

    copied = await run.incremental(settings, source_named(POSTEVENTS))

    assert copied >= 3  # the batch was read again
    assert await engine["ml_events"].count_documents({}) == 3  # and not duplicated


@pytest.mark.mongo
async def test_the_alert_fires_when_the_sync_is_behind(synced, caplog) -> None:
    """(f)"""
    settings, _, _ = synced
    await run.sync_once(settings)
    late = utc_now() - timedelta(minutes=16)
    await writers.write_sync_state(settings, ORDERS, {"current_as_of": late})

    with caplog.at_level(logging.CRITICAL, logger="reco.alert"):
        statuses = await run.check_lag(settings)

    assert [s["source"] for s in statuses if s["alert"]] == [ORDERS]
    assert any(getattr(r, "alert", False) and r.source == ORDERS for r in caplog.records)


@pytest.mark.mongo
async def test_the_alert_fires_when_a_run_fails(synced, monkeypatch, caplog) -> None:
    """(f) A test outage: the platform read fails."""
    settings, _, _ = synced

    async def outage(*args, **kwargs):
        raise ConnectionError("test outage")

    monkeypatch.setattr(run.fetch, "read_page_by_id", outage)
    with caplog.at_level(logging.CRITICAL, logger="reco.alert"), pytest.raises(RuntimeError):
        await run.sync_once(settings)

    reasons = {r.reason for r in caplog.records if getattr(r, "alert", False)}
    assert reasons == {"sync_failed", "sync_lag"}
    assert (await writers.read_sync_state(settings, POSTEVENTS))["last_run"]["outcome"] == "failed"


@pytest.mark.mongo
async def test_reconciliation_passes_when_ids_and_fields_match(synced) -> None:
    """(a)"""
    settings, platform, engine = synced
    await platform[POSTEVENTS].insert_many([postevent(), postevent()])
    await platform[ORDERS].insert_one(order())
    await platform[SERVED].insert_one(served_list())
    await run.sync_once(settings)
    today = utc_now().astimezone(reconcile.IST).date().isoformat()

    results = await reconcile.reconcile_day(settings, today)

    assert all(r["passed"] for r in results), results
    assert {r["source"]: r["platform_ids"] for r in results} == {POSTEVENTS: 2, ORDERS: 1, SERVED: 1, "rec_serve_log": 0}
    assert await engine["ml_measurements"].count_documents({"measure": "sync_reconciliation", "day": today}) == 4


@pytest.mark.mongo
async def test_reconciliation_finds_and_rereads_what_the_sync_missed(synced) -> None:
    """(a) Equal counts don't pass: a changed field is found, logged and re-read."""
    settings, platform, engine = synced
    like, placed = postevent(), order()
    await platform[POSTEVENTS].insert_one(like)
    await platform[ORDERS].insert_one(placed)
    await run.sync_once(settings)
    # Changed without moving updated_at (as before APP-12), so the incremental read can't see them.
    await platform[POSTEVENTS].update_one({"_id": like["_id"]}, {"$set": {"undone_at": utc_now()}})
    await platform[ORDERS].update_one({"_id": placed["_id"]}, {"$push": {"tracking_info": {"status": "Delivered", "timestamp": utc_now()}}})
    no_time = postevent()
    no_time.pop("updated_at")
    await platform[POSTEVENTS].insert_one(no_time)
    today = utc_now().astimezone(reconcile.IST).date().isoformat()

    first = {r["source"]: r for r in await reconcile.reconcile_day(settings, today)}

    assert not first[POSTEVENTS]["passed"] and first[POSTEVENTS]["mismatched"] == 1 and first[POSTEVENTS]["missing"] == 1
    assert first[POSTEVENTS]["mismatched_fields"] == {str(like["_id"]): ["undone_at"]}
    assert first[ORDERS]["mismatched_fields"] == {str(placed["_id"]): ["tracking_info"]}
    assert (await engine["ml_events"].find_one({"_id": like["_id"]}))["undone_at"] is not None

    second = await reconcile.reconcile_day(settings, today)
    assert all(r["passed"] for r in second), second


@pytest.mark.mongo
async def test_every_sync_and_reconciliation_run_is_recorded(synced, monkeypatch) -> None:
    """SD-21: every job run is recorded in ml_job_runs, failures included."""
    settings, platform, engine = synced
    await platform[POSTEVENTS].insert_one(postevent())
    await run.sync_once(settings)
    await reconcile.reconcile_day(settings, utc_now().astimezone(reconcile.IST).date().isoformat())

    async def outage(*args, **kwargs):
        raise ConnectionError("test outage")

    monkeypatch.setattr(run.fetch, "read_page_by_updated_at", outage)
    with pytest.raises(RuntimeError):
        await run.sync_once(settings)

    runs = await engine["ml_job_runs"].find({}).sort("started_at", 1).to_list(None)
    assert [(r["job"], r["outcome"]) for r in runs] == [
        ("sync", "succeeded"), ("reconcile_sync", "succeeded"), ("sync", "failed")]
    assert runs[0]["rows_written"] >= 1 and runs[1]["detail"]["passed"][POSTEVENTS] is True
    assert "data_window" in runs[1] and runs[1]["data_window"]["from"] is not None


@pytest.mark.mongo
async def test_a_serve_log_row_written_slightly_out_of_order_is_still_copied(synced) -> None:
    """Append-only rec_serve_log is read by _id with the sync overlap re-read."""
    settings, platform, engine = synced
    now = utc_now()
    first = {"_id": ObjectId.from_datetime(now), "request_id": "r1", "surface": "feed", "page": 1,
             "origin": "engine", "outcome": "ok", "elapsed_ms": 50, "at": now}
    await platform["rec_serve_log"].insert_one(first)
    await run.sync_once(settings)
    # A second SOCO_BE server's row, stamped 30 s earlier, lands after the first was copied.
    late_id = ObjectId.from_datetime(now - timedelta(seconds=30))
    await platform["rec_serve_log"].insert_one({**first, "_id": late_id, "request_id": "r2"})

    await run.incremental(settings, source_named("rec_serve_log"))

    assert await engine["ml_events"].count_documents({"source": "rec_serve_log"}) == 2


def test_an_order_history_entry_with_no_stage_is_logged(caplog) -> None:
    doc = order("Pending")
    doc["tracking_info"].append({"status": "Out for delivery today", "timestamp": utc_now()})
    with caplog.at_level(logging.WARNING, logger="reco.sync"):
        copy = make_copy(source_named(ORDERS), doc, OrderStatusValues())
    assert copy["tracking"][-1]["stage"] is None  # stored, never rejected (DS-017 6.4)
    assert any("no stage" in r.getMessage() for r in caplog.records)
