"""The eligibility checks a served item passes today. ENG-06 (interim), ENG-08.

ENG-06 serves on test before the filters (ENG-08) are built: "On test, return
eligible posts newest first". Until ENG-08, eligible means what the platform
records already say about the item itself:

    post     visibility public (E-04), not hidden (E-04), compliance not
             rejected or removed (E-12), not deranked
    product  status Activate(d), ignoring case (E-07), in stock (E-06)

ENG-08 replaces this with the full rule set: blocks, author status and privacy,
restriction levels and ml_item_state (ENG-27).
"""

from __future__ import annotations

from reco.platform.records import PostRecord, ProductRecord, status_is

#: compliance.status values that keep a post off every list.
_BLOCKED_COMPLIANCE = ("rejected", "removed", "deranked", "blocked")


def post_is_eligible(post: PostRecord) -> bool:
    if post.is_hidden or not status_is(post.visibility, "public"):
        return False
    return not any(status_is(post.compliance_status, s) for s in _BLOCKED_COMPLIANCE)


def product_is_eligible(product: ProductRecord) -> bool:
    return product.is_active and product.in_stock
