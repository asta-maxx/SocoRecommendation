"""ENG-02 items 1 and 6: jobs mode, and structured logs for every request and job."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from reco.jobs.__main__ import JOBS, main
from reco.monitoring.logs import JsonFormatter, job_run, log_request


def _record(message: str, **extra) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "reco.test", "levelname": "INFO", "msg": message})
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_a_line_is_json_with_the_standard_fields() -> None:
    line = JsonFormatter("dev").format(_record("hello %s", args=None))
    entry = json.loads(line)

    assert set(entry) >= {"ts", "level", "logger", "message", "env"}
    assert entry["env"] == "dev"
    assert entry["ts"].endswith("Z") and "." in entry["ts"]  # UTC, milliseconds


def test_extra_fields_become_their_own_keys() -> None:
    entry = json.loads(JsonFormatter("test").format(_record("request", path="/health", status=200)))

    assert entry["path"] == "/health"
    assert entry["status"] == 200


async def test_every_request_is_logged_with_status_and_duration(caplog) -> None:
    request = SimpleNamespace(method="GET", url=SimpleNamespace(path="/health"))

    async def call_next(_):
        return SimpleNamespace(status_code=503)

    with caplog.at_level(logging.INFO, logger="reco.request"):
        await log_request(request, call_next)

    record = caplog.records[-1]
    assert (record.method, record.path, record.status) == ("GET", "/health", 503)
    assert record.duration_ms >= 0


async def test_a_request_that_raises_is_still_logged(caplog) -> None:
    request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/v1/events"))

    async def call_next(_):
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="reco.request"), pytest.raises(RuntimeError):
        await log_request(request, call_next)

    assert caplog.records[-1].status == 500


async def test_a_job_logs_its_start_and_finish(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="reco.job"):
        async with job_run("interest", method="recency_decay"):
            pass

    started, finished = caplog.records[-2:]
    assert started.message == "job started" and started.job == "interest"
    assert finished.message == "job finished" and finished.outcome == "succeeded"
    assert finished.duration_ms >= 0


async def test_a_failed_job_is_logged_and_still_raises(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="reco.job"), pytest.raises(ValueError):
        async with job_run("interest"):
            raise ValueError("bad data")

    failed = caplog.records[-1]
    assert failed.message == "job failed" and failed.outcome == "failed"
    assert failed.levelno == logging.ERROR


def test_jobs_mode_lists_its_jobs(capsys) -> None:
    assert main(["--list"]) == 0
    assert capsys.readouterr().out.split() == sorted(JOBS)
