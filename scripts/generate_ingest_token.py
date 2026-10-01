"""Generate a new INGEST_TOKEN, the serving token. DS-017 v2.5 section 3, AS-04.

    .venv/bin/python scripts/generate_ingest_token.py

Prints a new random token, and writes it nowhere. Then:
  1. dev: add INGEST_TOKEN=<token> to your .env (never committed);
     test/production: set it in the server environment (SD-08).
  2. Give it to Aravinth privately -- never in a file, email or group chat
     (the Build List says "privately", like the DB-02 login).
  3. SOCO_BE sends it on POST /v1/recommendations as: Authorization: Bearer <token>
     (POST /v1/events is retired; the name INGEST_TOKEN is kept for the serving token.)

One token per environment. To replace a token, generate a new one, set it on
both sides, and restart the engine.
"""

from __future__ import annotations

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(32))
