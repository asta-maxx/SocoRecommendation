"""Time today's /dashboard-feed call end to end, and save the numbers (ENG-20 part 1).

    SOCO_FEED_URL=https://.../dashboard-feed SOCO_FEED_TOKEN=... \
        .venv/bin/python scripts/time_dashboard_feed.py [requests]

Build List, ENG-20: "Now: measure today's /dashboard-feed call end to end over
at least 1,000 requests, as p50, p95 and p99. Save the numbers (see the Home
sheet). If p95 is over 120 ms, cut the pool from 300 to 200 yourself."

Settings, from the environment (never printed or saved):
    SOCO_FEED_URL     the full URL of SOCO_BE's feed call, query string included
    SOCO_FEED_TOKEN   a test user's bearer token (optional)
    SOCO_FEED_METHOD  GET (default) or POST
    SOCO_FEED_BODY    a JSON body for POST (optional)

Requests go one after another, so each time is one call on its own. The first
10 warm the connection and are not timed. Only 2xx answers count towards the
percentiles; anything else is counted as an error. The record goes to
Tracing/checks/ENG-20_<date>.md with the host it was measured from, because a
laptop's network adds time that a server next to SOCO_BE would not.

Exit 0 when the numbers are saved and p95 is 120 ms or less; 1 when p95 is over
120 ms (cut the pool); 2 when it could not measure.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import platform
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIMUM = 1000  # Build List ENG-20: "at least 1,000 requests"
WARM_UP = 10
POOL_CUT_P95_MS = 120  # Build List ENG-20 and the Settings sheet (pool size)


def percentile(times: list[float], share: float) -> float:
    """Nearest-rank percentile: the smallest time at or above `share` of the calls."""
    ordered = sorted(times)
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


def summary(times: list[float]) -> dict[str, float]:
    return {
        "p50": percentile(times, 0.50), "p95": percentile(times, 0.95), "p99": percentile(times, 0.99),
        "min": min(times), "max": max(times),
    }


def call(request: urllib.request.Request) -> tuple[int, float]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (urllib.error.URLError, TimeoutError, OSError):
        status = 0
    return status, (time.perf_counter() - started) * 1000


def build_request() -> urllib.request.Request:
    method = os.environ.get("SOCO_FEED_METHOD", "GET").upper()
    body = os.environ.get("SOCO_FEED_BODY")
    headers = {"Accept": "application/json"}
    if token := os.environ.get("SOCO_FEED_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    if body:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(
        os.environ["SOCO_FEED_URL"], data=body.encode() if body else None, method=method, headers=headers,
    )


def record(path_only: str, host: str, count: int, errors: dict[int, int], stats: dict[str, float]) -> Path:
    today = dt.date.today().isoformat()
    verdict = (
        f"**p95 is over {POOL_CUT_P95_MS} ms: cut the pool from 300 to 200** (settings `pool_size`)."
        if stats["p95"] > POOL_CUT_P95_MS
        else f"p95 is {POOL_CUT_P95_MS} ms or less: the pool stays at 300."
    )
    lines = [
        f"# ENG-20 part 1: today's /dashboard-feed, {today}",
        "",
        "Build List ENG-20 part 1: measure today's /dashboard-feed call end to end over at least",
        "1,000 requests, as p50, p95 and p99, and save the numbers.",
        "",
        f"- Call: `{path_only}` (host and token not recorded)",
        f"- Measured from: {host}",
        f"- Requests timed: {count} (after {WARM_UP} untimed warm-up calls), one after another",
        f"- Errors (not timed): {sum(errors.values())}" + (f" {dict(sorted(errors.items()))}" if errors else ""),
        "",
        "| p50 | p95 | p99 | min | max |",
        "|---|---|---|---|---|",
        "| " + " | ".join(f"{stats[k]:.0f} ms" for k in ("p50", "p95", "p99", "min", "max")) + " |",
        "",
        verdict,
        "",
    ]
    out = ROOT / "Tracing" / "checks" / f"ENG-20_{today}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main(count: int) -> int:
    if "SOCO_FEED_URL" not in os.environ:
        print("Set SOCO_FEED_URL to SOCO_BE's /dashboard-feed URL (and SOCO_FEED_TOKEN if it needs a login).")
        return 2
    if count < MINIMUM:
        print(f"ENG-20 asks for at least {MINIMUM} requests; got {count}.")
        return 2
    request = build_request()
    for _ in range(WARM_UP):
        call(request)
    times: list[float] = []
    errors: dict[int, int] = {}
    for done in range(1, count + 1):
        status, ms = call(request)
        if 200 <= status < 300:
            times.append(ms)
        else:
            errors[status] = errors.get(status, 0) + 1
        if done % 100 == 0:
            print(f"  {done}/{count}")
    if len(times) < MINIMUM:
        print(f"Only {len(times)} of {count} calls answered 2xx; errors by status: {errors}. Nothing saved.")
        return 2
    stats = summary(times)
    path_only = urllib.parse.urlsplit(request.full_url).path
    host = f"{platform.node()} ({platform.system()})"
    out = record(path_only, host, len(times), errors, stats)
    print(json.dumps({k: round(v, 1) for k, v in stats.items()}), f"errors={sum(errors.values())}")
    print(f"Saved {out.relative_to(ROOT)}")
    return 1 if stats["p95"] > POOL_CUT_P95_MS else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else MINIMUM))
