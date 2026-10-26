"""Category resolution. DS-008 section 3.2.

Resolving a category is TWO steps, and the engine previously did only the second:

    1. resolve the string the source supplied to a canonical category, or
       determine that it has no canonical equivalent
    2. key the score map on the result

Skipping step 1 is not the same as "not hardcoding a category list". It means
seller-created strings like "Casual Sneakers" are scored as though they were
categories, and two spellings of the same category -- "Fashion" and "fashion" --
become two separate rows. Both were happening.

The vocabulary is LOADED, never written down here. `CANONICAL_CATEGORIES` and
`LEGACY_LABEL_MAP` live in backend/SOCO_BE/src/constants/categories.js and are
exported to JSON by `scripts/export_categories.py`. Retyping either into Python
creates a fourth vocabulary alongside the three that already exist, which is the
failure this arrangement is meant to prevent.

LEGACY_LABEL_MAP (checked 26 Oct 2026): categories.js is not in this repository,
so reco/platform/categories.json was exported from the fallback list
(reference/post_picker_categories.txt) and carries the 23 only. Only the
demo-data reader (reco.platform.readers, CategoryVocabulary.resolve) uses the
legacy map. The live reader never does: it maps through the settings' category
map, which holds the app's LEGACY_LABEL_MAP entries (F1, 16 Oct), and the
platform's category tree (resolve_label, below).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, PrivateAttr

logger = logging.getLogger(__name__)

#: The repository root: a relative vocabulary path is read from inside it.
REPO_ROOT = Path(__file__).resolve().parents[2]


def to_category_key(label: str) -> str:
    """The comparison key for a category. Mirrors `toCategoryKey()`.

    Lowercase and trimmed, with internal spaces preserved:

        "Fashion & Apparel"  ->  "fashion & apparel"

    A key, not a stored value. Scores are stored under the canonical LABEL, so
    the store stays readable and matches what the rest of the platform displays.
    """
    return " ".join(label.strip().lower().split())


class CategoryVocabulary(BaseModel):
    """The canonical categories and the map from legacy names onto them."""

    model_config = {"frozen": True}

    #: The canonical labels, exactly as the platform spells them.
    canonical: list[str] = Field(default_factory=list)

    #: Legacy label -> canonical label, or None meaning "drop this one".
    #: An explicit None is a decision that a legacy name has no home, and is
    #: different from a name simply being absent.
    legacy_map: dict[str, str | None] = Field(default_factory=dict)

    #: False when the map could not be loaded. Carried so the service can say so
    #: rather than behave as though an empty map were a complete one.
    legacy_map_loaded: bool = True

    source: str = "unknown"

    def _canonical_by_key(self) -> dict[str, str]:
        return {to_category_key(c): c for c in self.canonical}

    def _legacy_by_key(self) -> dict[str, str | None]:
        return {to_category_key(k): v for k, v in self.legacy_map.items()}

    def resolve(self, supplied: str) -> str | None:
        """The canonical label for a supplied string, or None to drop it.

        Order matters: a canonical match wins before the legacy map is consulted,
        so a legacy entry can never shadow a live category.
        """
        if not supplied or not supplied.strip():
            return None

        key = to_category_key(supplied)

        canonical = self._canonical_by_key().get(key)
        if canonical is not None:
            return canonical

        if key in self._legacy_by_key():
            mapped = self._legacy_by_key()[key]
            if mapped is None:
                return None
            # The map's target must itself be canonical, or the map is wrong.
            return self._canonical_by_key().get(to_category_key(mapped), mapped)

        return None

    def is_canonical(self, supplied: str) -> bool:
        return to_category_key(supplied) in self._canonical_by_key()

    @classmethod
    def load(cls, path: Path | str) -> CategoryVocabulary:
        """Read the exported vocabulary.

        Raises if the file is missing. An engine that silently carried on without
        a vocabulary would score seller-created strings as categories -- which is
        the defect this module exists to fix, and it would be invisible again.
        """
        path = Path(path)
        if not path.is_absolute():
            # Inside the repository, wherever the process was started from.
            path = REPO_ROOT / path
        if not path.exists():
            raise FileNotFoundError(
                f"category vocabulary not found at {path}. Export it with "
                f"scripts/export_categories.py -- the engine cannot resolve "
                f"categories without it, and scoring unresolved strings as "
                f"categories is the defect this file prevents."
            )

        data = json.loads(path.read_text(encoding="utf-8"))
        vocabulary = cls(
            canonical=data.get("canonical", []),
            legacy_map=data.get("legacy_map", {}),
            legacy_map_loaded=bool(data.get("legacy_map_loaded", True)),
            source=data.get("source", str(path)),
        )

        if not vocabulary.canonical:
            raise ValueError(f"{path} carries no canonical categories")

        if not vocabulary.legacy_map_loaded:
            logger.warning(
                "LEGACY_LABEL_MAP is NOT loaded: it is not in %s (exported from %s); the app's "
                "backend/SOCO_BE/src/constants/categories.js is not in this repository. "
                "Only the demo-data reader uses it (legacy names there are dropped and "
                "counted, not merged). The live reader does not: it maps through the "
                "settings' category map (which holds the app's LEGACY_LABEL_MAP entries) "
                "and the platform's category tree. Export categories.js to fix.",
                path,
                vocabulary.source,
            )

        logger.info(
            "category vocabulary loaded: %d canonical, %d legacy entries (%s)",
            len(vocabulary.canonical),
            len(vocabulary.legacy_map),
            vocabulary.source,
        )
        return vocabulary


class CategoryResolution(BaseModel):
    """What resolving one event's categories produced."""

    model_config = {"frozen": True}

    resolved: list[str]
    dropped: list[str]


