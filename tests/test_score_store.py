"""The score store against a live MongoDB. ST3, ST4, ST7, ST8, ST9.

Skips cleanly when Mongo is unreachable -- see the `store` fixture.
"""

from __future__ import annotations

import pytest
from pymongo.errors import DuplicateKeyError

from reco.data.mongo import ml_db
from reco.data.writers import (
    delete_user_scores,
    read_user_scores,
    upsert_score,
    upsert_user_scores,
)
from reco.domain.scores import Method, Window, utc_now
from tests.conftest import make_score, make_user_map

pytestmark = pytest.mark.mongo


async def test_upsert_then_read_back(store) -> None:
    await upsert_score(store, make_score(raw=42.5, share=1.0))

    scores = await read_user_scores(store, "u1", Method.RECENCY_DECAY)

    assert len(scores) == 1
    assert scores[0].raw == 42.5
    assert scores[0].category == "fashion & apparel"
    assert scores[0].window == Window.ALL


async def test_upsert_is_idempotent(store) -> None:
    """ST7. Same key twice leaves one document carrying the second's values."""
    await upsert_score(store, make_score(raw=10.0, event_count=1))
    await upsert_score(store, make_score(raw=99.0, event_count=12))

    scores = await read_user_scores(store, "u1", Method.RECENCY_DECAY)

    assert len(scores) == 1
    assert scores[0].raw == 99.0
    assert scores[0].event_count == 12


async def test_two_methods_coexist_for_one_user_and_category(store) -> None:
    """ST4, and the reason method is in the unique key at all.

    Both methods compute a score for every user. If one overwrote the other the
    comparison the whole of M1 exists to make would be impossible.
    """
    await upsert_score(store, make_score(method=Method.RECENCY_DECAY, raw=42.5))
    await upsert_score(
        store,
        make_score(method=Method.TIME_WINDOWS, window=Window.LAST_90_DAYS, raw=17.0),
    )

    method_a = await read_user_scores(store, "u1", Method.RECENCY_DECAY)
    method_b = await read_user_scores(store, "u1", Method.TIME_WINDOWS)

    assert len(method_a) == 1 and method_a[0].raw == 42.5
    assert len(method_b) == 1 and method_b[0].raw == 17.0
    assert await ml_db(store)[store.scores_collection].count_documents({}) == 2


async def test_two_model_versions_coexist(store) -> None:
    """A new model version is a new generation of scores, not an overwrite.

    Without this, rerunning after a parameter change destroys the evidence of
    what the previous configuration produced.
    """
    await upsert_score(store, make_score(model_version="test-1.0.0", raw=10.0))
    await upsert_score(store, make_score(model_version="test-1.1.0", raw=20.0))

    assert await ml_db(store)[store.scores_collection].count_documents({}) == 2

    old = await read_user_scores(store, "u1", Method.RECENCY_DECAY, "test-1.0.0")
    assert old[0].raw == 10.0


async def test_unique_index_rejects_a_duplicate_insert(store) -> None:
    """ST4. The uniqueness is the database's, not only the writer's.

    An upsert would not reveal this; a raw insert of the same key must fail.
    """
    document = make_score().to_document()
    await ml_db(store)[store.scores_collection].insert_one(dict(document))

    with pytest.raises(DuplicateKeyError):
        await ml_db(store)[store.scores_collection].insert_one(dict(document))


async def test_indexes_exist(store) -> None:
    names = await ml_db(store)[store.scores_collection].index_information()

    assert "uniq_user_category_method_version" in names
    assert names["uniq_user_category_method_version"].get("unique") is True
    assert "user_method_recency" in names


async def test_bulk_upsert_writes_a_whole_user_map(store) -> None:
    """ST8. The refresh path writes per user, not per category."""
    shares = {
        "fashion & apparel": 0.4,
        "electronics": 0.3,
        "home & living": 0.2,
        "books": 0.1,
    }
    written = await upsert_user_scores(store, "u1", make_user_map("u1", shares))

    stored = await read_user_scores(store, "u1", Method.RECENCY_DECAY)

    assert written == 4
    assert len(stored) == 4
    assert {s.category for s in stored} == set(shares)
    assert stored[0].category == "fashion & apparel"  # sorted by share desc
    assert abs(sum(s.share for s in stored) - 1.0) < 1e-9


