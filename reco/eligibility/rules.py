"""The eligibility rules E-01 to E-12. ENG-08. Pure: no database.

    post_rule(post, author, viewer)            -> "E-04" | ... | None (eligible)
    product_rule(product, seller, variants, viewer)
    item_rule(...)                              the right one for a candidate

No model can override these (ENG-08). They are applied before scoring and again
on the final list; every exclusion is logged with request_id, item_id and the
rule id by the caller (reco.eligibility.apply).

The first rule an item fails is the one reported, in E-number order. Where the
pack is silent, the choice made is noted on the rule:

    E-01  blocks, either direction, for user and business accounts. Read from the
          platform when each list is built (followers, status blocked).
    E-02  the viewer muted the author (feedback_type mute_author).
    E-03  the viewer chose not_interested, hide or report on the item, within
          the last 90 days.
    E-04  posts.isHidden true, or visibility not 'public'.
    E-05  the author's account is private and the viewer does not follow them.
    E-06  a product post whose Product_status is not 'Activated'; 'N/A' passes.
          Silent: a missing Product_status passes only when the post carries no
          product.
    E-07  a product is sellable only if status 'Activate', in stock, and at least
          one active variant has quantity minus reservedStock above 0.
    E-08  the author or seller is not active (status ignoring case). As in ENG-03,
          a missing status is not 'active' (Kala question 17).
    E-09  restriction_level suspended or removed -- switches on by itself once
          DB-08 adds the field.
    E-10  the viewer's own posts and products (their user id and their businesses).
    E-11  an ageGroup marking adult-only content is shown only to viewers 18 or
          over by users.DOB; no DOB means not shown. Silent: any ageGroup other
          than 'All' (or empty) is treated as adult-only.
    E-12  compliance.status deranked or removed; under review is served.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Union

from reco.platform.records import BusinessRecord, PostRecord, ProductRecord, UserRecord, VariantRecord, status_is

Account = Union[UserRecord, BusinessRecord]

RULES: dict[str, str] = {
    "E-01": "blocked, in either direction",
    "E-02": "the viewer muted the author",
    "E-03": "the viewer chose not interested, hide or report",
    "E-04": "post hidden or not public",
    "E-05": "private author the viewer does not follow",
    "E-06": "product post whose product is not Activated",
    "E-07": "product not sellable",
    "E-08": "author or seller not active",
    "E-09": "author or seller suspended or removed",
    "E-10": "the viewer's own item",
    "E-11": "adult-only content for a viewer under 18 or with no DOB",
    "E-12": "post deranked or removed",
}

#: E-12: compliance.status values that keep a post off every list.
BLOCKED_COMPLIANCE = ("deranked", "removed")
#: E-09 (DB-08): restriction levels that keep an account's items off every list.
BLOCKED_RESTRICTIONS = ("suspended", "removed")


@dataclass(frozen=True)
class Viewer:
    """What the rules need to know about the person the list is for."""

    user_id: str | None
    own_ids: frozenset[str] = frozenset()  # their user id and their businesses' ids (E-10)
    follows: frozenset[str] = frozenset()  # accounts they follow (E-05)
    blocked: frozenset[str] = frozenset()  # accounts blocked either way (E-01)
    muted: frozenset[str] = frozenset()  # authors they muted (E-02)
    dismissed: frozenset[str] = frozenset()  # items: not interested, hide, report, last 90 days (E-03)
    in_cart: frozenset[str] = frozenset()  # products in their cart: never on a product list (Kala, 16 Oct)
    date_of_birth: date | None = None
    today: date = field(default_factory=date.today)

    @property
    def is_adult(self) -> bool:
        dob = self.date_of_birth
        if dob is None:
            return False
        years = self.today.year - dob.year - ((self.today.month, self.today.day) < (dob.month, dob.day))
        return years >= 18


def _account_id(account: Account) -> str:
    return account.user_id if isinstance(account, UserRecord) else account.business_id


def account_rule(account: Account | None) -> str | None:
    """E-08 and E-09 on the author or seller. An account not found is not active."""
    if account is None or not account.is_active:
        return "E-08"
    if account.restriction_level in BLOCKED_RESTRICTIONS:
        return "E-09"
    return None


def _is_adult_only(age_group: str | None) -> bool:
    return bool(age_group and age_group.strip()) and not status_is(age_group, "All")


def post_rule(post: PostRecord, author: Account | None, viewer: Viewer) -> str | None:
    author_id = post.author_id
    if author_id in viewer.blocked:
        return "E-01"
    if author_id in viewer.muted:
        return "E-02"
    if post.post_id in viewer.dismissed:
        return "E-03"
    if post.is_hidden or not status_is(post.visibility, "public"):
        return "E-04"
    if author is not None and not author.account_is_public and author_id not in viewer.follows and author_id not in viewer.own_ids:
        return "E-05"
    if post.product_ids or (post.product_status and not status_is(post.product_status, "N/A")):
        if not status_is(post.product_status, "Activated"):
            return "E-06"
    rule = account_rule(author)
    if rule:
        return rule
    if author_id in viewer.own_ids:
        return "E-10"
    if _is_adult_only(post.age_group) and not viewer.is_adult:
        return "E-11"
    if any(status_is(post.compliance_status, s) for s in BLOCKED_COMPLIANCE):
        return "E-12"
    return None


def product_is_sellable(product: ProductRecord, variants: list[VariantRecord] | None) -> bool:
    """E-07: status 'Activate', in stock, and an active variant with stock above 0.
    With variants None (not read yet), only the product's own fields are checked."""
    if not (product.is_active and product.in_stock):
        return False
    return variants is None or any(v.is_active and (v.stock or 0) > 0 for v in variants)


def product_rule(
    product: ProductRecord, seller: Account | None, variants: list[VariantRecord] | None, viewer: Viewer
) -> str | None:
    """With variants None, every rule but E-07's variant stock is checked."""
    seller_id = product.seller_id
    if seller_id in viewer.blocked:
        return "E-01"
    if seller_id in viewer.muted:
        return "E-02"
    if product.product_id in viewer.dismissed:
        return "E-03"
    if not product_is_sellable(product, variants):
        return "E-07"
    rule = account_rule(seller)
    if rule:
        return rule
    if seller_id in viewer.own_ids:
        return "E-10"
    return None