def resolve_all(
    vocabulary: CategoryVocabulary,
    supplied: list[str],
) -> CategoryResolution:
    """Resolve every category on an event, keeping the two outcomes apart.

    Deduplicates: two legacy spellings of one category ("Fashion", "fashion")
    merge onto a single canonical label, and that label must receive the event's
    weight ONCE, not twice. Without this a user who wrote the same category two
    ways would be credited double for a single action.
    """
    resolved: list[str] = []
    dropped: list[str] = []

    for value in supplied:
        canonical = vocabulary.resolve(value)
        if canonical is None:
            dropped.append(value)
        elif canonical not in resolved:
            resolved.append(canonical)

    return CategoryResolution(resolved=resolved, dropped=dropped)


# --- ENG-03: the 23, matched by name ----------------------------------------------


def _direct(vocabulary: CategoryVocabulary, label: str, category_map: dict[str, str] | None) -> tuple[str | None, str | None]:
    """The direct rule: (one of the 23, None), or (None, reason). By name first, then
    the category map's entry for the label itself, whose target must be one of the 23."""
    by_name = vocabulary._canonical_by_key()
    found = by_name.get(to_category_key(label))
    if found is not None:
        return found, None
    mapped = {to_category_key(k): v for k, v in (category_map or {}).items()}.get(to_category_key(label))
    if mapped is None:
        return None, None
    target = by_name.get(to_category_key(mapped)) if isinstance(mapped, str) else None
    return (target, None) if target else (None, MAP_NOT_TO_23)


def canonical_name(
    vocabulary: CategoryVocabulary,
    label: object,
    category_map: dict[str, str] | None = None,
    tree: CategoryTree | None = None,
) -> str | None:
    """ENG-03: the one of the 23 this label names, or None to drop it.

    With the platform's category tree (the engine's readers always pass it), the
    tree rule of 26 Oct 2026 applies: see resolve_label. Without it, the direct
    rule only: matched by NAME -- case and spacing ignored -- then, ENG-29 item 1,
    the category map in the settings, whose target must itself be one of the 23.
    The legacy map is never consulted. Anything unmatched is dropped, never guessed.
    """
    if tree is not None:
        return resolve_label(vocabulary, label, category_map, tree).category
    if not isinstance(label, str) or not label.strip():
        return None
    return _direct(vocabulary, label, category_map)[0]


def post_categories(
    vocabulary: CategoryVocabulary,
    supplied: object,
    category_map: dict[str, str] | None = None,
    tree: CategoryTree | None = None,
) -> CategoryResolution:
    """A post's (or a user's declared) categories, each matched to the 23 (canonical_name). Unmatched ones are dropped."""
    labels = [supplied] if isinstance(supplied, str) else supplied if isinstance(supplied, list) else []
    resolved: list[str] = []
    dropped: list[str] = []
    for label in labels:
        name = canonical_name(vocabulary, label, category_map, tree)
        if name is None:
            dropped.append(str(label))
        elif name not in resolved:
            resolved.append(name)
    return CategoryResolution(resolved=resolved, dropped=dropped)


