"""M5's fallback order, and the step a list records. ENG-17. Pure: no database.

    steps = ladder(method, method_one="attribute_similarity", method_two="bought_together")
    step  = reported_step(used)          # the response's and the E1's fallback_step
    found = fill(sources, wanted, exclude)

Build List v1.4 ENG-17: "When method two has nothing (no pair reaches 2
co-purchases, which will be true for most products at launch), fall back in this
order and record which step was used: 1. the method-one list for that product;
2. eligible products in the same top-level category, most popular first;
3. eligible products, newest first. A user assigned to method two never gets an
empty list." And: a request "returns exactly limit items, or fewer only when fewer
eligible products exist".

So a list is filled from its sources in order, each one after the filters and the
exclusions (the viewed product, every product in the viewer's cart), until it
holds what the request needs:

    bought_together        its own list, then step 1, step 2, step 3
    attribute_similarity   its own list, then step 2, step 3

Where the pack is silent (decided 17 Oct 2026, docs/engineering/ENG-17.md):

  - A method's own list that is short is filled by the next steps too, so a list is
    always full when enough eligible products exist; "has nothing" is the case of
    an empty own list.
  - Method one has no list for a product only when the product is newer than the
    last nightly batch, or no batch is current: it then takes steps 2 and 3 (its
    own list is step 1 of method two's ladder, so it skips that one).
  - fallback_step is null when the method's own list filled the page; otherwise the
    first fallback step that added a product: "product_step_1", "product_step_2" or
    "product_step_3". The E1 record also keeps every step used and how many products
    each added.
  - A current batch older than interest.stale_after_hours (48) is not read: the
    ladder takes over (ENG-22 check 10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

#: The sources a list can come from. OWN is the assigned method's own stored list.
OWN = "own"
STEP_1 = "product_step_1"  # the method-one list for that product
STEP_2 = "product_step_2"  # eligible products in the same top-level category, most popular first
STEP_3 = "product_step_3"  # eligible products, newest first

STEP_DESCRIPTION = {
    OWN: "the assigned method's own list",
    STEP_1: "the method-one (attribute similarity) list for that product",
    STEP_2: "eligible products in the same top-level category, most popular first",
    STEP_3: "eligible products, newest first",
}


def ladder(method: str, *, method_one: str, method_two: str) -> tuple[str, ...]:
    """The sources a list is filled from, in order, for the user's assigned method."""
    if method == method_two:
        return (OWN, STEP_1, STEP_2, STEP_3)
    return (OWN, STEP_2, STEP_3)


def reported_step(used: Iterable[str]) -> str | None:
    """The fallback step a list records: None when only the method's own list was
    used; else the first fallback step that added a product."""
    for step in used:
        if step != OWN:
            return step
    return None


@dataclass
class Filled:
    product_ids: list[str]
    added: dict[str, int]  # source -> products it added, in the order used

    @property
    def fallback_step(self) -> str | None:
        return reported_step(s for s, n in self.added.items() if n > 0)

    @property
    def method_served(self) -> bool:
        """Whether the assigned method's own list served anything (SD-23)."""
        return self.added.get(OWN, 0) > 0


def take(found: list[str], seen: set[str], candidates: Iterable[str], exclude: set[str] | frozenset[str],
         wanted: int) -> int:
    """Append the `candidates` not yet in `found` and not excluded, until `wanted`.
    Returns how many were added."""
    added = 0
    for pid in candidates:
        if len(found) >= wanted:
            break
        if pid in seen or pid in exclude:
            continue
        seen.add(pid)
        found.append(pid)
        added += 1
    return added


def fill(sources: Iterable[tuple[str, Iterable[str]]], wanted: int, exclude: set[str] | frozenset[str]) -> Filled:
    """The list from already-filtered sources, in order, until `wanted` products."""
    found: list[str] = []
    seen: set[str] = set()
    added: dict[str, int] = {}
    for name, candidates in sources:
        if len(found) >= wanted:
            break
        added[name] = take(found, seen, candidates, exclude, wanted)
    return Filled(found, added)
