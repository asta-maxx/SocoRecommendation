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

from reco.config import Settings, live
from reco.config.tunables import Tunables
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.store.scores import InterestScore, Method, Window, utc_now

#: Each test run gets its own throwaway databases (run id = process id), so two
#: runs at once never share collections; both are dropped when the run ends.
TEST_DB = os.environ.get("TEST_MONGO_DB", f"reco_test_{os.getpid()}")

#: The DS-007 v1.1 values Kala's demo generator used (reference/v2). Tests that
#: compare the engine with the demo dataset's expected answers pin these; every
#: other test uses the Settings sheet through m1_tunables().
DS007_M1_TUNABLES = {
    "P-02": 3.0,
    "P-04": 30.0,
    "P-05": {},
    "P-06": {"view": 2.0, "click": 5.0, "cart": 10.0, "purchase": 20.0, "search": 3.0},
    "P-07": 0.0,
    "P-08": 24.0,
    "P-09": "daily",
    "P-10": [7, 30, 90],
    "P-11": [0.5, 0.3, 0.2],
    "P-25": 10.0,
    "P-26": False,
    "P-27": 30,
}


def m1_tunables(changes: dict | None = None) -> dict:
    """What the M1 methods read, from the Settings sheet, with dotted changes.

    m1_tunables({"interest.half_life_days": 60}) -- validated against the sheet.
    """
    return Tunables().with_changes(changes or {}).m1()


def put_in_force(changes: dict) -> None:
    """Make the settings in force the Settings sheet with these changes."""
    live.put_in_force(Tunables().with_changes(changes), "test")


@pytest.fixture(autouse=True)
def _settings_sheet_in_force():
    """Every test starts, and ends, with the Settings-sheet defaults in force."""
    live.reset()
    yield
    live.reset()


@pytest.fixture(autouse=True)
def _own_state_dir(tmp_path_factory, monkeypatch):
    """Every test keeps its settings state (reco.config.state) in a folder of its own,
    never in the repo's .state/ or the server's /var/lib/reco."""
    from reco.config import state

    folder = tmp_path_factory.mktemp("state")
    monkeypatch.setattr(state, "DEV_DIR", folder)
    monkeypatch.setattr(state, "SERVER_DIR", folder)
    return folder
#: The engine database is never the platform database (AS-09), so the test
#: settings name a separate one for the read-only side. Store tests seed and read
#: ml_ collections only, which live in TEST_DB.
TEST_PLATFORM_DB = f"{TEST_DB}_platform"

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
        app_mongo_db=TEST_PLATFORM_DB,
        ml_mongo_uri=_test_uri(),
        ml_mongo_db=TEST_DB,
        model_version="test-1.0.0",
    )


@pytest_asyncio.fixture
async def store(settings: Settings):
    """A live, empty score store. Skips the test if Mongo is unreachable."""
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        # Never interpolate the URI: it carries the password, and a skip reason
        # is printed in full by -rs and by most CI reporters.
        pytest.skip(f"MongoDB unreachable (db={settings.ml_mongo_db}): {type(exc).__name__}")

    await store_conn.ml_db(settings)[settings.scores_collection].drop()

    from reco.store.writers import ensure_indexes

    await ensure_indexes(settings)
    try:
        yield settings
    finally:
        await store_conn.ml_db(settings)[settings.scores_collection].drop()
        await platform_conn.close_client()
        await store_conn.close_client()


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


@pytest.fixture(scope="session", autouse=True)
def _drop_the_run_databases():
    """Drop this run's two throwaway databases at the end (ignored without MongoDB)."""
    yield
    import asyncio

    from pymongo import AsyncMongoClient

    async def drop() -> None:
        client = AsyncMongoClient(_test_uri())
        try:
            for name in (TEST_DB, TEST_PLATFORM_DB):
                await client.drop_database(name)
        finally:
            await client.close()

    try:
        asyncio.run(drop())
    except Exception:  # pragma: no cover - environment dependent
        pass
