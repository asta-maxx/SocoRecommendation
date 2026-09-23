"""Structured logs for every request and job. ENG-02 item 6, SD-27.

One JSON object per line, so a log collector can filter and count by field
instead of parsing sentences. Every line carries the time (UTC, milliseconds),
level, logger, message and environment. Anything passed as `extra=` becomes a
field of its own.

    logger.info("request", extra={"path": "/health", "status": 200})
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from reco.config import Settings

#: Attributes every LogRecord has. Anything else on a record came from `extra=`.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

request_logger = logging.getLogger("reco.request")
job_logger = logging.getLogger("reco.job")


class JsonFormatter(logging.Formatter):
    def __init__(self, environment: str) -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "env": self.environment,
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(settings: Settings) -> None:
    """Send every log line to stderr as JSON. Called once per process."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(settings.engine_env))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)


async def log_request(request: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
    """HTTP middleware: one line per request, with its outcome and duration."""
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        request_logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )


@asynccontextmanager
async def job_run(job: str, **fields: Any) -> AsyncIterator[None]:
    """Log a job's start and its end, with the outcome and duration.

    A failed job is logged with its error and then re-raised, so the caller still
    sees the failure.
    """
    started = time.perf_counter()
    job_logger.info("job started", extra={"job": job, **fields})
    try:
        yield
    except Exception:
        job_logger.exception(
            "job failed",
            extra={
                "job": job,
                "outcome": "failed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                **fields,
            },
        )
        raise
    job_logger.info(
        "job finished",
        extra={
            "job": job,
            "outcome": "succeeded",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            **fields,
        },
    )