async def test_bulk_upsert_replaces_a_previous_run(store) -> None:
    """A second refresh updates in place rather than doubling the documents."""
    first = make_user_map("u1", {"electronics": 0.6, "books": 0.4})
    await upsert_user_scores(store, "u1", first)

    second = make_user_map("u1", {"electronics": 0.9, "books": 0.1})
    await upsert_user_scores(store, "u1", second)

    stored = await read_user_scores(store, "u1", Method.RECENCY_DECAY)
    by_category = {s.category: s.share for s in stored}

    assert len(stored) == 2
    assert by_category["electronics"] == pytest.approx(0.9)


async def test_read_is_filtered_by_method(store) -> None:
    """ST9. What the display and the data checks consume."""
    await upsert_user_scores(
        store, "u1", make_user_map("u1", {"electronics": 1.0}, method=Method.RECENCY_DECAY)
    )
    await upsert_user_scores(
        store,
        "u1",
        make_user_map(
            "u1",
            {"books": 1.0},
            method=Method.TIME_WINDOWS,
            window=Window.LAST_90_DAYS,
        ),
    )

    method_b = await read_user_scores(store, "u1", Method.TIME_WINDOWS)

    assert [s.category for s in method_b] == ["books"]


async def test_read_does_not_leak_other_users(store) -> None:
    await upsert_user_scores(store, "u1", make_user_map("u1", {"electronics": 1.0}))
    await upsert_user_scores(store, "u2", make_user_map("u2", {"books": 1.0}))

    assert len(await read_user_scores(store, "u1", Method.RECENCY_DECAY)) == 1


async def test_read_of_unknown_user_returns_empty(store) -> None:
    """Not an error, and not a fabricated uniform map. The ladder handles it."""
    assert await read_user_scores(store, "nobody", Method.RECENCY_DECAY) == []


async def test_delete_removes_only_that_method(store) -> None:
    await upsert_score(store, make_score(method=Method.RECENCY_DECAY))
    await upsert_score(
        store, make_score(method=Method.TIME_WINDOWS, window=Window.LAST_90_DAYS)
    )

    deleted = await delete_user_scores(store, "u1", Method.RECENCY_DECAY)

    assert deleted == 1
    assert len(await read_user_scores(store, "u1", Method.TIME_WINDOWS)) == 1


async def test_stale_categories_are_removed_by_a_later_run(store) -> None:
    """A category a user stops scoring in must not linger.

    An upsert alone leaves it behind, and a stale row is worse than a missing
    one: the surviving rows were normalised over a new total, so the stale row's
    share was computed against a denominator that no longer exists and the set
    stops summing to 1.

    Real cause: U08 scored three seller-created categories until resolution was
    fixed. The fix stopped writing them; nothing removed the rows already there.
    """
    from datetime import timedelta

    from reco.data.writers import remove_scores_older_than

    first_run = utc_now() - timedelta(hours=1)
    await upsert_user_scores(
        store,
        "u1",
        make_user_map(
            "u1",
            {"electronics": 0.5, "casual sneakers": 0.5},
            computed_at=first_run,
        ),
    )

    second_run = utc_now()
    await upsert_user_scores(
        store, "u1", make_user_map("u1", {"electronics": 1.0}, computed_at=second_run)
    )

    removed = await remove_scores_older_than(
        store, Method.RECENCY_DECAY, store.model_version, second_run
    )

    stored = await read_user_scores(store, "u1", Method.RECENCY_DECAY)
    assert removed == 1
    assert [s.category for s in stored] == ["electronics"]
    assert sum(s.share for s in stored) == pytest.approx(1.0)


async def test_the_sweep_leaves_other_methods_alone(store) -> None:
    """Method B's rows were written by a different run at a different instant.
    Sweeping by timestamp alone would delete them."""
    from datetime import timedelta

    from reco.data.writers import remove_scores_older_than

    old = utc_now() - timedelta(hours=1)
    await upsert_user_scores(
        store,
        "u1",
        make_user_map(
            "u1",
            {"books": 1.0},
            method=Method.TIME_WINDOWS,
            window=Window.LAST_90_DAYS,
            computed_at=old,
        ),
    )

    await remove_scores_older_than(
        store, Method.RECENCY_DECAY, store.model_version, utc_now()
    )

    assert len(await read_user_scores(store, "u1", Method.TIME_WINDOWS)) == 1


async def test_stored_document_carries_all_four_metadata_fields(store) -> None:
    """The point of RE-02, asserted against what actually landed in Mongo."""
    await upsert_score(store, make_score())

    document = await ml_db(store)[store.scores_collection].find_one({"user_id": "u1"})

    for field in ("method", "model_version", "window", "computed_at"):
        assert document.get(field) is not None, f"{field} missing from stored document"
    assert document["computed_at"].tzinfo is not None
