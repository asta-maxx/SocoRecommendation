"""The event row contract, enforced rather than merely agreed.

If the generator and the engine drift on a field name, these fail -- which is the
whole point of fixing the five fields in writing before either is built.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from reco.config import Settings
from reco.domain.event_contract import (
    CONDITIONAL_FIELDS,
    CORE_FIELDS,
    ROW_EVENT_TYPES,
    DemoEventRow,
    is_declared_interest_row,
)


def make_row(**overrides) -> DemoEventRow:
    """A valid row, spelled the way the generator actually spells one."""
    fields = {
        "user_id": "U01",
        "event_type": "product_view",
        "categories": ["Fashion & Apparel"],
        "timestamp": datetime.now(timezone.utc) - timedelta(days=1),
        "weight": 2,
        "view_duration_seconds": 7.5,
    }
    fields.update(overrides)
    return DemoEventRow(**{k: v for k, v in fields.items() if v is not None or k in overrides})


# --- the agreed names -------------------------------------------------------


def test_the_five_core_fields_are_exactly_these() -> None:
    """Named, in writing, before anything is built."""
    assert CORE_FIELDS == ("user_id", "event_type", "categories", "timestamp", "weight")


def test_seven_fields_in_total() -> None:
    assert set(DemoEventRow.model_fields) == set(CORE_FIELDS) | set(CONDITIONAL_FIELDS)
    assert len(DemoEventRow.model_fields) == 7


def test_a_renamed_field_is_rejected() -> None:
    """extra='forbid' is what makes the contract binding rather than advisory.

    `eventType` instead of `event_type` would otherwise be written happily and
    read as nothing.
    """
    row = make_row().model_dump()
    row["eventType"] = row.pop("event_type")

    with pytest.raises(ValidationError):
        DemoEventRow(**row)


@pytest.mark.parametrize("field", CORE_FIELDS)
def test_every_core_field_is_required(field: str) -> None:
    row = make_row().model_dump()
    del row[field]

    with pytest.raises(ValidationError):
        DemoEventRow(**row)


# --- categories is plural ---------------------------------------------------


def test_categories_is_plural_and_a_list() -> None:
    """A singular `category` cannot express a multi-category post, which is
    U03's entire purpose.
    """
    assert "category" not in DemoEventRow.model_fields
    assert "categories" in DemoEventRow.model_fields
    assert make_row().categories == ["Fashion & Apparel"]


def test_a_single_category_is_still_an_array() -> None:
    with pytest.raises(ValidationError):
        make_row(categories="fashion & apparel")


def test_multi_category_row_is_valid() -> None:
    row = make_row(categories=["fashion & apparel", "home & living"])

    assert len(row.categories) == 2


def test_empty_categories_is_refused() -> None:
    with pytest.raises(ValidationError):
        make_row(categories=[])


@pytest.mark.parametrize(
    "supplied",
    ["Fashion & Apparel", "home & decor", "home_&_living", "Casual Sneakers"],
)
def test_any_non_blank_category_string_is_accepted(supplied: str) -> None:
    """The contract allows any string; the engine maps or drops.

    U06 carries legacy spellings and U08 carries values with no canonical
    equivalent, both deliberately. Validating the vocabulary here would make
    those two users ungeneratable and delete what they demonstrate.
    """
    assert make_row(categories=[supplied]).categories == [supplied]


def test_a_blank_category_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        make_row(categories=["   "])


# --- the reversal -----------------------------------------------------------


def test_reversal_is_its_own_event_type() -> None:
    assert "purchase_reversal" in ROW_EVENT_TYPES
    assert "is_reversal" not in DemoEventRow.model_fields


def test_purchase_and_reversal_require_an_order_id() -> None:
    for event_type in ("purchase", "purchase_reversal"):
        with pytest.raises(ValidationError, match="order_id"):
            make_row(
                event_type=event_type,
                weight=20,
                view_duration_seconds=None,
                order_id=None,
            )


def test_valid_reversal_row() -> None:
    row = make_row(
        event_type="purchase_reversal",
        weight=-20,
        view_duration_seconds=None,
        order_id="o1",
    )

    assert row.order_id == "o1"


def test_reversal_weight_is_the_purchase_weight_negated() -> None:
    """Not P-07. P-07 is hide/report/skip and is 0 at launch -- multiplying the
    reversal by it would zero the reversal silently.
    """
    tunables = Settings().tunables()
    row = make_row(
        event_type="purchase_reversal",
        weight=-20,
        view_duration_seconds=None,
        order_id="o1",
    )

    assert row.expected_weight(tunables) == -20.0
    assert tunables["P-07"] == 0.0  # and is not involved


def test_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValidationError, match="event_type"):
        make_row(event_type="like")


# --- view_duration_seconds --------------------------------------------------


def test_view_duration_belongs_to_views_only() -> None:
    """A duration on a non-view row invites P-02 being applied wider than it is."""
    with pytest.raises(ValidationError, match="view rows only"):
        make_row(event_type="product_click", weight=5, view_duration_seconds=7.5)


def test_sub_threshold_duration_is_still_a_valid_row() -> None:
    """The generator does not apply P-02 -- U02 needs sub-threshold views to
    exist in the data in order to prove they are excluded from scoring.
    """
    assert make_row(view_duration_seconds=0.5).view_duration_seconds == 0.5


# --- weight is written, never read ------------------------------------------


def test_weight_is_on_the_row() -> None:
    """The data checks need it to do arithmetic a reader can follow."""
    assert "weight" in DemoEventRow.model_fields


def test_weight_never_reaches_the_engine_event() -> None:
    """The engine derives weight from P-06 keyed on event_type. If it read this
    field, P-06 would stop being configuration.
    """
    from reco.domain.events import Event

    assert "weight" not in Event.model_fields


def test_expected_weight_matches_p06_for_every_type() -> None:
    """The one legitimate reading of the field: a check that the generator's
    belief and P-06 agree.
    """
    tunables = Settings().tunables()
    expected = {
        "product_view": 2.0,
        "keyword_search": 3.0,
        "product_click": 5.0,
        "add_to_cart": 10.0,
        "purchase": 20.0,
    }

    for event_type, weight in expected.items():
        row = make_row(
            event_type=event_type,
            weight=weight,
            view_duration_seconds=7.5 if event_type == "product_view" else None,
            order_id="o1" if event_type == "purchase" else None,
        )
        assert row.expected_weight(tunables) == weight


def test_expected_weight_follows_a_retuned_p06() -> None:
    """Proving P-06 really is configuration: change it, and the expectation moves."""
    retuned = Settings(event_weights={"view": 7.0}).tunables()

    assert make_row().expected_weight(retuned) == 7.0  # a product_view row


# --- declared interests must never appear -----------------------------------


def test_home_and_living_is_three_merges_not_four() -> None:
    """DS-008's 'four' counts map entries. Kala ruled three are genuine merges;
    the fourth is an underscore spelling of the canonical label correcting itself.
    """
    from reco.domain.event_contract import (
        HOME_AND_LIVING_MERGES,
        HOME_AND_LIVING_SPELLING_FIX,
    )

    assert len(HOME_AND_LIVING_MERGES) == 3
    assert HOME_AND_LIVING_SPELLING_FIX not in HOME_AND_LIVING_MERGES
    # Four keys point at the category in total.
    assert len(HOME_AND_LIVING_MERGES) + 1 == 4


def test_the_spelling_fix_is_carried_not_rejected() -> None:
    """The underscore form is a legacy spelling to map away.

    It is NOT rejected at read: the engine scores whatever string the source
    supplies and the mapping happens afterwards, which is what lets U06 show the
    repair rather than hiding it behind a validation error.
    """
    from reco.domain.event_contract import HOME_AND_LIVING_SPELLING_FIX

    row = make_row(categories=[HOME_AND_LIVING_SPELLING_FIX])

    assert row.categories == [HOME_AND_LIVING_SPELLING_FIX]


def test_the_three_merges_are_valid_category_keys() -> None:
    """They are toCategoryKey() output -- lowercase, spaces preserved."""
    from reco.domain.event_contract import HOME_AND_LIVING_MERGES

    assert make_row(categories=list(HOME_AND_LIVING_MERGES)).categories == list(
        HOME_AND_LIVING_MERGES
    )


def test_a_row_without_a_timestamp_reads_as_a_declared_interest() -> None:
    """The single easiest thing in the build to get wrong (G6). A declared
    interest in the event stream gets decayed by Method A, which is forbidden.
    """
    assert is_declared_interest_row({"user_id": "U01", "event_type": "product_view"})


@pytest.mark.parametrize(
    "event_type", ["interest", "declared_interest", "signup_interest"]
)
def test_interest_typed_rows_are_detected(event_type: str) -> None:
    assert is_declared_interest_row(
        {"event_type": event_type, "timestamp": datetime.now(timezone.utc)}
    )


def test_an_ordinary_event_is_not_a_declared_interest() -> None:
    assert not is_declared_interest_row(make_row().model_dump())


def test_declared_interest_cannot_be_built_as_a_row_anyway() -> None:
    with pytest.raises(ValidationError):
        make_row(event_type="declared_interest")


# --- the document and the code agree ----------------------------------------


def test_contract_document_names_every_field() -> None:
    """EVENT_CONTRACT.md is what gets signed. If it and the model disagree, the
    signature is on the wrong thing.
    """
    document = (Path(__file__).parents[1] / "EVENT_CONTRACT.md").read_text(
        encoding="utf-8"
    )

    for field in set(CORE_FIELDS) | set(CONDITIONAL_FIELDS):
        assert f"`{field}`" in document, f"{field} is not named in EVENT_CONTRACT.md"

    for event_type in ROW_EVENT_TYPES:
        assert event_type in document, f"{event_type} is not named in EVENT_CONTRACT.md"
