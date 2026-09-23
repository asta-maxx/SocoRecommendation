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
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
                "LEGACY_LABEL_MAP is NOT loaded (%s). Legacy category names will "
                "be dropped and counted rather than merged onto their canonical "
                "category. Scores are correct but incomplete: a user whose "
                "activity is entirely under legacy names will score nothing. "
                "Export categories.js to fix.",
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
