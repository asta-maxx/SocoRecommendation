"""Print the time limits this run uses (review of 26 Oct 2026, point 1; checklist line 6.0).

    .venv/bin/python scripts/show_limits.py

REQUEST_BUDGET_MS and SOURCE_TIME_LIMIT_MS are test-only overrides (refused in
production); unset, the pack's limits apply: the request 250 ms (2 s on dev) and
each candidate source retrieval.source_time_limit_ms (20 ms).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reco.config import get_settings  # noqa: E402

s = get_settings()
request = f"{s.request_budget_ms} ms (test-only)" if s.request_budget_ms else "default: 250 ms (2 s on dev)"
source = f"{s.source_time_limit_ms} ms (test-only)" if s.source_time_limit_ms else "default: 20 ms"
print(f"environment {s.engine_env}: request limit {request}; each candidate source {source}")
