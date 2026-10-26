"""ENG-30 point 4: commission settings merged per product (for ENG-18, M6); and point 5's
daily report of order-history texts that match nothing.

ENG-30's check (commission): "a store row with enabled false and a product row with
poolPercent 15 merge as expected; a missing field falls through to the level below;
poolPercent 60 is ignored and logged; two rows with the same scope and scopeId
resolve to the later one; with commissionconfigs unreadable the M6 job does not run."
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from reco.platform import commission
from reco.platform.commission import CommissionRules, CommissionUnreadable, load_commission

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
DEFAULTS = {"enabled": True, "poolPercent": 10, "minOrderAmount": 0, "holdDays": 7}


def rules(*rows):
    return CommissionRules.from_rows(rows, DEFAULTS)


def test_the_defaults_are_the_settings_sheets(settings) -> None:
    assert commission.defaults_in_force() == {"enabled": True, "poolPercent": 10, "minOrderAmount": 0, "holdDays": 7}


def test_store_disabled_and_product_15_merge_field_by_field() -> None:
    r = rules({"scope": "platform", "scopeId": None, "poolPercent": 12, "holdDays": 5},
              {"scope": "seller", "scopeId": "s1", "enabled": False},
              {"scope": "product", "scopeId": "p1", "poolPercent": 15})
    merged, sources = r.for_product("p1", "s1")
    assert merged == {"enabled": False, "poolPercent": 15, "minOrderAmount": 0, "holdDays": 5}
    assert sources == {"enabled": "seller", "poolPercent": "product", "minOrderAmount": "default", "holdDays": "platform"}


def test_a_missing_field_falls_through_to_the_level_below() -> None:
    r = rules({"scope": "platform", "scopeId": None, "poolPercent": 12},
              {"scope": "product", "scopeId": "p1", "holdDays": 3})
    merged, _ = r.for_product("p1", "s1")
    assert merged["poolPercent"] == 12 and merged["holdDays"] == 3 and merged["enabled"] is True


def test_another_store_or_product_does_not_apply() -> None:
    r = rules({"scope": "seller", "scopeId": "s2", "poolPercent": 30}, {"scope": "product", "scopeId": "p2", "poolPercent": 40})
    assert r.for_product("p1", "s1")[0]["poolPercent"] == 10


@pytest.mark.parametrize("field, value", [
    ("poolPercent", 60), ("poolPercent", -1), ("minOrderAmount", -5), ("enabled", "yes"), ("enabled", 1), ("holdDays", -2),
    ("poolPercent", "15"),
])
def test_a_value_out_of_range_is_ignored_and_logged(field, value, caplog) -> None:
    r = rules({"scope": "platform", "scopeId": None, "poolPercent": 12, "enabled": True, "minOrderAmount": 0, "holdDays": 7},
              {"scope": "product", "scopeId": "p1", field: value})
    with caplog.at_level(logging.WARNING, logger="reco.commission"):
        merged, sources = r.for_product("p1", "s1")
    assert merged[field] == {"poolPercent": 12, "enabled": True, "minOrderAmount": 0, "holdDays": 7}[field]
    assert sources[field] == "platform"  # the level below applies
    assert any(getattr(rec, "field", None) == field for rec in caplog.records)


def test_poolpercent_0_and_50_are_allowed() -> None:
    assert rules({"scope": "product", "scopeId": "p1", "poolPercent": 50}).for_product("p1", None)[0]["poolPercent"] == 50
    assert rules({"scope": "product", "scopeId": "p1", "poolPercent": 0}).for_product("p1", None)[0]["poolPercent"] == 0


def test_two_rows_with_the_same_scope_resolve_to_the_later_one(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="reco.commission"):
        r = rules({"scope": "seller", "scopeId": "s1", "poolPercent": 5, "updatedAt": T0 + timedelta(days=2)},
                  {"scope": "seller", "scopeId": "s1", "poolPercent": 8, "updatedAt": T0})
    assert r.for_product("p1", "s1")[0]["poolPercent"] == 5 and r.duplicates == 1
    assert any("later updatedAt wins" in rec.getMessage() for rec in caplog.records)


def test_a_row_with_an_unknown_scope_is_ignored() -> None:
    r = rules({"scope": "collaboration", "scopeId": "x", "poolPercent": 40})
    assert r.unknown_scope == 1 and r.for_product("p1", "s1")[0]["poolPercent"] == 10


async def test_unreadable_commissionconfigs_raise_so_m6_does_not_run(monkeypatch, settings) -> None:
    async def refused(settings):
        raise PermissionError("not authorized on soco to execute command find")

    monkeypatch.setattr(commission.fetch, "read_commission_configs", refused)
    with pytest.raises(CommissionUnreadable):
        await load_commission(settings)  # the defaults never stand in for rows that could not be read


async def test_load_merges_what_it_reads(monkeypatch, settings) -> None:
    async def rows(settings):
        return [{"scope": "platform", "scopeId": None, "poolPercent": 10}, {"scope": "seller", "scopeId": "s1", "poolPercent": 5}]

    monkeypatch.setattr(commission.fetch, "read_commission_configs", rows)
    loaded = await load_commission(settings)
    assert loaded.for_product("p1", "s1")[0]["poolPercent"] == 5


# --- point 5: the daily report of history texts that match nothing -----------------------------


async def test_unmatched_history_texts_are_reported_daily(monkeypatch, settings) -> None:
    from reco.jobs import category_check

    recorded, alerts = [], []

    async def unmatched(settings):
        return [{"text": "Parcel lost in transit", "orders": 2}]

    async def record(settings, key, fields):
        recorded.append((key, fields))

    monkeypatch.setattr(category_check.writers, "read_unmatched_history", unmatched)
    monkeypatch.setattr(category_check.writers, "record_measurement", record)
    monkeypatch.setattr(category_check, "alert", lambda *a, **k: alerts.append((a, k)))
    out = await category_check.check_history_texts(settings)
    assert out[0]["text"] == "Parcel lost in transit"
    assert recorded[0][0]["measure"] == "unmatched_history_texts" and recorded[0][1]["count"] == 1
    assert alerts and alerts[0][1]["texts"] == ["Parcel lost in transit"]


# --- on a database: commissionconfigs read in full ---------------------------------------------


@pytest.mark.mongo
async def test_commission_rows_are_read_from_the_platform(store) -> None:
    from pymongo import AsyncMongoClient

    from tests.conftest import TEST_PLATFORM_DB, _test_uri

    client = AsyncMongoClient(_test_uri())
    configs = client[TEST_PLATFORM_DB]["commissionconfigs"]
    await configs.delete_many({})
    await configs.insert_many([
        {"scope": "platform", "scopeId": None, "enabled": True, "poolPercent": 10, "repostSharePercent": 50, "updatedAt": T0},
        {"scope": "seller", "scopeId": "s1", "enabled": False, "updatedAt": T0},
        {"scope": "product", "scopeId": "p1", "poolPercent": 15, "updatedAt": T0},
    ])
    try:
        loaded = await load_commission(store)
        merged, _ = loaded.for_product("p1", "s1")
        assert merged == {"enabled": False, "poolPercent": 15, "minOrderAmount": 0, "holdDays": 7}
        assert "repostSharePercent" not in loaded.rows[("platform", None)]  # only the fields the engine uses are read
    finally:
        await configs.delete_many({})
        await client.close()
