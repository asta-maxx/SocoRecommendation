"""The watcher (ENG-04 item 7, ENG-07), and a settings change not recorded is not applied (ENG-02 item 4)."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from reco.config import sync as config_sync
from reco.config.tunables import Tunables
from reco.monitoring import watch
from reco.store import connection as store_conn
from reco.store import writers
from reco.store.scores import utc_now


@pytest.mark.mongo
async def test_a_run_left_running_too_long_is_alerted(store, caplog) -> None:
    settings = store
    runs = store_conn.ml_db(settings)["ml_job_runs"]
    await runs.drop()
    await writers.record_job_run(settings, {"_id": "old", "job": "interest", "method": "recency_decay",
                                            "outcome": "running", "started_at": utc_now() - timedelta(hours=3)})
    await writers.record_job_run(settings, {"_id": "new", "job": "interest", "method": "time_windows",
                                            "outcome": "running", "started_at": utc_now() - timedelta(minutes=5)})
    with caplog.at_level(logging.CRITICAL, logger="reco.alert"):
        stuck = await watch.stuck_runs(settings)
    assert [r["_id"] for r in stuck] == ["old"]
    assert any(getattr(r, "reason", None) == "job_stuck" and r.job_run_id == "old" for r in caplog.records)
    await runs.drop()


async def test_a_settings_change_that_could_not_be_recorded_is_not_applied_and_tried_again(monkeypatch) -> None:
    """Review point 3 (26 Oct): not written, not applied. The rest is in test_settings_diary.py."""
    written = []
    calls = {"n": 0}

    async def flaky(settings, record):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("engine database down")
        written.append(record["config_version"])
        return True

    async def no_latest(settings):
        return None

    monkeypatch.setattr(config_sync.writers, "record_config_change", flaky)
    monkeypatch.setattr(config_sync.writers, "read_latest_config_change", no_latest)
    monkeypatch.setattr(config_sync, "_alerted", None)
    from reco.config import Settings, live

    old, new = Tunables(), Tunables().with_changes({"config_version": "9"})
    assert await config_sync._apply(Settings(), old, new, []) is False
    assert written == [] and live.current().config_version == old.config_version
    assert await config_sync._apply(Settings(), old, new, []) is True
    assert written == ["9"] and live.current().config_version == "9"