# --- the tree rule (ENG-03, ENG-29 item 1; review of 26 Oct 2026) -----------------------
#
# A label is mapped through its actual top-level parent in the platform's category
# tree. The top counts if it is one of the 23 (by name), or if the category map
# points it straight to one of the 23. Otherwise the label is left unmapped, with a
# reason, and listed -- never guessed from the label, product or seller name.

#: Why a label is unmapped.
NOT_IN_TREE = "not_in_tree"  # no node has this name (or id), and no direct rule maps it
NO_PARENT = "no_parent"  # a node whose top-level parent cannot be reached
TOP_NOT_MAPPED = "top_not_mapped"  # the top is not one of the 23 and the map has no entry for it
MAP_NOT_TO_23 = "map_not_to_23"  # a map entry (the label's, or its top's) whose target is not one of the 23
AMBIGUOUS = "ambiguous"  # the label would end up in two different categories (or cannot be told apart)
EMPTY = "empty"  # not a label at all: missing, blank or not text

UNMAPPED_REASONS = (NOT_IN_TREE, NO_PARENT, TOP_NOT_MAPPED, MAP_NOT_TO_23, AMBIGUOUS, EMPTY)

#: How a label was mapped.
VIA_NAME = "one of the 23"
VIA_MAP = "category map"
VIA_TREE = "tree"
VIA_TREE_AND_MAP = "tree and category map"


class CategoryNode(BaseModel):
    model_config = {"frozen": True}

    category_id: str
    name: str | None
    parent_id: str | None
    level: int | None


class TopOutcome(BaseModel):
    """Where one node's chain of parents ends, and what that top counts as."""

    model_config = {"frozen": True}

    top: str | None  # the top-level node's name, if reached
    category: str | None  # one of the 23, or None
    reason: str | None  # NO_PARENT, TOP_NOT_MAPPED or MAP_NOT_TO_23 when category is None


class CategoryTree(BaseModel):
    """The platform's categories collection, as a tree of parents (_id, name, parent, level)."""

    model_config = {"frozen": True}

    nodes: dict[str, CategoryNode] = Field(default_factory=dict)
    _names: dict[str, list[str]] | None = PrivateAttr(default=None)

    @classmethod
    def build(cls, category_docs: list[dict]) -> CategoryTree:
        from reco.platform.ids import maybe_str

        nodes: dict[str, CategoryNode] = {}
        for doc in category_docs:
            category_id = maybe_str(doc.get("_id"))
            if category_id is None:
                continue
            name = doc.get("name")
            level = doc.get("level")
            nodes[category_id] = CategoryNode(
                category_id=category_id,
                name=name if isinstance(name, str) and name.strip() else None,
                parent_id=maybe_str(doc.get("parent")) if doc.get("parent") is not None else None,
                level=level if isinstance(level, int) and not isinstance(level, bool) else None,
            )
        return cls(nodes=nodes)

    def _by_name(self) -> dict[str, list[str]]:
        if self._names is None:
            found: dict[str, list[str]] = {}
            for node in self.nodes.values():
                if node.name:
                    found.setdefault(to_category_key(node.name), []).append(node.category_id)
            self._names = found
        return self._names

    def named(self, label: str) -> list[CategoryNode]:
        """Every node with this name (case and spacing ignored), in id order."""
        return [self.nodes[i] for i in sorted(self._by_name().get(to_category_key(label), []))]

    def top_node(self, category_id: str) -> CategoryNode | None:
        """The node's top-level parent, following parent links; None when the chain
        breaks (a parent not in the tree), loops, or ends at a node that has no parent
        but says it is below the top (level above 0)."""
        seen: set[str] = set()
        node = self.nodes.get(category_id)
        while node is not None and node.category_id not in seen:
            seen.add(node.category_id)
            if node.parent_id is None:
                return node if node.level in (None, 0) else None
            node = self.nodes.get(node.parent_id)
        return None

    def path_of(self, category_id: str) -> list[str]:
        """The names from the top down to this node, as far as the parent links go."""
        names: list[str] = []
        seen: set[str] = set()
        node = self.nodes.get(category_id)
        while node is not None and node.category_id not in seen:
            seen.add(node.category_id)
            names.insert(0, node.name or f"(unnamed {node.category_id})")
            node = self.nodes.get(node.parent_id) if node.parent_id else None
        return names


