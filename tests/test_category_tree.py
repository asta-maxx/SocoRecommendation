"""The tree rule for categories (ENG-03, ENG-29 item 1; review of 26 Oct 2026).

Every label the engine maps (a post's categories, a user's interests, a business's
category, a product's category id) is mapped through its actual top-level parent
in the platform's category tree. The top counts if it is one of the 23, or if the
category map points it straight to one of the 23. Otherwise the label is left
unmapped with a reason -- never guessed from the label, product or seller name.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from bson import ObjectId

from reco.platform import records
from reco.platform.categories import (
    AMBIGUOUS,
    EMPTY,
    MAP_NOT_TO_23,
    NO_PARENT,
    NOT_IN_TREE,
    TOP_NOT_MAPPED,
    VIA_MAP,
    VIA_NAME,
    VIA_TREE,
    VIA_TREE_AND_MAP,
    CategoryTree,
    CategoryVocabulary,
    ProductCategoryIndex,
    canonical_name,
    post_categories,
    resolve_category_id,
    resolve_label,
)

VOCAB = CategoryVocabulary(
    canonical=["Fashion & Apparel", "Electronics", "Home & Living", "Shoes & Footwear", "Gaming", "Food & Beverages"],
)
MAP = {"fashion": "Fashion & Apparel", "home & kitchen": "Home & Living", "bad top": "Not A Category",
       "footwear": "Shoes & Footwear", "cricket": "Not A Category", "retail": "Food & Beverages"}

ELECTRONICS, FASHION, HOME_KITCHEN, ART, BAD_TOP = (ObjectId() for _ in range(5))
GAMING, SHIRTS, MEN, FOOTWEAR, JEANS_MEN, JEANS_KITCHEN, POTTERY, LOST, ORPHAN, BROKEN, LOOP_A, LOOP_B, ODD = (
    ObjectId() for _ in range(13))


def node(_id, name, parent=None, level=0, path=None):
    return {"_id": _id, "name": name, "parent": parent, "level": level, "path": path or [name]}


DOCS = [
    node(ELECTRONICS, "Electronics"),  # one of the 23 by name
    node(FASHION, "Fashion"),  # not one of the 23: the category map points it to Fashion & Apparel
    node(HOME_KITCHEN, "Home & Kitchen"),  # mapped too
    node(ART, "Art & Handicrafts"),  # not one of the 23, and not in the map
    node(BAD_TOP, "Bad Top"),  # mapped, but not to one of the 23
    node(GAMING, "Gaming", ELECTRONICS, 1),  # one of the 23 by name, under Electronics
    node(MEN, "Men", FASHION, 1),
    node(SHIRTS, "Shirts", MEN, 2),
    node(FOOTWEAR, "Footwear", FASHION, 1),  # the map says Shoes & Footwear; the tree, Fashion & Apparel
    node(JEANS_MEN, "Jeans", MEN, 2),
    node(JEANS_KITCHEN, "jeans ", HOME_KITCHEN, 1),  # the same name, another top that ends elsewhere
    node(POTTERY, "Pottery", ART, 1),
    node(LOST, "Lost", ObjectId(), 1),  # its parent is not in the tree
    node(ORPHAN, "Orphan", None, 2),  # no parent, yet says it is below the top
    node(BROKEN, "Broken Child", LOST, 2),
    node(LOOP_A, "Loop A", LOOP_B, 1),
    node(LOOP_B, "Loop B", LOOP_A, 1),
    node(ODD, "Odd Path", HOME_KITCHEN, 1, path=["Electronics", "Odd Path"]),  # the path disagrees with the parent
]
TREE = CategoryTree.build(DOCS)


def resolve(label, category_map=MAP, tree=TREE):
    return resolve_label(VOCAB, label, category_map, tree)


# --- mapped -------------------------------------------------------------------------------


def test_a_label_that_is_one_of_the_23_is_that_category() -> None:
    r = resolve("  electronics ")
    assert (r.category, r.via, r.reason) == ("Electronics", VIA_NAME, None)


def test_a_label_one_of_the_23_by_name_stays_so_even_under_another_top_and_is_noted() -> None:
    """ENG-03 matches by name; the Build List governs. The tree's other top is listed, not applied."""
    r = resolve("Gaming")
    assert (r.category, r.via) == ("Gaming", VIA_NAME)
    assert r.tops == ["Electronics"] and "Electronics" in r.note


def test_a_label_is_mapped_through_its_top_when_the_top_is_one_of_the_23() -> None:
    tree = CategoryTree.build([node(ELECTRONICS, "Electronics"), node(LOST, "Screen Protectors", ELECTRONICS, 1)])
    r = resolve("screen protectors", tree=tree)
    assert (r.category, r.via, r.tops) == ("Electronics", VIA_TREE, ["Electronics"])


def test_a_label_is_mapped_through_its_top_when_the_map_points_the_top_to_one_of_the_23() -> None:
    r = resolve("Shirts")  # Fashion > Men > Shirts; the map: fashion -> Fashion & Apparel
    assert (r.category, r.via, r.tops) == ("Fashion & Apparel", VIA_TREE, ["Fashion"])


