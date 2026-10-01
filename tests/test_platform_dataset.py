"""ENG-29: the adapters, checked on the constructed test-environment data.

The Build List's check: "Unit tests: an unmapped category is reported; a test
account is left out of scoring; an order with tracking_info and a return
request reads correctly; a product post on a feed list keeps post_id and
product_id apart; rec_serve_log rows are copied. The test environment holds the
constructed data."
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio

from reco.config import PLATFORM_COLLECTIONS, live
from reco.config.accounts import is_exempt, is_test_account
from reco.config.tunables import OrderStatusValues
from reco.platform import connection as platform_conn
from reco.platform import fetch, records
from reco.platform.categories import ProductCategoryIndex
from reco.platform.readers import vocabulary
from reco.store import connection as store_conn
from reco.store import writers
from reco.sync import run
from tests.conftest import put_in_force
from tests.platform_dataset import build_dataset

KIND_OF = {name: kind for kind, name in PLATFORM_COLLECTIONS.items()}


def parse_everything(dataset: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Every constructed document through its ENG-03 parser. Returns what failed."""
    from reco.config import Settings

    vocab = vocabulary(Settings())
    index = ProductCategoryIndex.build(vocab, dataset["categories"])
    failures = []
    for collection, documents in dataset.items():
        kind = KIND_OF[collection]
        if kind == "follower":
            continue  # no parser yet: blocks are read by ENG-08 (shape: question 16)
        for doc in documents:
            try:
                if kind in {"user", "business", "post", "category"}:
                    getattr(records, f"parse_{kind}")(doc, vocab)
                elif kind == "product":
                    records.parse_product(doc, index)
                else:
                    getattr(records, f"parse_{kind}")(doc)
            except Exception as exc:  # pragma: no cover - reported, not raised
                failures.append(f"{collection} {doc['_id']}: {exc}")
    return failures


DATA, CASES = build_dataset()


def entry(key: str, days: int = 30) -> dict:
    return {"account_id": str(CASES[key]), "reason": "ENG-29 test", "expiry": date.today() + timedelta(days=days), "changed_by": "Allen"}


def test_every_constructed_document_reads() -> None:
    assert parse_everything(DATA) == []
    assert {KIND_OF[name] for name in DATA} == set(PLATFORM_COLLECTIONS)  # every collection the engine reads


# --- item 1: categories ------------------------------------------------------------------


def test_an_unmapped_category_is_left_out_until_the_map_covers_it() -> None:
    from reco.config import Settings
    from reco.platform.categories import canonical_name

    vocab = vocabulary(Settings())
    assert canonical_name(vocab, "Fashion") is None  # not one of the 23 by name: dropped, never guessed
    assert canonical_name(vocab, "Fashion", {"fashion": "Fashion & Apparel"}) == "Fashion & Apparel"
    assert canonical_name(vocab, "Cricket", {"cricket": "Not A Category"}) is None  # the target must be one of the 23


# --- item 2: spellings -------------------------------------------------------------------


def test_status_spellings_map_a_stored_spelling() -> None:
    assert records.status_is("ACTIVATE ", "Activate")
    assert not records.status_is("Activated", "Activate")
    put_in_force({"lists.status_spellings": {"Activated": "activate"}})
    assert records.status_is("Activated", "Activate")
    assert records.spellings_of("activate") == ["activate", "activated"]


# --- item 3: exemption and test-account lists -----------------------------------------------


def test_the_account_lists_respect_expiry() -> None:
    put_in_force({"lists.test_accounts": [entry("test_account"), entry("viewer", days=-1)],
                  "lists.exemptions": [entry("exempt_account")]})
    assert is_test_account(str(CASES["test_account"])) and not is_test_account(str(CASES["viewer"]))  # expired
    assert is_exempt(str(CASES["exempt_account"])) and not is_exempt(str(CASES["test_account"]))


def test_a_list_change_is_a_settings_change_with_who_changed_it() -> None:
    before = live.current()
    after = before.with_changes({"lists.test_accounts": [entry("test_account")]})
    changes = live.differences(before, after)
    assert [c["key"] for c in changes] == ["lists.test_accounts"]  # recorded in ml_config_changes (ENG-02 item 4)
    assert after.lists.test_accounts[0].changed_by == "Allen" and after.lists.test_accounts[0].reason


# --- items 4 and 5: order history and returns --------------------------------------------------


def _order(key: str) -> records.OrderRecord:
    doc = next(o for o in DATA["orders"] if o["_id"] == CASES[key])
    return records.parse_order(doc, OrderStatusValues())


def test_an_order_with_tracking_info_and_a_return_request_reads_correctly() -> None:
    order = _order("order_return_requested")
    assert [e.stage for e in order.tracking] == ["created", "delivered", "return_requested"]
    assert order.delivered_at is not None and order.return_requested_at is not None
    assert order.delivered_at < order.return_requested_at and order.is_returned
    assert order.tracking[-1].actor == "buyer"


