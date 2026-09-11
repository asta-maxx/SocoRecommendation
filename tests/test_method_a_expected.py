"""Method A against the generator's own expected scores.

`ml_demo_meta.json` carries `expected_raw` for all twenty narrated users, computed
by the generator independently of this engine. This is the test that matters: it
compares Method A against a number someone else produced, rather than against
this codebase's reading of the specification.

Skips cleanly if the demo dataset has not been unpacked -- see DEMO_DIR.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from reco.config import Settings
from reco.domain.categories import CategoryVocabulary, resolve_all
from reco.domain.events import Event, EventType
from reco.methods.context import ScoringContext
from reco.methods.interest_decay import score

DEMO_DIR = Path(
    os.environ.get(
        "DEMO_DATA_DIR",
        Path(__file__).resolve().parents[1] / "reference" / "demo",
    )
)

TOLERANCE = 5e-6

#: Generator row type -> internal event type. The generator spells them long.
ROW_TYPES = {
    "product_view": EventType.VIEW,
    "product_click": EventType.CLICK,
    "add_to_cart": EventType.CART,
    "purchase": EventType.PURCHASE,
    "keyword_search": EventType.SEARCH,
    "purchase_reversal": EventType.PURCHASE,
}


def _load(name: str):
    path = DEMO_DIR / name
    if not path.exists():
        pytest.skip(
            f"demo dataset not found at {DEMO_DIR}. Unpack reference/demo.zip "
            f"or set DEMO_DATA_DIR."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def demo():
    meta = _load("ml_demo_meta.json")
    events = _load("ml_demo_events.json")
    users = _load("ml_demo_users.json")
    orders = _load("ml_demo_orders.json")

    by_user: dict[str, list[dict]] = {}
    for row in events:
        by_user.setdefault(row["user_id"], []).append(row)

    return {
        "meta": meta,
        "reference_date": datetime.fromisoformat(meta["reference_date"]),
        "events": by_user,
        "declared": {
            u["user_id"]: u.get("declared_interests", []) for u in users
        },
        "orders": {
            o["order_id"]: datetime.fromisoformat(o["placed_at"])
            for o in orders
            if o.get("placed_at")
        },
    }


VOCABULARY = CategoryVocabulary.load(
    Path(__file__).resolve().parents[1] / "reco" / "data" / "categories.json"
)


def resolve_expected(expected: dict[str, float]) -> dict[str, float]:
    """Put the generator's expected values through the same resolution.

    `expected_raw` is keyed on the strings the generator supplied -- including
    legacy spellings and seller-invented names. The engine stores canonical
    categories, so the two are only comparable once the expectation has been
    resolved the same way: unmappable names drop out, and names that merge onto
    one canonical category have their values SUMMED.

    That summing is what makes this test assert the merge rather than assume it.
    With no LEGACY_LABEL_MAP loaded, U06's five names all drop and the expected
    map is empty. When the map arrives, the same code expects
    Home & Living = 9.65 + 10.88 + 9.88 and Fashion & Apparel = 11.44 + 7.24 --
    without this file changing.
    """
    resolved: dict[str, float] = {}
    for supplied, value in expected.items():
        canonical = VOCABULARY.resolve(supplied)
        if canonical is None:
            continue
        resolved[canonical] = resolved.get(canonical, 0.0) + value
    return resolved


def adapt(row: dict, reference_date: datetime) -> Event | None:
    """The flat adapter, applied to a raw generated row.

    Mirrors what `data.readers` does against the collection, so this test
    exercises the same rules: a null timestamp, a future timestamp, an empty
    category list and -- since the fix to DS-008 section 3.2 -- a category with no
    canonical equivalent are all dropped rather than scored.
    """
    event_type = ROW_TYPES.get(row.get("event_type"))
    if event_type is None:
        return None

    when = row.get("timestamp")
    if not when:  # null, not an absent key -- U10 carries both
        return None
    timestamp = datetime.fromisoformat(when)
    if timestamp > reference_date:
        return None

    supplied = [c for c in (row.get("categories") or []) if isinstance(c, str) and c]
    categories = resolve_all(VOCABULARY, supplied).resolved
    if not categories:
        return None

    return Event(
        user_id=row["user_id"],
        event_type=event_type,
        categories=categories,
        timestamp=timestamp,
        view_duration_seconds=row.get("view_duration_seconds"),
        order_id=row.get("order_id"),
        is_reversal=row.get("event_type") == "purchase_reversal",
    )


def context_for(demo, user_id: str) -> ScoringContext:
    return ScoringContext(
        tunables=Settings().tunables(),
        declared_interests=demo["declared"].get(user_id, []),
        order_created_at=demo["orders"],
        now=demo["reference_date"],
    )


def events_for(demo, user_id: str) -> list[Event]:
    return [
        event
        for row in demo["events"].get(user_id, [])
        if (event := adapt(row, demo["reference_date"])) is not None
    ]


def raw_for(demo, user_id: str) -> dict[str, float]:
    """The stored raw: events plus the declared floor. This is what the engine
    writes, and it is what DS-008's formula defines.
    """
    raws, _ = score(events_for(demo, user_id), context_for(demo, user_id))
    return raws


def event_raw_for(demo, user_id: str) -> dict[str, float]:
    """The event component alone, with the floor switched off.

    `expected_raw` in the meta file is this, NOT the stored raw. The generator's
    prose makes the split explicit -- "U20 Shoes & Footwear 20.46 plus a floor of
    10", and U07 has six declared interests but an empty `expected_raw` because
    it has no events. Comparing the stored raw against it would fail by exactly
    the floor on every declared category, which looks like a decay bug and is not
    one.
    """
    ctx = context_for(demo, user_id).model_copy(update={"declared_interests": []})
    raws, _ = score(events_for(demo, user_id), ctx)
    return raws


def narrated_users(demo) -> list[str]:
    return sorted(demo["meta"]["expected_raw"])


# --- the whole set ----------------------------------------------------------


def test_every_narrated_user_matches_expected(demo) -> None:
    """All twenty at once, so a partial pass is visible as a partial pass."""
    mismatches = []

    for user_id in narrated_users(demo):
        expected = resolve_expected(demo["meta"]["expected_raw"][user_id])
        got = event_raw_for(demo, user_id)

        for category, want in expected.items():
            have = got.get(category)
            if have is None or abs(have - want) > TOLERANCE:
                mismatches.append(
                    f"{user_id} {category}: expected {want:.6f}, got "
                    f"{'missing' if have is None else format(have, '.6f')}"
                )
        for category, have in got.items():
            if category not in expected and abs(have) > TOLERANCE:
                mismatches.append(
                    f"{user_id} {category}: unexpected {have:.6f}"
                )

    assert not mismatches, "\n".join(mismatches)


# --- the ones that each prove something -------------------------------------


def test_u02_only_qualified_views_count(demo) -> None:
    """Twenty views, twelve under three seconds. Only the eight qualified ones
    contribute -- P-02 applied on the value, not on the field's presence.
    """
    assert event_raw_for(demo, "U02")["Beauty & Personal Care"] == pytest.approx(
        13.105563, abs=TOLERANCE
    )


def test_u03_multi_category_gets_full_weight_each(demo) -> None:
    """Not a divided share. All three land on the same number, which they only
    can if each category received the whole weight.
    """
    raws = event_raw_for(demo, "U03")
    values = [raws[c] for c in ("Fashion & Apparel", "Jewellery", "Technology")]

    assert all(v == pytest.approx(39.121085, abs=TOLERANCE) for v in values)
    assert len(set(round(v, 6) for v in values)) == 1


def test_u04_decay_reorders_the_categories(demo) -> None:
    """The argument for decay. Heavy Electronics three months ago, heavy Home &
    Living in the last fortnight -- with decay on, the recent interest leads.
    """
    raws = event_raw_for(demo, "U04")

    assert raws["Home & Living"] == pytest.approx(118.537586, abs=TOLERANCE)
    assert raws["Electronics"] == pytest.approx(16.981739, abs=TOLERANCE)
    assert raws["Home & Living"] > raws["Electronics"]


def test_u05_declared_floor_leads(demo) -> None:
    """Three declared categories at a floor of 10 each, against light recent
    activity worth 4.52. The floor must lead, and must not decay.

    The stored raw, not the event component: the floor is the point.
    """
    raws = raw_for(demo, "U05")

    assert raws["Electronics"] == pytest.approx(4.515886, abs=TOLERANCE)
    floors = [v for c, v in raws.items() if c != "Electronics"]
    assert len(floors) == 3
    assert all(v == pytest.approx(10.0, abs=TOLERANCE) for v in floors)
    assert min(floors) > raws["Electronics"]


def test_u20_is_events_plus_the_floor(demo) -> None:
    """"U20 Shoes & Footwear 20.46 plus a floor of 10" -- the generator's own
    words, and the clearest statement that expected_raw excludes the floor.
    """
    assert event_raw_for(demo, "U20")["Shoes & Footwear"] == pytest.approx(
        20.459381, abs=TOLERANCE
    )
    assert raw_for(demo, "U20")["Shoes & Footwear"] == pytest.approx(
        30.459381, abs=TOLERANCE
    )


def test_the_floor_does_not_decay(demo) -> None:
    """P-26 is No at launch. U07 declared six interests and has no events at all;
    every one must sit at exactly 10 however old the signup is.

    A floor that decayed would make a user who declared six interests and then
    browsed lightly for three months fade to nothing -- which is exactly the user
    who most needs those declarations to hold.
    """
    raws = raw_for(demo, "U07")

    assert len(raws) == 6
    assert all(v == 10.0 for v in raws.values())


def test_u06_never_stores_a_legacy_spelling(demo) -> None:
    """U06's whole job is to show legacy names being REPAIRED.

    An earlier version of this test asserted the five legacy names were present
    and called that correct. It was not: storing 'Fashion' and 'fashion' as two
    separate rows is precisely the production defect U06 demonstrates being
    fixed, and the test locked the defect in while the suite reported green.

    What must always hold is that no legacy spelling reaches the store. Whether
    they MERGE or are DROPPED depends on LEGACY_LABEL_MAP, covered below.
    """
    raws = event_raw_for(demo, "U06")

    for legacy in (
        "Fashion",
        "fashion",
        "home & decor",
        "kitchen & dining",
        "bedding & bath",
        "home_&_living",
    ):
        assert legacy not in raws, f"{legacy!r} was stored verbatim"


def test_u06_merges_once_the_legacy_map_is_loaded(demo) -> None:
    """The merge itself, conditional on having the map.

    Without LEGACY_LABEL_MAP the five names have no canonical equivalent, so they
    are dropped and counted -- correct per DS-008 section 3.2, and incomplete:
    U06 demonstrates a merge and cannot until the map arrives.

    With the map, three names collapse onto Home & Living and two onto
    Fashion & Apparel, each target the sum of its parts.
    """
    if not VOCABULARY.legacy_map_loaded:
        pytest.skip(
            "LEGACY_LABEL_MAP not loaded -- export categories.js. U06's five "
            "legacy names are dropped rather than merged until it arrives."
        )

    raws = event_raw_for(demo, "U06")

    assert set(raws) == {"Home & Living", "Fashion & Apparel"}
    assert raws["Home & Living"] == pytest.approx(30.40, abs=0.01)
    assert raws["Fashion & Apparel"] == pytest.approx(18.68, abs=0.01)


def test_u06_legacy_names_are_counted_when_dropped(demo) -> None:
    """The drop is COUNTED, never silent.

    That counter reading zero against a dataset deliberately built to contain
    unmappable categories is the signal that resolution is not running at all --
    which is exactly how this went unnoticed through four clean runs.
    """
    from reco.domain.events import ReadStats

    stats = ReadStats()
    for row in demo["events"]["U06"]:
        supplied = [c for c in (row.get("categories") or []) if isinstance(c, str)]
        stats.record_unmapped(resolve_all(VOCABULARY, supplied).dropped)

    if VOCABULARY.legacy_map_loaded:
        assert stats.unmapped_category_values == 0
    else:
        assert stats.unmapped_category_values == 20
        assert set(stats.unmapped_examples) == {
            "Fashion",
            "fashion",
            "home & decor",
            "kitchen & dining",
            "bedding & bath",
        }


def test_u07_and_u11_are_different_cold_start_rungs(demo) -> None:
    """They are not the same case, and the ladder treats them differently.

    U07 has declared interests and no events -- rung 2, the floor alone.
    U11 has neither -- rung 3, platform-wide popularity.

    Neither gets a fabricated uniform share: U11's map is empty, which is the
    signal for the ladder to take over rather than a number to serve.
    """
    assert event_raw_for(demo, "U07") == {}
    assert raw_for(demo, "U07") != {}

    assert event_raw_for(demo, "U11") == {}
    assert raw_for(demo, "U11") == {}


def test_u08_drops_unmappable_categories(demo) -> None:
    """U08's whole job is to show unmapped categories being dropped.

    An earlier version of this test asserted 'Casual Sneakers' was present with a
    raw score, and called that correct. It was the opposite of what U08
    demonstrates: three seller-created categories with no path to the canonical
    23 were taking 43 percent of the profile.
    """
    raws = event_raw_for(demo, "U08")

    for unmappable in ("Casual Sneakers", "Jackets", "Sunglasses"):
        assert unmappable not in raws, f"{unmappable!r} was scored as a category"

    assert set(raws) == {"Home & Living"}
    assert raws["Home & Living"] == pytest.approx(18.948715, abs=TOLERANCE)


def test_u08_drops_are_counted(demo) -> None:
    """Six events, three distinct names. Counted, so the drop rate is a figure
    somebody can look at rather than an absence nobody notices.
    """
    from reco.domain.events import ReadStats

    stats = ReadStats()
    for row in demo["events"]["U08"]:
        supplied = [c for c in (row.get("categories") or []) if isinstance(c, str)]
        stats.record_unmapped(resolve_all(VOCABULARY, supplied).dropped)

    assert stats.unmapped_category_values == 6
    assert set(stats.unmapped_examples) == {
        "Casual Sneakers",
        "Jackets",
        "Sunglasses",
    }


def test_u10_future_and_null_timestamps_are_dropped(demo) -> None:
    """U10 carries both. Future is judged against the reference date, not the
    clock -- run a day late against now() and those rows start contributing.
    """
    rows = demo["events"]["U10"]

    assert any(r.get("timestamp") is None for r in rows), "fixture lost its nulls"
    assert event_raw_for(demo, "U10")["Travel & Lifestyle"] == pytest.approx(
        42.475671, abs=TOLERANCE
    )


def test_u16_and_u17_differ_by_exactly_the_purchase(demo) -> None:
    """Check 7, and the one that catches a reversal built the old way.

    The pair is equal by construction. U17's order was cancelled, so the
    reversal removes exactly what the purchase added at twelve days old:
    20 x 2**(-12/30) = 15.157166. Aged from the cancellation instead it would
    remove 17.8, leaving U17 below a user who never ordered.
    """
    cat = "Fashion & Apparel"
    u16 = event_raw_for(demo, "U16")[cat]
    u17 = event_raw_for(demo, "U17")[cat]

    assert u16 == pytest.approx(50.451544, abs=TOLERANCE)
    assert u17 == pytest.approx(35.294378, abs=TOLERANCE)
    assert u16 - u17 == pytest.approx(20 * 2 ** (-12 / 30), abs=1e-4)
    assert u17 > 0


def test_no_user_scores_negative(demo) -> None:
    """Under the corrected reversal a negative raw cannot occur."""
    for user_id in narrated_users(demo):
        for category, raw in raw_for(demo, user_id).items():
            assert raw >= 0, f"{user_id} {category} is negative: {raw}"
