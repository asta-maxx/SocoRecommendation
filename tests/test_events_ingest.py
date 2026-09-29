"""ENG-04 items 1-6: POST /v1/events -- check, de-duplicate, store, reply.

The Build List check: "Send the same batch twice: the second reply shows all
duplicates. An event with position 0 is rejected with a reason."
"""

from __future__ import annotations

import uuid

import pytest

from reco.api.events import token_ok
from reco.config import Settings
from reco.events import ingest as ingest_module
from reco.events.ingest import (
    EVENT_NAMES,
    MAX_EVENTS_PER_CALL,
    BatchRefused,
    ingest,
    read_batch,
    reason_to_reject,
    to_document,
)

USER = "65f1a2b3c4d5e6f708192a3b"
ITEM = "6a3fe5cfcce0b0785136e7fe"


def impression(**overrides) -> dict:
    event = {
        "event_id": str(uuid.uuid4()), "event_name": "recommendation_impression", "user_id": USER,
        "server_ts": "2026-10-20T09:15:30.010Z", "request_id": "3f1c9a2e-7b4d-4e21-9c8a-5d6e7f8a9b0c",
        "item_id": ITEM, "item_type": "product", "position": 1, "viewport_entered": True,
        "dwell_ms": 2400, "is_exploration": False, "client_ts": "2026-10-20T14:45:29+05:30",
    }
    event.update(overrides)
    return event


def social(**overrides) -> dict:
    event = {"event_id": str(uuid.uuid4()), "event_name": "social_interaction", "user_id": USER,
             "server_ts": "2026-10-20T09:16:05.000Z", "target_id": ITEM, "action": "like", "request_id": None}
    event.update(overrides)
    return event


# --- the eight names ------------------------------------------------------------------


def test_the_eight_wave_1a_event_names() -> None:
    assert EVENT_NAMES == {
        "recommendation_request", "recommendation_impression", "recommendation_click", "add_to_cart",
        "order_placed", "order_state_changed", "social_interaction", "content_feedback",
    }


# --- ENG-04 item 3: what is rejected, and why ---------------------------------------------


def test_a_good_event_is_accepted() -> None:
    assert reason_to_reject(impression()) is None


def test_position_0_is_rejected_with_a_reason() -> None:
    """Half of the Build List's check."""
    assert "position 0" in reason_to_reject(impression(position=0))


@pytest.mark.parametrize("surface", ["opportunity", "home_for_you", ""])
def test_a_surface_other_than_feed_or_product_is_rejected(surface: str) -> None:
    event = {"event_id": "e1", "event_name": "recommendation_request", "user_id": USER,
             "request_id": "r1", "surface": surface}
    assert "not feed or product" in reason_to_reject(event)


@pytest.mark.parametrize("item_type", ["brand", "promotion", "promoter"])
def test_an_item_type_other_than_post_or_product_is_rejected(item_type: str) -> None:
    assert "not post or product" in reason_to_reject(impression(item_type=item_type))


@pytest.mark.parametrize("name", ["recommendation_request", "recommendation_impression", "recommendation_click"])
@pytest.mark.parametrize("missing", [None, "", "absent"])
def test_request_id_is_required_on_request_impression_and_click(name: str, missing) -> None:
    event = impression(event_name=name)
    if missing == "absent":
        del event["request_id"]
    else:
        event["request_id"] = missing
    assert "request_id is missing" in reason_to_reject(event)


@pytest.mark.parametrize("name", ["add_to_cart", "order_placed", "social_interaction", "content_feedback"])
def test_request_id_may_be_empty_on_the_others(name: str) -> None:
    assert reason_to_reject(social(event_name=name, request_id=None)) is None


def test_order_state_changed_needs_no_request_id() -> None:
    event = {"event_id": "e1", "event_name": "order_state_changed", "user_id": USER,
             "order_id": "o1", "new_state": "Delivered"}
    assert reason_to_reject(event) is None


@pytest.mark.parametrize("field", ["event_id", "event_name", "user_id"])
def test_every_event_carries_event_id_name_and_user(field: str) -> None:
    event = impression()
    del event[field]
    assert f"{field} is missing" in reason_to_reject(event)


@pytest.mark.parametrize("name", ["payment_state_changed", "search_performed", "identity_stitched", "view"])
def test_events_outside_wave_1a_are_rejected(name: str) -> None:
    assert "not a Wave 1A event" in reason_to_reject(impression(event_name=name))


