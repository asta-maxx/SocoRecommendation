"""Category resolution. DS-008 section 3.2.

The step the engine was missing: resolve the supplied string onto a canonical
category, or determine it has none. Keying the map without resolving first is
what let "Casual Sneakers" take 24 percent of U08's profile and "Fashion" and
"fashion" become two separate rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reco.platform.categories import (
    CategoryVocabulary,
    resolve_all,
    to_category_key,
)

CANONICAL = [
    "Fashion & Apparel",
    "Home & Living",
    "Electronics",
    "Shoes & Footwear",
]

LEGACY = {
    "home & decor": "Home & Living",
    "kitchen & dining": "Home & Living",
    "bedding & bath": "Home & Living",
    "home_&_living": "Home & Living",
    "Fashion": "Fashion & Apparel",
    "Gadgets": None,
}


@pytest.fixture
def vocabulary() -> CategoryVocabulary:
    return CategoryVocabulary(canonical=CANONICAL, legacy_map=LEGACY, source="test")


@pytest.fixture
def canonical_only() -> CategoryVocabulary:
    return CategoryVocabulary(
        canonical=CANONICAL, legacy_map={}, legacy_map_loaded=False, source="test"
    )


# --- toCategoryKey ----------------------------------------------------------


@pytest.mark.parametrize(
    "supplied,expected",
    [
        ("Fashion & Apparel", "fashion & apparel"),
        ("  Fashion & Apparel  ", "fashion & apparel"),
        ("FASHION & APPAREL", "fashion & apparel"),
        ("Fashion  &   Apparel", "fashion & apparel"),
    ],
)
def test_the_key_is_lowercase_trimmed_and_space_preserving(
    supplied: str, expected: str
) -> None:
    """Spaces are preserved, not replaced. 'fashion & apparel', never
    'fashion_&_apparel' -- the underscore form is a legacy spelling to map away.
    """
    assert to_category_key(supplied) == expected


def test_the_key_does_not_strip_underscores() -> None:
    """An underscored name is a DIFFERENT string that the legacy map repairs.
    Silently stripping underscores here would repair it by accident and hide the
    fact that a legacy spelling was in the data.
    """
    assert to_category_key("home_&_living") == "home_&_living"


# --- resolution -------------------------------------------------------------


def test_a_canonical_category_resolves_to_itself(vocabulary) -> None:
    assert vocabulary.resolve("Home & Living") == "Home & Living"


def test_case_and_spacing_do_not_matter(vocabulary) -> None:
    assert vocabulary.resolve("  home & living ") == "Home & Living"
    assert vocabulary.resolve("HOME & LIVING") == "Home & Living"


def test_resolution_returns_the_canonical_spelling(vocabulary) -> None:
    """Stored under the canonical LABEL, so the store stays readable and matches
    what the rest of the platform displays.
    """
    assert vocabulary.resolve("home & living") == "Home & Living"


def test_a_legacy_name_maps_onto_its_canonical_category(vocabulary) -> None:
    assert vocabulary.resolve("home & decor") == "Home & Living"
    assert vocabulary.resolve("kitchen & dining") == "Home & Living"
    assert vocabulary.resolve("bedding & bath") == "Home & Living"


def test_the_underscore_variant_is_repaired_not_merged(vocabulary) -> None:
    """Four keys point at Home & Living; three are merges. The fourth is the
    canonical label correcting its own spelling.
    """
    assert vocabulary.resolve("home_&_living") == "Home & Living"


def test_two_spellings_of_one_category_resolve_to_the_same_label(vocabulary) -> None:
    """'Fashion' and 'fashion' were two separate rows in the store. They are one
    category, and this is the assertion that says so.
    """
    assert vocabulary.resolve("Fashion") == vocabulary.resolve("fashion")
    assert vocabulary.resolve("Fashion") == "Fashion & Apparel"


def test_an_explicit_null_in_the_map_means_drop(vocabulary) -> None:
    """Different from a name simply being absent: someone decided this one has
    no home.
    """
    assert vocabulary.resolve("Gadgets") is None


def test_an_unknown_name_is_dropped(vocabulary) -> None:
    """Seller-created product categories are unconstrained. 'Casual Sneakers' is
    a real one with no path to the canonical 23.
    """
    assert vocabulary.resolve("Casual Sneakers") is None
    assert vocabulary.resolve("Jackets") is None
    assert vocabulary.resolve("Sunglasses") is None


def test_blank_resolves_to_nothing(vocabulary) -> None:
    assert vocabulary.resolve("") is None
    assert vocabulary.resolve("   ") is None


def test_a_canonical_match_wins_over_the_legacy_map() -> None:
    """A legacy entry must never shadow a live category."""
    shadowing = CategoryVocabulary(
        canonical=["Electronics"], legacy_map={"Electronics": None}
    )

    assert shadowing.resolve("Electronics") == "Electronics"


def test_without_the_legacy_map_legacy_names_are_dropped(canonical_only) -> None:
    """Correct per DS-008 section 3.2, and incomplete. Dropping is the right
    behaviour for a name with no known mapping; the map is what turns a drop into
    a merge.
    """
    assert canonical_only.resolve("home & decor") is None
    assert canonical_only.resolve("Fashion") is None
    assert canonical_only.resolve("Home & Living") == "Home & Living"


# --- resolving a whole event ------------------------------------------------


def test_resolved_and_dropped_are_kept_apart(vocabulary) -> None:
    result = resolve_all(vocabulary, ["Home & Living", "Casual Sneakers"])

    assert result.resolved == ["Home & Living"]
    assert result.dropped == ["Casual Sneakers"]


def test_a_partly_resolvable_event_keeps_what_resolved(vocabulary) -> None:
    """The event is not dropped -- only the category that has no home. Counting
    whole events only would report zero for exactly this case.
    """
    result = resolve_all(vocabulary, ["Electronics", "Jackets", "Home & Living"])

    assert result.resolved == ["Electronics", "Home & Living"]
    assert result.dropped == ["Jackets"]


def test_two_spellings_merge_to_one_contribution(vocabulary) -> None:
    """A single event tagged 'Fashion' and 'fashion' credits Fashion & Apparel
    ONCE. Without deduplication the user is paid twice for one action just
    because the category was written two ways.
    """
    result = resolve_all(vocabulary, ["Fashion", "fashion"])

    assert result.resolved == ["Fashion & Apparel"]


def test_everything_dropped_leaves_nothing_resolved(vocabulary) -> None:
    result = resolve_all(vocabulary, ["Casual Sneakers", "Jackets"])

    assert result.resolved == []
    assert len(result.dropped) == 2


# --- loading ----------------------------------------------------------------


def test_a_missing_vocabulary_file_raises(tmp_path) -> None:
    """An engine that carried on without a vocabulary would score seller strings
    as categories -- the defect this module exists to fix, invisible again.
    """
    with pytest.raises(FileNotFoundError, match="export_categories"):
        CategoryVocabulary.load(tmp_path / "nothing.json")


def test_an_empty_vocabulary_raises(tmp_path) -> None:
    path = tmp_path / "categories.json"
    path.write_text(json.dumps({"canonical": [], "legacy_map": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="no canonical categories"):
        CategoryVocabulary.load(path)


def test_loading_round_trips(tmp_path) -> None:
    path = tmp_path / "categories.json"
    path.write_text(
        json.dumps({"canonical": CANONICAL, "legacy_map": LEGACY, "source": "test"}),
        encoding="utf-8",
    )

    loaded = CategoryVocabulary.load(path)

    assert loaded.canonical == CANONICAL
    assert loaded.resolve("home & decor") == "Home & Living"


def test_a_partial_export_says_so_loudly(tmp_path, caplog) -> None:
    """An absent map must not look like an empty one."""
    import logging

    path = tmp_path / "categories.json"
    path.write_text(
        json.dumps(
            {"canonical": CANONICAL, "legacy_map": {}, "legacy_map_loaded": False}
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="reco.platform.categories"):
        loaded = CategoryVocabulary.load(path)

    assert loaded.legacy_map_loaded is False
    assert "LEGACY_LABEL_MAP is NOT loaded" in caplog.text


# --- the shipped vocabulary -------------------------------------------------


def test_the_shipped_vocabulary_has_the_canonical_twenty_three() -> None:
    """List 2, the post category picker. Loaded, never retyped -- a retyped copy
    would be a fourth vocabulary alongside the three that already exist.
    """
    path = Path(__file__).resolve().parents[1] / "reco" / "platform" / "categories.json"
    if not path.exists():
        pytest.skip("run scripts/export_categories.py")

    vocabulary = CategoryVocabulary.load(path)

    assert len(vocabulary.canonical) == 23
    assert "Fashion & Apparel" in vocabulary.canonical
    assert "Home & Living" in vocabulary.canonical


def test_no_category_name_is_written_down_in_executable_python() -> None:
    """The vocabulary is data, not source.

    Docstrings are excluded: naming a category while explaining how resolution
    works is documentation. What must not exist is a category name reaching
    executable code, because a retyped copy is a fourth vocabulary alongside the
    three that already exist.
    """
    import ast

    import reco.platform.categories as categories_module
    import reco.platform.readers as readers_module

    path = Path(__file__).resolve().parents[1] / "reco" / "platform" / "categories.json"
    if not path.exists():
        pytest.skip("run scripts/export_categories.py")
    names = json.loads(path.read_text(encoding="utf-8"))["canonical"]

    for module in (categories_module, readers_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ) and ast.get_docstring(node, clean=False) is not None:
                docstrings.add(id(node.body[0].value))

        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]

        for name in names:
            offenders = [text for text in literals if name in text]
            assert not offenders, (
                f"{name!r} appears in executable code in "
                f"{Path(module.__file__).name}. Category names are loaded, "
                f"never written down."
            )