def test_the_first_delivery_is_kept_from_free_text_entries() -> None:
    order = _order("order_delivered")
    assert order.tracking[-1].status.startswith("Delivered (") and order.delivered_at == order.tracking[-1].at
    assert not order.is_returned and order.cancelled_by is None


def test_a_cancellation_reads_who_acted_and_keeps_the_reason_unscored() -> None:
    order = _order("order_cancelled_by_seller")
    assert order.cancelled_by == "seller" and order.cancelled_at is not None
    assert order.cancel_reasons == {"reject_reason_by_buyer": "out of stock"}


def test_a_tracking_entry_by_buyer_decides_when_the_status_fields_do_not() -> None:
    doc = {"_id": CASES["order_pending"], "order_status": "Pending", "buyer_approval_status": "Pending",
           "tracking_info": [{"status": "Cancelled by buyer", "timestamp": "2026-09-30T10:00:00Z"}]}
    assert records.parse_order(doc, OrderStatusValues()).cancelled_by == "buyer"


# --- item 6: item identity -----------------------------------------------------------------


def test_a_product_post_on_a_feed_list_keeps_post_id_and_product_id_apart() -> None:
    doc = next(e for e in DATA["postevents"] if e["_id"] == CASES["feed_product_click"])
    event = records.parse_postevent(doc)
    assert event.item_id == str(CASES["product_post"]) and event.post_id == str(CASES["product_post"])
    assert event.product_id == str(CASES["product"]) and event.post_id != event.product_id


# --- item 7: rec_serve_log -----------------------------------------------------------------


def test_a_serve_log_row_reads() -> None:
    row = records.parse_serve_log(DATA["rec_serve_log"][0])
    assert (row.origin, row.outcome, row.elapsed_ms, row.surface, row.page) == ("fallback", "timeout", 251, "feed", 1)
    assert row.created_at is not None


# --- against a database: the test environment, scoring, the sync ----------------------------------


@pytest_asyncio.fixture
async def seeded(settings):
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    platform = platform_conn.app_db(settings)
    engine = store_conn.ml_db(settings)
    for name, docs in DATA.items():
        await platform[name].drop()
        await platform[name].insert_many(docs)
    for name in ("ml_events", "ml_orders", "ml_sync_state", "ml_job_runs", "ml_measurements"):
        await engine[name].drop()
    await writers.ensure_engine_collections(settings)
    yield settings, platform, engine
    for name in DATA:
        await platform[name].drop()
    for name in ("ml_events", "ml_orders", "ml_sync_state", "ml_job_runs", "ml_measurements"):
        await engine[name].drop()
    await platform_conn.close_client()
    await store_conn.close_client()


@pytest.mark.mongo
async def test_rec_serve_log_rows_are_copied(seeded) -> None:
    settings, _, engine = seeded
    await run.sync_once(settings)
    # The append-only overlap re-reads recent rows on purpose; copies are keyed on _id.
    rows = await engine["ml_events"].find({"source": "rec_serve_log"}).to_list(None)
    assert len(rows) == 3
    assert sorted(r["origin"] for r in rows) == ["cache", "engine", "fallback"] and all(r["event_type"] == "serve_log" for r in rows)
    order = await engine["ml_orders"].find_one({"_id": CASES["order_return_requested"]})
    assert order["is_returned"] and order["return_requested_at"] is not None


@pytest.mark.mongo
async def test_an_unmapped_category_is_reported(seeded) -> None:
    settings, _, _ = seeded
    labels = {row["label"]: row for row in await fetch.unmapped_categories(settings)}
    assert "Cricket" in labels and labels["Cricket"]["used_by"] == {"posts": 1}
    assert "Fashion" in labels  # user interest, business category and the products' category tree
    assert "(no category id)" in labels
    put_in_force({"lists.category_map": {"Fashion": "Fashion & Apparel", "Cricket": "Sports & Outdoors"}})
    still = {row["label"] for row in await fetch.unmapped_categories(settings)}
    assert "Fashion" not in still and "Cricket" not in still


@pytest.mark.mongo
async def test_a_test_account_is_left_out_of_scoring(seeded, monkeypatch) -> None:
    settings, _, _ = seeded
    from reco.jobs import refresh as refresh_module
    from reco.slots.interest.events import ReadStats

    async def events_by_user(settings, reference_date):
        return {}, ReadStats()

    async def nothing(settings):
        return {}

    async def all_users(settings):
        return [str(u["_id"]) for u in DATA["users"]]

    monkeypatch.setattr(refresh_module.readers, "read_events_by_user", events_by_user)
    monkeypatch.setattr(refresh_module.readers, "read_all_declared_interests", nothing)
    monkeypatch.setattr(refresh_module.readers, "read_all_order_creation_times", nothing)
    monkeypatch.setattr(refresh_module.readers, "read_all_user_ids", all_users)
    put_in_force({"lists.test_accounts": [entry("test_account")]})

    result = await refresh_module.refresh(settings)

    assert result.test_accounts_skipped == 1
    assert result.users_seen == len(DATA["users"]) - 1
