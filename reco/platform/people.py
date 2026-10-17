"""Who is behind an account, and who promoted an order. ENG-30 points 1 and 2.

    people = People.of(businesses)            # from the businessregisters records
    people.person_of("store-id")  -> "owner-user-id"
    people.same_person("user-id", "store-id")  -> True when the store is the user's
    promoter_of(order, post_authors)  -> the order's promoter, or None

Point 1, promoter on an order: orders.promoter_id (text; a user or a store) is the
author of the order's post. If it is missing or null and post_id is set, take
posts.userId of that post. Orders created before 23 September 2026 have none, and
no backfill is run.

Point 2, one person: a personal account, and every store whose
businessregisters.user_id (text) is that account's id, count as one person. Used
for self-purchase (ENG-16, ENG-21) and own products (ENG-18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class People:
    """Store id -> the personal account that owns it."""

    owners: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, businesses: Iterable[Any]) -> People:
        return cls({b.business_id: b.owner_user_id for b in businesses if getattr(b, "owner_user_id", None)})

    def person_of(self, account_id: str | None) -> str | None:
        """The person an account belongs to: a store's owner, else the account itself."""
        if not account_id:
            return None
        return self.owners.get(str(account_id), str(account_id))

    def same_person(self, a: str | None, b: str | None) -> bool:
        return bool(a and b) and self.person_of(a) == self.person_of(b)


def promoter_of(order: Mapping[str, Any], post_authors: Mapping[str, str]) -> str | None:
    """orders.promoter_id, else the author of the order's post, else None."""
    promoter = order.get("promoter_id")
    if promoter:
        return str(promoter)
    post_id = order.get("post_id")
    return post_authors.get(str(post_id)) if post_id else None
