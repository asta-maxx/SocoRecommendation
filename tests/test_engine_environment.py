"""ENG-01: environments, the engine's own database, and its twelve collections."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pydantic import ValidationError

from reco.config import (
    ENGINE_COLLECTIONS,
    ENGINE_ENVIRONMENTS,
    Settings,
    _hosts_of,
    _require_production_env_from_server,
)
from reco.platform import connection as platform_conn
from reco.store import connection as store_conn
from reco.store.writers import ensure_engine_collections

ATLAS_A = "mongodb+srv://reader:secret@nex-dev.cob9whd.mongodb.net/soco?retryWrites=true"
ATLAS_B = "mongodb+srv://writer:secret@soco.4b7z1ko.mongodb.net/"


# --- environments ------------------------------------------------------------


def test_the_three_environments_are_sd04() -> None:
    assert ENGINE_ENVIRONMENTS == ("dev", "test", "production")


def test_default_environment_is_dev() -> None:
    assert Settings().engine_env == "dev"


@pytest.mark.parametrize("given,expected", [("TEST", "test"), (" production ", "production")])
def test_environment_is_normalised(given: str, expected: str) -> None:
    assert Settings(engine_env=given).engine_env == expected


def test_unknown_environment_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(engine_env="staging")


@pytest.mark.parametrize("env", ENGINE_ENVIRONMENTS)
def test_each_environment_gets_its_own_engine_database_by_default(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("ENGINE_ENV", env)
    monkeypatch.delenv("ML_MONGO_DB", raising=False)
    # The test-only limits a test-server run exports are refused in production (by design).
    monkeypatch.delenv("REQUEST_BUDGET_MS", raising=False)
    monkeypatch.delenv("SOURCE_TIME_LIMIT_MS", raising=False)
    monkeypatch.setattr("reco.config._SERVER_ENGINE_ENV", env)

    assert Settings.from_env().ml_mongo_db == f"soco_engine_{env}"


# --- SD-08: production settings come from the server, not a file -----------------


def test_production_from_a_dotenv_file_is_refused() -> None:
    with pytest.raises(RuntimeError, match="SD-08"):
        _require_production_env_from_server("production", server_engine_env="")


def test_production_from_the_server_is_accepted() -> None:
    _require_production_env_from_server("production", server_engine_env="production")


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_and_test_may_use_a_dotenv_file(env: str) -> None:
    _require_production_env_from_server(env, server_engine_env="")


# --- AS-09 / SD-06: the engine database is never the platform database -------------


def test_hosts_drop_scheme_credentials_and_options() -> None:
    assert _hosts_of(ATLAS_A) == ("nex-dev.cob9whd.mongodb.net",)
    assert _hosts_of("mongodb://u:p@h2:27017,h1:27017/db?rs=x") == ("h1:27017", "h2:27017")


def test_separate_clusters_may_share_a_database_name() -> None:
    Settings(app_mongo_uri=ATLAS_A, app_mongo_db="soco", ml_mongo_uri=ATLAS_B, ml_mongo_db="soco")


def test_same_cluster_with_a_different_database_is_allowed() -> None:
    Settings(app_mongo_uri=ATLAS_A, app_mongo_db="soco", ml_mongo_uri=ATLAS_A, ml_mongo_db="soco_engine_dev")


@pytest.mark.parametrize("engine_db", ["soco", "SoCo"])
def test_engine_database_that_is_the_platform_database_is_refused(engine_db: str) -> None:
    other_credentials = ATLAS_A.replace("reader:secret", "writer:other")
    with pytest.raises(ValidationError, match="AS-09"):
        Settings(
            app_mongo_uri=ATLAS_A,
            app_mongo_db="soco",
            ml_mongo_uri=other_credentials,
            ml_mongo_db=engine_db,
        )


def test_refusal_does_not_print_the_password() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(app_mongo_uri=ATLAS_A, app_mongo_db="soco", ml_mongo_uri=ATLAS_A, ml_mongo_db="soco")

    assert "secret" not in str(exc.value)


# --- ENG-01 item 2: the twelve collections ------------------------------------


def test_engine_collections_are_the_sixteen_in_eng01() -> None:
    """Build List ENG-01 item 2's sixteen, and ml_return_requests (ENG-30 point 7; SDA v1.7)."""
    assert set(ENGINE_COLLECTIONS) == {
        "ml_return_requests",
        "ml_events",
        "ml_orders",
        "ml_sync_state",
        "ml_item_state",
        "ml_deletions",
        "ml_user_interest_scores",
        "ml_product_scores",
        "ml_promoter_scores",
        "ml_promoter_scores_monthly",
        "ml_opportunity_scores",
        "ml_user_candidates",
        "ml_fraud_flags",
        "ml_fraud_cases",
        "ml_job_runs",
        "ml_config_changes",
        "ml_measurements",
    }
    assert len(ENGINE_COLLECTIONS) == 17
    assert all(name.startswith("ml_") for name in ENGINE_COLLECTIONS)


@pytest_asyncio.fixture
async def engine_db(settings: Settings):
    """The throwaway test database, emptied of engine collections before and after."""
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable (db={settings.ml_mongo_db}): {type(exc).__name__}")

    database = store_conn.ml_db(settings)
    for name in ENGINE_COLLECTIONS:
        await database[name].drop()
    try:
        yield database
    finally:
        for name in ENGINE_COLLECTIONS:
            await database[name].drop()
        await platform_conn.close_client()
        await store_conn.close_client()


@pytest.mark.mongo
async def test_all_twelve_collections_are_created_once(settings: Settings, engine_db) -> None:
    first = await ensure_engine_collections(settings)
    second = await ensure_engine_collections(settings)

    assert sorted(first) == sorted(ENGINE_COLLECTIONS)
    assert second == []
    assert set(ENGINE_COLLECTIONS) <= set(await engine_db.list_collection_names())


@pytest.mark.mongo
@pytest.mark.parametrize("collection", ["ml_events", "ml_orders"])
async def test_copies_expire_365_days_after_the_original_event_time(
    settings: Settings, engine_db, collection: str
) -> None:
    """SD-29, X-08: at least 365 days, under the engine's own expiry, on created_at."""
    await ensure_engine_collections(settings)
    indexes = {index["name"]: index async for index in await engine_db[collection].list_indexes()}

    assert list(indexes["retention"]["key"].items()) == [("created_at", 1)]
    assert indexes["retention"]["expireAfterSeconds"] == 365 * 24 * 3600


@pytest.mark.mongo
async def test_ml_events_is_keyed_on_the_platform_id_not_event_id(settings: Settings, engine_db) -> None:
    """The sync upserts on the platform _id (ENG-04); the 22 Sep unique event_id index is dropped."""
    # As built to the 22 Sep design: unique event_id, and user_time on server_ts.
    await engine_db["ml_events"].create_index([("event_id", 1)], unique=True, name="uniq_event_id")
    await engine_db["ml_events"].create_index([("user_id", 1), ("server_ts", -1)], name="user_time")
    await ensure_engine_collections(settings)
    indexes = {index["name"]: index async for index in await engine_db["ml_events"].list_indexes()}

    assert "uniq_event_id" not in indexes
    assert list(indexes["user_time"]["key"].items()) == [("user_id", 1), ("created_at", -1)]
    assert list(indexes["request_id"]["key"].items()) == [("request_id", 1)]
