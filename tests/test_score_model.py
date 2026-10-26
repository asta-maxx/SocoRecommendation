"""The score document rejects what it must. ST2 and the §2 edge rules.

These need no database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from reco.store.scores import (
    InterestScore,
    Method,
    ScoreBatch,
    Window,
    normalise_to_shares,
    utc_now,
)
from tests.conftest import make_score, make_user_map

METADATA_FIELDS = ["method", "model_version", "window", "computed_at"]


@pytest.mark.parametrize("field", METADATA_FIELDS)
def test_missing_metadata_field_raises(field: str) -> None:
    """ST2. Each of the four, omitted in turn -- four cases, not one.

    A single test omitting all four would pass even if three of them had quietly
    acquired a default.
    """
    fields = make_score().model_dump()
    del fields[field]

    with pytest.raises(ValidationError) as exc:
        InterestScore(**fields)

    assert field in str(exc.value)


@pytest.mark.parametrize("field", METADATA_FIELDS)
def test_null_metadata_field_raises(field: str) -> None:
    """Non-nullable, not merely required. None must fail as hard as absence."""
    fields = make_score().model_dump()
    fields[field] = None

    with pytest.raises(ValidationError):
        InterestScore(**fields)


def test_naive_computed_at_raises() -> None:
    """A naive timestamp silently breaks the P-08 staleness comparison."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_score(computed_at=datetime(2026, 9, 10, 12, 0, 0))


def test_computed_at_normalised_to_utc() -> None:
    """An aware non-UTC timestamp is accepted and converted, not rejected."""
    ist = timezone(timedelta(hours=5, minutes=30))
    score = make_score(computed_at=datetime(2026, 9, 10, 17, 30, tzinfo=ist))

    assert score.computed_at == datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("share", [-0.1, 1.4, 2.0])
def test_share_outside_unit_range_raises(share: float) -> None:
    with pytest.raises(ValidationError, match="share"):
        make_score(share=share)


def test_negative_raw_raises() -> None:
    """Cannot occur if the purchase reversal is aged from the original order.

    If this ever fires in production it is that bug, not a validation nuisance.
    """
    with pytest.raises(ValidationError, match="negative"):
        make_score(raw=-15.16)


def test_negative_event_count_raises() -> None:
    with pytest.raises(ValidationError):
        make_score(event_count=-1)


@pytest.mark.parametrize(
    "supplied",
    ["Fashion & Apparel", "fashion & apparel", "home & decor", "home_&_living", "Casual Sneakers"],
)
def test_the_category_is_stored_exactly_as_supplied(supplied: str) -> None:
    """The score map is keyed on whatever string the source gave.

    An earlier version required toCategoryKey() shape -- lowercase, no
    underscores -- and would have refused almost every real score: the data is
    title case, and U06 and U08 carry legacy and unmappable values on purpose.
    Constraining it here would also have created a fourth category vocabulary.
    """
    assert make_score(category=supplied).category == supplied


def test_unknown_field_rejected() -> None:
    """extra='forbid'. A typo'd field name must not land silently in the store."""
    with pytest.raises(ValidationError):
        InterestScore(**{**make_score().model_dump(), "modelVersion": "1.0.0"})


def test_key_includes_method_and_model_version() -> None:
    """ST4. Both are part of the identity of a score; ENG-07 adds the batch."""
    assert set(make_score().key()) == {
        "user_id",
        "category",
        "method",
        "model_version",
        "job_run_id",
    }


def test_to_document_writes_enums_as_plain_strings() -> None:
    """The collection must stay readable to the Node backend and to mongosh."""
    document = make_score().to_document()

    assert document["method"] == "recency_decay"
    assert document["window"] == "all"
    assert isinstance(document["method"], str)
    assert set(document) == {
        "user_id",
        "category",
        "raw",
        "share",
        "event_count",
        "method",
        "model_version",
        "window",
        "computed_at",
        # ENG-07: provenance on every row
        "score",
        "slot",
        "confidence",
        "config_version",
        "data_window",
        "job_run_id",
        # Kala 2a (16 Oct): the user's qualified actions
        "qualified_actions",
    }


def test_from_document_round_trips() -> None:
    original = make_score()
    rebuilt = InterestScore.from_document({"_id": "ignored", **original.to_document()})

    assert rebuilt == original


# --- shares -----------------------------------------------------------------


def test_normalise_to_shares_sums_to_one() -> None:
    shares = normalise_to_shares({"fashion & apparel": 30.0, "electronics": 10.0})

    assert shares == {"fashion & apparel": 0.75, "electronics": 0.25}


def test_zero_total_raw_yields_no_shares() -> None:
    """§ 'Never fabricate a uniform share'.

    A uniform distribution is indistinguishable from a genuine even spread of
    interest and hides that the user is unknown. Store nothing; let the
    cold-start ladder answer.
    """
    assert normalise_to_shares({"fashion & apparel": 0.0, "electronics": 0.0}) == {}
    assert normalise_to_shares({}) == {}


# --- batches ----------------------------------------------------------------


def test_batch_shares_must_sum_to_one() -> None:
    scores = make_user_map("u1", {"electronics": 0.5, "books": 0.2})

    with pytest.raises(ValidationError, match="sum to 1"):
        ScoreBatch(user_id="u1", scores=scores)


def test_batch_rejects_mixed_methods() -> None:
    """Shares from two methods were normalised over different totals. Summing
    them is meaningless, and storing them as one batch hides that.
    """
    scores = [
        make_score(category="electronics", share=0.5, method=Method.RECENCY_DECAY),
        make_score(
            category="books",
            share=0.5,
            method=Method.TIME_WINDOWS,
            window=Window.LAST_90_DAYS,
        ),
    ]

    with pytest.raises(ValidationError, match="one method"):
        ScoreBatch(user_id="u1", scores=scores)


def test_batch_rejects_repeated_category() -> None:
    scores = [
        make_score(category="electronics", share=0.5),
        make_score(category="electronics", share=0.5),
    ]

    with pytest.raises(ValidationError, match="repeat a category"):
        ScoreBatch(user_id="u1", scores=scores)


def test_batch_rejects_foreign_user() -> None:
    scores = make_user_map("u1", {"electronics": 1.0})

    with pytest.raises(ValidationError, match="carries a score for"):
        ScoreBatch(user_id="u2", scores=scores)


def test_batch_of_one_full_share_is_valid() -> None:
    batch = ScoreBatch(user_id="u1", scores=make_user_map("u1", {"electronics": 1.0}))

    assert len(batch.scores) == 1
    assert batch.scores[0].computed_at <= utc_now()
