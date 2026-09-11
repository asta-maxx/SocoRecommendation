"""Shared fixtures.

Tests split in two. The model tests need no database and always run. The store
tests need a reachable MongoDB and skip cleanly when there is not one, so a fresh
checkout can run the suite before anyone has a connection string.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
import pytest_asyncio

from reco.config import Settings
from reco.data import mongo
from reco.domain.scores import InterestScore, Method, Window, utc_now

TEST_DB = os.environ.get("TEST_MONGO_DB", "reco_test")

#: Fail fast when there is no MongoDB. PyMongo's default server selection
#: timeout is 30 seconds; across the store tests that is minutes of waiting
#: before the suite reports the one thing it already knew.
_SELECTION_TIMEOUT_MS = int(os.environ.get("TEST_MONGO_TIMEOUT_MS", "1500"))


def _test_uri() -> str:
    uri = os.environ.get("ML_MONGO_URI", "mongodb://localhost:27017")
    separator = "&" if "?" in uri else "?"
    return f"{uri}{separator}serverSelectionTimeoutMS={_SELECTION_TIMEOUT_MS}"


@pytest.fixture
def settings() -> Settings:
    """Settings pointed at a throwaway database, never at the real one."""
    return Settings(
        app_mongo_uri=_test_uri(),
        app_mongo_db=TEST_DB,
        ml_mongo_uri=_test_uri(),
        ml_mongo_db=TEST_DB,
        model_version="test-1.0.0",
    )


@pytest_asyncio.fixture
async def store(settings: Settings):
    """A live, empty score store. Skips the test if Mongo is unreachable."""
    mongo.init_clients(settings)
    try:
        await mongo.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await mongo.close_clients()
        # Never interpolate the URI: it carries the password, and a skip reason
        # is printed in full by -rs and by most CI reporters.
        pytest.skip(f"MongoDB unreachable (db={settings.ml_mongo_db}): {type(exc).__name__}")

    await mongo.ml_db(settings)[settings.scores_collection].drop()

    from reco.data.writers import ensure_indexes

    await ensure_indexes(settings)
    try:
        yield settings
    finally:
        await mongo.ml_db(settings)[settings.scores_collection].drop()
        await mongo.close_clients()


def make_score(**overrides) -> InterestScore:
    """A valid score. Tests override exactly the field under examination."""
    fields = {
        "user_id": "u1",
        "category": "fashion & apparel",
        "raw": 42.5,
        "share": 1.0,
        "event_count": 7,
        "method": Method.RECENCY_DECAY,
        "model_version": "test-1.0.0",
        "window": Window.ALL,
        "computed_at": utc_now(),
    }
    fields.update(overrides)
    return InterestScore(**fields)


def make_user_map(user_id: str, shares: dict[str, float], **overrides):
    """A coherent set of scores for one user, shares summing to 1."""
    return [
        make_score(
            user_id=user_id,
            category=category,
            raw=share * 100,
            share=share,
            **overrides,
        )
        for category, share in shares.items()
    ]


@pytest.fixture
def hours_ago():
    def _hours_ago(hours: float):
        return utc_now() - timedelta(hours=hours)

    return _hours_ago