def top_outcome(
    vocabulary: CategoryVocabulary, tree: CategoryTree, category_id: str, category_map: dict[str, str] | None
) -> TopOutcome:
    """One node's top, and whether it counts: one of the 23 by name, or pointed straight
    to one of the 23 by the category map. Only the top's own name is used."""
    top = tree.top_node(category_id)
    if top is None or not top.name:
        return TopOutcome(top=None, category=None, reason=NO_PARENT)
    category, reason = _direct(vocabulary, top.name, category_map)
    return TopOutcome(top=top.name, category=category, reason=None if category else reason or TOP_NOT_MAPPED)


class LabelResolution(BaseModel):
    """How one label resolved: the one of the 23 it counts in, or why it is unmapped."""

    model_config = {"frozen": True}

    label: str
    category: str | None
    via: str | None = None  # VIA_NAME, VIA_MAP, VIA_TREE or VIA_TREE_AND_MAP when mapped
    reason: str | None = None  # one of UNMAPPED_REASONS when unmapped
    tops: list[str] = Field(default_factory=list)  # the tree tops the label's nodes reach
    note: str = ""  # what the reviewer should know (e.g. where tree and map disagree)


def _tree_side(
    vocabulary: CategoryVocabulary, tree: CategoryTree, ids: list[str], category_map: dict[str, str] | None
) -> tuple[str | None, str | None, list[str], str]:
    """(category, reason, tops, note) for a set of nodes the label may mean.

    Mapped only when every node resolves, and all to the same one of the 23: two
    nodes of one name ending in different categories (or one ending nowhere) cannot
    be told apart, so the label is ambiguous."""
    if not ids:
        return None, NOT_IN_TREE, [], ""
    outcomes = [top_outcome(vocabulary, tree, i, category_map) for i in ids]
    tops = sorted({o.top for o in outcomes if o.top})
    categories = sorted({o.category for o in outcomes if o.category})
    failures = sorted({o.reason for o in outcomes if o.category is None and o.reason})
    if len(categories) > 1:
        return None, AMBIGUOUS, tops, f"{len(ids)} nodes of this name end in {', '.join(categories)}"
    if categories and failures:
        return None, AMBIGUOUS, tops, (f"{len(ids)} nodes of this name: some end in {categories[0]}, "
                                       f"some are unmapped ({', '.join(failures)})")
    if categories:
        return categories[0], None, tops, ""
    for reason in (MAP_NOT_TO_23, TOP_NOT_MAPPED, NO_PARENT):
        if reason in failures:
            return None, reason, tops, ""
    return None, NO_PARENT, tops, ""  # pragma: no cover - every failure carries a reason


