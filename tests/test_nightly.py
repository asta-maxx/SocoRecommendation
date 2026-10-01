"""ENG-07: the daily refresh -- batches, the current marker, ml_job_runs, the 2 AM IST schedule.

The Build List's check: "Kill a job halfway: requests keep reading the previous
batch. ml_job_runs shows the failure."

    a job that fails halfway                     test_a_failure_halfway_keeps_the_previous_batch
    a job killed halfway (nothing runs after)    test_a_killed_run_is_recorded_as_failed_and_never_read
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from reco.jobs import batches, scheduler
from reco.store import connection as store_conn
from reco.store import writers
from reco.store.scores import Method, Window, utc_now
from tests.conftest import make_user_map

METHOD = str(Method.RECENCY_DECAY)


# --- the schedule (no database) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "due"),
    [
        ("2026-10-01T01:00:00+05:30", "2026-10-01T02:00:00+05:30"),
        ("2026-10-01T02:00:00+05:30", "2026-10-02T02:00:00+05:30"),
        ("2026-10-01T23:30:00+00:00", "2026-10-03T02:00:00+05:30"),  # already 05:00 IST on the 2nd
    ],
)
def test_the_next_run_is_2am_ist(now: str, due: str) -> None:
    assert scheduler.next_run(datetime.fromisoformat(now)) == datetime.fromisoformat(due)


def test_the_run_time_is_the_setting_and_reconciliation_runs_last() -> None:
    from reco.config import live

    assert live.current().interest.refresh_time_ist == "02:00"  # SD-22, the Settings sheet
    assert scheduler.next_run(datetime.fromisoformat("2026-10-01T03:00:00+05:30"), "03:30") == datetime.fromisoformat("2026-10-01T03:30:00+05:30")
    assert scheduler.NIGHTLY[-1] == "reconcile_sync"


async def test_a_failed_nightly_job_does_not_stop_the_others(monkeypatch, caplog) -> None:
    ran = []

    async def bad(settings):
        ran.append("bad")
        raise RuntimeError("boom")

    async def good(settings):
        ran.append("good")

    monkeypatch.setattr(scheduler, "NIGHTLY", ("bad", "good"))
    with caplog.at_level(logging.CRITICAL, logger="reco.alert"):
        failed = await scheduler.run_nightly(None, {"bad": bad, "good": good})
    assert ran == ["bad", "good"] and failed == ["bad"]
    assert any(getattr(r, "reason", None) == "job_failed" for r in caplog.records)


# --- batches (database) -----------------------------------------------------------------


@pytest_asyncio.fixture
async def nightly(store):
    runs = store_conn.ml_db(store)["ml_job_runs"]
    await runs.drop()
    await writers.ensure_engine_collections(store)
    yield store
    await runs.drop()


def _writer(settings, shares: dict[str, float], fail_after: int | None = None):
    """A job's work: writes users U1..Un, each with `shares`; raises after `fail_after` users."""

    async def work(job_run_id: str) -> int:
        written = 0
        for n in range(1, 5):
            if fail_after is not None and n > fail_after:
                raise RuntimeError("stopped halfway")
            scores = make_user_map(f"U{n}", shares, job_run_id=job_run_id, config_version="2",
                                   data_window={"from": None, "to": utc_now()}, computed_at=utc_now())
            written += await writers.upsert_user_scores(settings, f"U{n}", scores)
        return written

    return work


async def _batch(settings, work):
    return await batches.run_batch(
        settings, job="interest", slot="interest", method=METHOD, collection=settings.scores_collection,
        data_window={"from": None, "to": utc_now()}, work=work,
    )


async def _shares(settings, user: str) -> dict[str, float]:
    return {s.category: s.share for s in await writers.read_user_scores(settings, user, METHOD)}


@pytest.mark.mongo
async def test_a_batch_is_read_only_once_complete_and_current(nightly) -> None:
    settings = nightly
    record = await _batch(settings, _writer(settings, {"fashion": 1.0}))

    assert record["outcome"] == "succeeded" and record["is_current"] and record["rows_written"] == 4
    assert await _shares(settings, "U1") == {"fashion": 1.0}
    run = await store_conn.ml_db(settings)["ml_job_runs"].find_one({"_id": record["_id"]})
    for field in ("job", "slot", "method", "data_window", "rows_written", "duration_seconds", "outcome",
                  "started_at", "finished_at", "config_version", "model_version"):
        assert field in run, field


