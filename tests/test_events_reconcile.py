"""ENG-04 item 7: the daily reconciliation, and the switch date after 7 matching days."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from reco.events import reconcile
from reco.events.reconcile import compare
from reco.platform.records import LegacyClickRecord, LegacyRequestRecord

DAY = date(2026, 10, 12)
T = datetime(2026, 10, 12, 9, 15, 31, 2000, tzinfo=timezone.utc)


def click(i: int, *, at: datetime = T, request_id: str | None = "r1", position: int = 1,
          item_type: str = "post", item: str | None = None) -> LegacyClickRecord:
    return LegacyClickRecord(request_id=request_id, user_id=f"u{i}", item_id=item or f"i{i}",
                             item_type=item_type, position=position, at=at)


def same_clicks(n: int) -> list[LegacyClickRecord]:
    return [click(i) for i in range(n)]


# --- the three tests -----------------------------------------------------------------


def test_identical_days_hold() -> None:
    result = compare("click", same_clicks(50), same_clicks(50), DAY)
    assert result.holds and result.sample_matched == 50 and not result.problems


def test_counts_within_one_percent_hold_and_beyond_do_not() -> None:
    assert compare("click", same_clicks(100), same_clicks(101), DAY).counts_match  # 1 in 101
    assert not compare("click", same_clicks(100), same_clicks(103), DAY).counts_match


def test_complete_row_shares_must_match_within_one_percent() -> None:
    new = same_clicks(100)
    old = same_clicks(90) + [click(i, request_id=None) for i in range(90, 100)]  # 90% complete
    result = compare("click", new, old, DAY)
    assert not result.shares_match and not result.holds


def test_the_sample_matches_time_to_the_second() -> None:
    """Old rows stamped a few milliseconds apart still match; a second apart do not."""
    old_ms = [click(i, at=T.replace(microsecond=900_000)) for i in range(20)]
    assert compare("click", same_clicks(20), old_ms, DAY).sample_agrees
    old_s = [click(i, at=T + timedelta(seconds=1)) for i in range(20)]
    assert not compare("click", same_clicks(20), old_s, DAY).sample_agrees


@pytest.mark.parametrize("field,value", [("request_id", "other"), ("position", 2), ("item_type", "product")])
def test_matched_pairs_must_agree_on_request_position_and_type(field: str, value) -> None:
    old = same_clicks(10)
    old[3] = old[3].model_copy(update={field: value})
    result = compare("click", same_clicks(10), old, DAY)
    assert not result.sample_agrees and any(field in p for p in result.problems)


def test_matching_is_one_to_one() -> None:
    """Two identical new events need two old rows; one old row is not enough."""
    new = [click(1), click(1)]
    result = compare("click", new, [click(1)], DAY)
    assert result.sample_matched == 1 and not result.sample_agrees


def test_the_sample_is_at_most_100_and_repeatable() -> None:
    first = compare("click", same_clicks(250), same_clicks(250), DAY)
    again = compare("click", same_clicks(250), same_clicks(250), DAY)
    assert first.sampled == 100 and first.as_dict() == again.as_dict()


def test_requests_have_no_item_so_match_on_user_and_time() -> None:
    new = [LegacyRequestRecord(request_id=f"r{i}", user_id=f"u{i}", surface="feed", policy_id="p",
                               candidate_ids=[], at=T) for i in range(5)]
    assert compare("request", new, list(new), DAY).holds


def test_an_empty_pair_passes_but_a_day_with_no_rows_is_not_evidence() -> None:
    assert compare("content_feedback", [], [], DAY).holds


# --- the switch date, against a real database ----------------------------------------------


@pytest.fixture
async def reconcile_store(settings):
    from reco.platform import connection as platform_conn
    from reco.store import connection as store_conn
    from reco.store.writers import ensure_engine_collections

    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    engine = store_conn.ml_db(settings)
    platform_copy = store_conn._client[settings.app_mongo_db]  # the throwaway test copy
    for name in ("ml_events", "ml_measurements"):
        await engine[name].drop()
    await platform_copy["recommendationclicks"].drop()
    await ensure_engine_collections(settings)
    try:
        yield engine, platform_copy
    finally:
        for name in ("ml_events", "ml_measurements"):
            await engine[name].drop()
        await platform_copy["recommendationclicks"].drop()
        await platform_conn.close_client()
        await store_conn.close_client()


async def _seed_day(engine, platform_copy, day: date, n: int = 5) -> None:
    for i in range(n):
        at = datetime(day.year, day.month, day.day, 10, i, 5, tzinfo=timezone.utc)
        row = {"request_id": f"r-{day}-{i}", "item_id": f"6a3fe5cfcce0b0785136e7f{i}", "item_type": "post",
               "position": i + 1, "user_id": "65f1a2b3c4d5e6f708192a3b", "server_ts": at}
        await platform_copy["recommendationclicks"].insert_one(dict(row))
        await engine["ml_events"].insert_one(
            {**row, "event_id": f"e-{day}-{i}", "event_name": "recommendation_click"})


@pytest.mark.mongo
async def test_seven_matching_days_fix_the_switch_date(settings, reconcile_store) -> None:
    engine, platform_copy = reconcile_store
    first = DAY - timedelta(days=6)
    for offset in range(7):
        day = first + timedelta(days=offset)
        await _seed_day(engine, platform_copy, day)
        result = await reconcile.reconcile_day(settings, day)
        assert result["holds"], result["pairs"]
        expected = None if offset < 6 else DAY
        assert await reconcile.switch_date(settings) == expected  # only on the 7th day

    # A later day never moves it.
    await _seed_day(engine, platform_copy, DAY + timedelta(days=1))
    await reconcile.reconcile_day(settings, DAY + timedelta(days=1))
    assert await reconcile.switch_date(settings) == DAY


@pytest.mark.mongo
async def test_a_failing_day_breaks_the_run(settings, reconcile_store) -> None:
    engine, platform_copy = reconcile_store
    first = DAY - timedelta(days=6)
    for offset in range(7):
        day = first + timedelta(days=offset)
        await _seed_day(engine, platform_copy, day)
        if offset == 3:  # an extra old row the new log never got: counts differ by 20%
            await platform_copy["recommendationclicks"].insert_one(
                {"request_id": "x", "item_id": "i", "item_type": "post", "position": 1,
                 "user_id": "u", "server_ts": datetime(day.year, day.month, day.day, 23, tzinfo=timezone.utc)})
        await reconcile.reconcile_day(settings, day)

    assert await reconcile.switch_date(settings) is None


@pytest.mark.mongo
async def test_days_with_no_events_at_all_do_not_count(settings, reconcile_store) -> None:
    for offset in range(7):
        result = await reconcile.reconcile_day(settings, DAY - timedelta(days=offset))
        assert not result["counted"] and not result["holds"]
    assert await reconcile.switch_date(settings) is None