def test_a_top_level_label_is_its_own_top() -> None:
    assert resolve("Home & Kitchen").category == "Home & Living"
    # "fashion" is in the map and is a top that the map points to the same place: both agree.
    r = resolve("Fashion")
    assert (r.category, r.via) == ("Fashion & Apparel", VIA_TREE_AND_MAP)


def test_the_map_alone_maps_a_label_that_is_not_in_the_tree() -> None:
    r = resolve("Retail")
    assert (r.category, r.via, r.reason) == ("Food & Beverages", VIA_MAP, None)


def test_the_map_maps_a_label_whose_tree_top_is_not_mapped_and_says_so() -> None:
    r = resolve("Pottery", {**MAP, "pottery": "Home & Living"})
    assert (r.category, r.via) == ("Home & Living", VIA_MAP)
    assert TOP_NOT_MAPPED in r.note and "Art & Handicrafts" in r.note


def test_the_top_is_found_by_parent_links_not_by_the_path() -> None:
    """The actual top-level parent: Odd Path's parent is Home & Kitchen, whatever its path says."""
    assert resolve("Odd Path").category == "Home & Living"


def test_names_match_ignoring_case_and_spacing() -> None:
    assert resolve("  SHIRTS ").category == "Fashion & Apparel"


# --- unmapped, with a reason -----------------------------------------------------------------


def test_not_in_tree() -> None:
    r = resolve("Handloom Weavers")
    assert (r.category, r.reason) == (None, NOT_IN_TREE)


@pytest.mark.parametrize("label", ["Lost", "Orphan", "Broken Child", "Loop A"])
def test_no_parent_when_the_top_cannot_be_reached(label: str) -> None:
    """A parent missing from the tree, a node below the top with no parent, a child of
    such a node, and a loop: none reaches a top-level node."""
    r = resolve(label)
    assert (r.category, r.reason) == (None, NO_PARENT)


def test_top_not_mapped() -> None:
    r = resolve("Pottery")
    assert (r.category, r.reason, r.tops) == (None, TOP_NOT_MAPPED, ["Art & Handicrafts"])


def test_map_not_to_23_on_the_top() -> None:
    tree = CategoryTree.build([*DOCS, node(ObjectId(), "Widgets", BAD_TOP, 1)])
    r = resolve("Widgets", tree=tree)
    assert (r.category, r.reason) == (None, MAP_NOT_TO_23)


def test_map_not_to_23_on_the_label_itself_whatever_the_tree_says() -> None:
    r = resolve("Cricket")
    assert (r.category, r.reason) == (None, MAP_NOT_TO_23) and "Not A Category" in r.note
    r = resolve("Shirts", {**MAP, "shirts": "Not A Category"})  # the tree would say Fashion & Apparel
    assert (r.category, r.reason) == (None, MAP_NOT_TO_23)


def test_ambiguous_when_two_nodes_of_one_name_end_in_different_categories() -> None:
    r = resolve("Jeans")  # Fashion > Men > Jeans, and Home & Kitchen > jeans
    assert (r.category, r.reason) == (None, AMBIGUOUS)
    assert r.tops == ["Fashion", "Home & Kitchen"] and "Fashion & Apparel" in r.note and "Home & Living" in r.note


def test_ambiguous_when_one_node_of_a_name_resolves_and_another_does_not() -> None:
    tree = CategoryTree.build([*DOCS, node(ObjectId(), "Pottery", HOME_KITCHEN, 1)])
    r = resolve("Pottery", tree=tree)  # one under Home & Kitchen (Home & Living), one under Art (unmapped)
    assert (r.category, r.reason) == (None, AMBIGUOUS)


def test_ambiguous_when_the_tree_and_the_direct_map_disagree() -> None:
    """Footwear: the tree says Fashion & Apparel (top Fashion); the map says Shoes & Footwear.
    Neither is picked."""
    r = resolve("Footwear")
    assert (r.category, r.reason) == (None, AMBIGUOUS)
    assert "Fashion & Apparel" in r.note and "Shoes & Footwear" in r.note


def test_ambiguous_when_the_map_maps_a_label_whose_nodes_disagree() -> None:
    r = resolve("Jeans", {**MAP, "jeans": "Fashion & Apparel"})
    assert (r.category, r.reason) == (None, AMBIGUOUS)


@pytest.mark.parametrize("label", [None, "", "   ", 7, ["Electronics"]])
def test_empty(label) -> None:
    assert (resolve(label).category, resolve(label).reason) == (None, EMPTY)


# --- ids (products) ---------------------------------------------------------------------------


def test_a_category_id_is_found_by_id_and_followed_to_its_top() -> None:
    r = resolve_category_id(VOCAB, SHIRTS, MAP, TREE)
    assert (r.category, r.via, r.tops) == ("Fashion & Apparel", VIA_TREE, ["Fashion"])
    assert r.label == f"Fashion > Men > Shirts (category id {SHIRTS})"
    assert resolve_category_id(VOCAB, str(ELECTRONICS), MAP, TREE).category == "Electronics"  # text or ObjectId