@pytest.mark.mongo
async def test_every_score_row_carries_its_provenance(nightly) -> None:
    settings = nightly
    record = await _batch(settings, _writer(settings, {"fashion": 0.6, "beauty": 0.4}))
    row = await store_conn.ml_db(settings)[settings.scores_collection].find_one({"user_id": "U1"})
    for field in ("user_id", "category", "slot", "method", "model_version", "config_version", "score",
                  "confidence", "data_window", "computed_at", "job_run_id"):
        assert field in row, field
    assert row["job_run_id"] == record["_id"] and row["score"] == row["share"]


@pytest.mark.mongo
async def test_a_new_batch_replaces_the_old_one_and_older_batches_are_cleared(nightly) -> None:
    settings = nightly
    first = await _batch(settings, _writer(settings, {"fashion": 1.0}))
    second = await _batch(settings, _writer(settings, {"beauty": 1.0}))
    third = await _batch(settings, _writer(settings, {"travel": 1.0}))

    assert await _shares(settings, "U1") == {"travel": 1.0}
    assert third["replaced"] == second["_id"]
    held = set(await store_conn.ml_db(settings)[settings.scores_collection].distinct("job_run_id"))
    assert held == {second["_id"], third["_id"]}  # the replaced batch is kept one more night
    assert first["_id"] not in held


@pytest.mark.mongo
async def test_a_failure_halfway_keeps_the_previous_batch(nightly) -> None:
    settings = nightly
    good = await _batch(settings, _writer(settings, {"fashion": 1.0}))

    with pytest.raises(RuntimeError):
        await _batch(settings, _writer(settings, {"beauty": 1.0}, fail_after=2))

    assert await _shares(settings, "U1") == {"fashion": 1.0}  # requests still read the previous batch
    assert await writers.current_job_run_id(settings, "interest", METHOD) == good["_id"]
    failed = await store_conn.ml_db(settings)["ml_job_runs"].find_one({"outcome": "failed"})
    assert failed and "stopped halfway" in failed["error"] and not failed["is_current"]
    assert set(await store_conn.ml_db(settings)[settings.scores_collection].distinct("job_run_id")) == {good["_id"]}


@pytest.mark.mongo
async def test_a_killed_run_is_recorded_as_failed_and_never_read(nightly) -> None:
    """A kill runs no handler: the run is left 'running' with half its rows written."""
    settings = nightly
    good = await _batch(settings, _writer(settings, {"fashion": 1.0}))
    killed = "killed-run"
    await writers.record_job_run(settings, {"_id": killed, "job": "interest", "slot": "interest", "method": METHOD,
                                            "started_at": utc_now(), "outcome": "running", "is_current": False})
    for n in (1, 2):
        await writers.upsert_user_scores(settings, f"U{n}", make_user_map(f"U{n}", {"beauty": 1.0}, job_run_id=killed))

    assert await _shares(settings, "U1") == {"fashion": 1.0}  # requests keep reading the previous batch

    await _batch(settings, _writer(settings, {"travel": 1.0}))  # the next night

    run = await store_conn.ml_db(settings)["ml_job_runs"].find_one({"_id": killed})
    assert run["outcome"] == "failed" and "abandoned" in run["error"]  # ml_job_runs shows the failure
    held = set(await store_conn.ml_db(settings)[settings.scores_collection].distinct("job_run_id"))
    assert killed not in held and good["_id"] in held


async def test_one_interest_method_failing_still_runs_the_other(monkeypatch) -> None:
    from reco.jobs import __main__ as jobs

    ran = []

    async def method(settings, m):
        ran.append(str(m))
        if m == jobs.Method.RECENCY_DECAY:
            raise RuntimeError("boom")

    monkeypatch.setattr(jobs, "_interest_method", method)
    with pytest.raises(RuntimeError, match="recency_decay"):
        await jobs._interest(None)
    assert ran == ["recency_decay", "time_windows"]
