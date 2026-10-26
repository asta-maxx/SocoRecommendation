"""The serving token. DS-017 v2.5 section 3, AS-04.

POST /v1/recommendations carries Authorization: Bearer <INGEST_TOKEN>; the name
INGEST_TOKEN is kept for the serving token (POST /v1/events is retired). The
fraud case API uses its own ADMIN_TOKEN (ENG-21).
"""

from __future__ import annotations

import hmac
import logging

from reco.config import Settings

logger = logging.getLogger("reco.api.auth")


def token_ok(settings: Settings, authorization: str | None) -> bool:
    """Authorization: Bearer <INGEST_TOKEN>, compared in constant time. No token set: refused."""
    if not settings.ingest_token:
        logger.error("INGEST_TOKEN is not set; refusing the call")
        return False
    scheme, _, token = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        token.strip().encode(), settings.ingest_token.encode()
    )