def test_a_category_id_is_never_ambiguous_and_takes_no_direct_rule() -> None:
    assert resolve_category_id(VOCAB, JEANS_KITCHEN, MAP, TREE).category == "Home & Living"
    # Footwear's own name is in the map, but an id is mapped by its top only.
    assert resolve_category_id(VOCAB, FOOTWEAR, MAP, TREE).category == "Fashion & Apparel"


def test_category_id_reasons() -> None:
    assert resolve_category_id(VOCAB, ObjectId(), MAP, TREE).reason == NOT_IN_TREE
    assert resolve_category_id(VOCAB, None, MAP, TREE).reason == EMPTY
    assert resolve_category_id(VOCAB, POTTERY, MAP, TREE).reason == TOP_NOT_MAPPED
    assert resolve_category_id(VOCAB, LOST, MAP, TREE).reason == NO_PARENT


def test_the_product_index_follows_parents_to_the_top() -> None:
    index = ProductCategoryIndex.build(VOCAB, DOCS, MAP)
    assert index.category_of(SHIRTS) == "Fashion & Apparel"
    assert index.category_of(ODD) == "Home & Living"  # by its parent, not its path
    assert index.category_of(POTTERY) is None and index.category_of(LOST) is None
    product = records.parse_product({"_id": ObjectId(), "basicInfo": {"categoryId": SHIRTS}}, index)
    assert product.category == "Fashion & Apparel"


# --- the readers use it ------------------------------------------------------------------------


def test_canonical_name_with_the_tree_applies_the_rule_and_without_it_the_direct_rule() -> None:
    assert canonical_name(VOCAB, "Shirts", MAP, TREE) == "Fashion & Apparel"
    assert canonical_name(VOCAB, "Shirts", MAP) is None  # direct rule only
    assert canonical_name(VOCAB, "Footwear", MAP) == "Shoes & Footwear"
    assert canonical_name(VOCAB, "Footwear", MAP, TREE) is None  # ambiguous under the tree rule


def test_post_user_business_and_category_records_use_the_tree() -> None:
    post = records.parse_post({"_id": ObjectId(), "userId": ObjectId(), "categories": ["Shirts", "Pottery", "Gaming"]},
                              VOCAB, MAP, TREE)
    assert post.categories == ["Fashion & Apparel", "Gaming"] and post.categories_dropped == ["Pottery"]
    user = records.parse_user({"_id": ObjectId(), "interest": ["Shirts", "Shirts", "Jeans"]}, VOCAB, MAP, TREE)
    assert user.declared_interests == ["Fashion & Apparel"]
    business = records.parse_business({"_id": ObjectId(), "category": "Odd Path"}, VOCAB, MAP, TREE)
    assert business.category == "Home & Living" and business.category_supplied == "Odd Path"
    category = records.parse_category(node(SHIRTS, "Shirts", MEN, 2, ["Fashion", "Men", "Shirts"]), VOCAB, MAP, TREE)
    assert category.top_level == "Fashion & Apparel"
    assert post_categories(VOCAB, "Shirts", MAP, TREE).resolved == ["Fashion & Apparel"]


# --- the vocabulary file loads from inside the repository --------------------------------------


def test_the_vocabulary_loads_from_the_repository_wherever_the_process_starts(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vocabulary = CategoryVocabulary.load("reco/platform/categories.json")
    assert len(vocabulary.canonical) == 23


def test_the_shipped_vocabulary_names_no_laptop_folder() -> None:
    import json

    data = json.loads((Path(__file__).resolve().parents[1] / "reco" / "platform" / "categories.json").read_text("utf-8"))
    assert ":" not in data["source"].split(" ")[0] and "\\" not in data["source"]
    assert data["source"].startswith("reference/post_picker_categories.txt")


def test_the_export_records_a_repository_relative_source() -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("export_categories", root / "scripts" / "export_categories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._shown(root / "reference" / "post_picker_categories.txt") == "reference/post_picker_categories.txt"
    assert module._shown(Path(os.sep) / "elsewhere" / "categories.js") == "categories.js"


# --- the tree is read at most once a minute ----------------------------------------------------


async def test_the_tree_is_read_once_and_reused_within_a_minute(monkeypatch) -> None:
    from reco.config import Settings
    from reco.platform import fetch

    reads = []

    class Cursor:
        async def to_list(self, _):
            reads.append(1)
            return DOCS

    class Collection:
        def find(self, *_):
            return Cursor()

    class Db:
        client = object()

        def __getitem__(self, _):
            return Collection()

    db = Db()
    monkeypatch.setattr(fetch, "app_db", lambda settings: db)
    fetch.reset_category_tree_cache()
    settings = Settings()
    try:
        first = await fetch.category_tree(settings)
        assert await fetch.category_tree(settings) is first and len(reads) == 1
        monkeypatch.setattr(fetch, "CATEGORY_TREE_SECONDS", 0.0)
        await fetch.category_tree(settings)
        assert len(reads) == 2  # stale: read again
    finally:
        fetch.reset_category_tree_cache()