def test_checks_apply_only_to_events_that_carry_the_field() -> None:
    """A social_interaction has no position, surface or item_type: none of those checks apply."""
    event = social()
    assert "position" not in event and reason_to_reject(event) is None


# --- ENG-04 item 1: the batch ----------------------------------------------------------


def test_the_body_must_be_an_events_list() -> None:
    with pytest.raises(BatchRefused) as refused:
        read_batch({"items": []})
    assert refused.value.code == "invalid_body"


def test_at_most_100_events_per_call() -> None:
    read_batch({"events": [impression() for _ in range(MAX_EVENTS_PER_CALL)]})
    with pytest.raises(BatchRefused) as refused:
        read_batch({"events": [impression() for _ in range(MAX_EVENTS_PER_CALL + 1)]})
    assert refused.value.code == "too_many_events"


# --- stored exactly as sent ------------------------------------------------------------


def test_stored_as_sent_with_server_ts_as_a_date_and_client_ts_untouched() -> None:
    event = impression()
    document = to_document(event, received_at="now")

    assert document["server_ts"].isoformat().startswith("2026-10-20T09:15:30.010")
    assert document["client_ts"] == "2026-10-20T14:45:29+05:30"  # stored exactly as sent
    assert document["received_at"] == "now"
    assert {k: v for k, v in document.items() if k not in {"server_ts", "received_at"}} == {
        k: v for k, v in event.items() if k != "server_ts"
    }


# --- the token ---------------------------------------------------------------------


def test_the_right_bearer_token_is_accepted() -> None:
    assert token_ok(Settings(ingest_token="s3cret"), "Bearer s3cret")


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", "s3cret", "Basic s3cret"])
def test_a_missing_or_wrong_token_is_refused(header) -> None:
    assert not token_ok(Settings(ingest_token="s3cret"), header)


def test_no_configured_token_refuses_everything() -> None:
    assert not token_ok(Settings(ingest_token=""), "Bearer ")


# --- ENG-04 items 4 and 6: duplicates and the reply (store faked) --------------------------


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    stored: set[str] = set()

    async def insert_events(settings, documents):
        new = [d["event_id"] for d in documents if d["event_id"] not in stored]
        stored.update(new)
        return new, [d["event_id"] for d in documents if d["event_id"] not in new]

    monkeypatch.setattr(ingest_module.writers, "insert_events", insert_events)
    return stored


async def test_the_reply_counts_accepted_duplicates_and_rejected(fake_store) -> None:
    good = impression()
    batch = {"events": [good, dict(good), impression(position=0), social()]}

    reply = (await ingest(Settings(), batch)).reply()

    assert reply["accepted"] == 2
    assert reply["duplicates"] == 1  # the same event twice in one batch
    assert len(reply["rejected"]) == 1 and "position 0" in reply["rejected"][0]["reason"]


async def test_the_same_batch_twice_is_all_duplicates_the_second_time(fake_store) -> None:
    """The other half of the Build List's check, with the store faked."""
    batch = {"events": [impression(), social(), impression()]}

    first = (await ingest(Settings(), batch)).reply()
    second = (await ingest(Settings(), batch)).reply()

    assert first == {"accepted": 3, "duplicates": 0, "rejected": []}
    assert second == {"accepted": 0, "duplicates": 3, "rejected": []}


# --- against a real database -------------------------------------------------------------


@pytest.fixture
async def events_store(settings: Settings):
    from reco.store import connection as store_conn
    from reco.store.writers import ensure_engine_collections

    store_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    await store_conn.ml_db(settings)["ml_events"].drop()
    await ensure_engine_collections(settings)  # the unique event_id index
    try:
        yield store_conn.ml_db(settings)["ml_events"]
    finally:
        await store_conn.ml_db(settings)["ml_events"].drop()
        await store_conn.close_client()


@pytest.mark.mongo
async def test_eng04_check_against_the_database(settings: Settings, events_store) -> None:
    """The Build List check, end to end on a real ml_events with its unique index."""
    batch = {"events": [impression(), social(), impression(position=0)]}

    first = (await ingest(settings, batch)).reply()
    second = (await ingest(settings, batch)).reply()

    assert first["accepted"] == 2 and first["duplicates"] == 0
    assert second["accepted"] == 0 and second["duplicates"] == 2  # all duplicates
    assert [r["reason"] for r in second["rejected"]] == [
        "position 0 is not allowed: positions count from 1"
    ]
    assert await events_store.count_documents({}) == 2  # stored once each
