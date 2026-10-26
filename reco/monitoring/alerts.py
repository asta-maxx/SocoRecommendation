"""Alerts to the service owner. ENG-04 item 7.

An alert is a structured log line at CRITICAL with "alert": true and the
owner, so a log collector can route it on that one field. The pack names who is
alerted (the service owner, Allen) but not the channel; until one is chosen the
log line is the alert.
"""

from __future__ import annotations

import logging
from typing import Any

alert_logger = logging.getLogger("reco.alert")

SERVICE_OWNER = "Allen"


def alert(reason: str, message: str, **fields: Any) -> None:
    alert_logger.critical(message, extra={"alert": True, "reason": reason, "owner": SERVICE_OWNER, **fields})
