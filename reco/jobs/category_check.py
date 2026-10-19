"""The daily check for categories outside the 23. ENG-29 item 1.

Every category label in use on the platform is matched to the 23, by name or
through the settings' category map. Any that match neither are reported to the
service owner every day (an alert) and recorded in ml_measurements; items in
them are left out of category scoring until the map covers them -- never guessed.
"""

from __future__ import annotations

from typing import Any

from reco.config import Settings
from reco.monitoring.alerts import alert
from reco.platform import fetch
from reco.store import writers
from reco.store.scores import utc_now
from reco.sync.reconcile import IST


async def check_categories(settings: Settings) -> list[dict[str, Any]]:
    unmapped = await fetch.unmapped_categories(settings)
    day = utc_now().astimezone(IST).date().isoformat()
    await writers.record_measurement(
        settings, {"measure": "unmapped_categories", "day": day},
        {"checked_at": utc_now(), "unmapped": unmapped[:200], "count": len(unmapped),
         "items": sum(row["items"] for row in unmapped)},
    )
    if unmapped:
        alert("unmapped_categories", "platform categories outside the 23 and not in the category map",
              count=len(unmapped), labels=[row["label"] for row in unmapped[:20]])
    return unmapped


async def check_history_texts(settings: Settings) -> list[dict[str, Any]]:
    """ENG-30 point 5: "An entry that matches nothing is reported daily and never
    guessed." Recorded in ml_measurements (measure unmatched_history_texts) and
    alerted when there is any."""
    unmatched = await writers.read_unmatched_history(settings)
    day = utc_now().astimezone(IST).date().isoformat()
    await writers.record_measurement(
        settings, {"measure": "unmatched_history_texts", "day": day},
        {"checked_at": utc_now(), "texts": unmatched[:200], "count": len(unmatched),
         "orders": sum(row["orders"] for row in unmatched)},
    )
    if unmatched:
        alert("unmatched_history_texts", "order-history texts the history-text map does not match",
              count=len(unmatched), texts=[row["text"] for row in unmatched[:20]])
    return unmatched