def resolve_label(
    vocabulary: CategoryVocabulary, label: object, category_map: dict[str, str] | None, tree: CategoryTree
) -> LabelResolution:
    """The tree rule for a category NAME (a post category, a declared interest, a
    business category). Decisions of 26 Oct 2026 (docs/engineering/ENG-29.md):

    1. A label that is itself one of the 23 (case and spacing ignored) is that
       category: ENG-03 matches a post's categories to the 23 by name, and the
       Build List governs. Where the tree puts a node of that name under another
       top, it is noted for the reviewer, not applied.
    2. Otherwise the label's node(s) are found by name in the tree and followed to
       their top; the top counts if it is one of the 23 or the category map points it
       straight to one of the 23.
    3. The category map's entry for the label itself (the direct map) still applies.
       Where tree and direct map both give a category and they differ, the label is
       ambiguous: neither is picked. Where only one gives a category, it is used
       (with a note when the tree's top was not mapped).
    4. A direct map entry whose target is not one of the 23 leaves the label unmapped
       (map_not_to_23), whatever the tree says: the entry itself is wrong.
    """
    if not isinstance(label, str) or not label.strip():
        return LabelResolution(label=str(label), category=None, reason=EMPTY)
    by_name = vocabulary._canonical_by_key().get(to_category_key(label))
    nodes = tree.named(label)
    tree_category, tree_reason, tops, tree_note = _tree_side(vocabulary, tree, [n.category_id for n in nodes], category_map)

    if by_name is not None:
        note = ""
        if tree_category not in (None, by_name) or tree_reason == AMBIGUOUS:
            note = f"one of the 23 by name; the tree puts it under {', '.join(tops)}" + (
                f" ({tree_category})" if tree_category else "")
        return LabelResolution(label=label, category=by_name, via=VIA_NAME, tops=tops, note=note)

    direct, direct_reason = _direct(vocabulary, label, category_map)
    if direct_reason == MAP_NOT_TO_23:
        return LabelResolution(label=label, category=None, reason=MAP_NOT_TO_23, tops=tops,
                               note=f"the category map points it to {_map_target(label, category_map)!r}, not one of the 23")
    if direct is not None and tree_category is not None:
        if direct == tree_category:
            return LabelResolution(label=label, category=direct, via=VIA_TREE_AND_MAP, tops=tops)
        return LabelResolution(label=label, category=None, reason=AMBIGUOUS, tops=tops,
                               note=f"tree: {tree_category} (under {', '.join(tops)}); category map: {direct}")
    if direct is not None:
        if tree_reason == AMBIGUOUS:
            return LabelResolution(label=label, category=None, reason=AMBIGUOUS, tops=tops,
                                   note=f"category map: {direct}; tree: {tree_note}")
        note = "" if tree_reason == NOT_IN_TREE else f"tree: {tree_reason} (under {', '.join(tops) or 'no top'})"
        return LabelResolution(label=label, category=direct, via=VIA_MAP, tops=tops, note=note)
    if tree_category is not None:
        return LabelResolution(label=label, category=tree_category, via=VIA_TREE, tops=tops)
    return LabelResolution(label=label, category=None, reason=tree_reason, tops=tops, note=tree_note)


def resolve_category_id(
    vocabulary: CategoryVocabulary, category_id: object, category_map: dict[str, str] | None, tree: CategoryTree
) -> LabelResolution:
    """The tree rule for a category ID (a product's categoryPathIds[0], else
    basicInfo.categoryId): the node is found by id and followed to its top. An id
    names one node, so it is never ambiguous, and no direct rule applies to it."""
    from reco.platform.ids import maybe_str

    key = maybe_str(category_id) if category_id is not None else None
    if not key:
        return LabelResolution(label="(no category id)", category=None, reason=EMPTY)
    if key not in tree.nodes:
        return LabelResolution(label=f"category id {key}", category=None, reason=NOT_IN_TREE)
    outcome = top_outcome(vocabulary, tree, key, category_map)
    label = f"{' > '.join(tree.path_of(key))} (category id {key})"
    tops = [outcome.top] if outcome.top else []
    if outcome.category is None:
        return LabelResolution(label=label, category=None, reason=outcome.reason, tops=tops)
    return LabelResolution(label=label, category=outcome.category, via=VIA_TREE, tops=tops)


def _map_target(label: str, category_map: dict[str, str] | None) -> object:
    return {to_category_key(k): v for k, v in (category_map or {}).items()}.get(to_category_key(label))


class ProductCategoryIndex(BaseModel):
    """ENG-03: a product's category id -> one of the 23, via the categories tree.

    v1.3: "a product's categoryPathIds must start with one of the 23". The id
    (categoryPathIds[0], or basicInfo.categoryId where the path is absent) is
    looked up in categories by id and followed up its parents to the top-level
    node, which must be one of the 23 -- by name, or through the category map
    (ENG-29; the tree rule of 26 Oct 2026). Unmapped -> None.
    """

    model_config = {"frozen": True}

    by_id: dict[str, str | None] = Field(default_factory=dict)

    @classmethod
    def build(
        cls, vocabulary: CategoryVocabulary, category_docs: list[dict], category_map: dict[str, str] | None = None
    ) -> ProductCategoryIndex:
        return cls.from_tree(vocabulary, CategoryTree.build(category_docs), category_map)

    @classmethod
    def from_tree(
        cls, vocabulary: CategoryVocabulary, tree: CategoryTree, category_map: dict[str, str] | None = None
    ) -> ProductCategoryIndex:
        return cls(by_id={i: top_outcome(vocabulary, tree, i, category_map).category for i in tree.nodes})

    def category_of(self, category_id: object) -> str | None:
        from reco.platform.ids import maybe_str

        key = maybe_str(category_id) if category_id is not None else None
        return self.by_id.get(key) if key else None
