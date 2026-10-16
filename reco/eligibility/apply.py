"""Applying E-01 to E-12 to real items, and logging every exclusion. ENG-08.

    viewer = await viewer_context(settings, user_id)
    kept   = await eligible_posts(settings, posts, viewer, request_id)
    kept   = await eligible_products(settings, products, viewer, request_id)
    failed = await recheck(settings, items, viewer, request_id)    # just before a list is returned

Every exclusion is logged with request_id, item_id and the rule id (ENG-08), one
line each on the reco.eligibility logger.

Until ENG-27 keeps ml_item_state, the item-level rules (E-04 to E-09, E-12) read
the platform directly for the items in hand; ENG-27 moves them onto its state,
refreshed every 15 minutes, and the recheck stays a platform read.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Iterable

from reco.config import Settings, live
from reco.eligibility.rules import Account, Viewer, post_rule, product_is_sellable, product_rule
from reco.platform import fetch
from reco.platform.records import PostRecord, ProductRecord, VariantRecord
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.eligibility")

_DISMISSING = ("not_interested", "hide", "report")


async def viewer_context(settings: Settings, user_id: str | None) -> Viewer:
    """Who the list is for: own accounts, follows, blocks (from the platform, now),
    mutes and dismissals (from the engine's copy of feedback events), and DOB."""
    if not user_id:
        return Viewer(user_id=None)
    # One round trip for the usual viewer: blocks are read for the user id at the
    # same time; a second read only when the viewer also owns businesses.
    users, businesses, follows, blocks, feedback, cart = await asyncio.gather(
        fetch.read_where(settings, "user", "_id", [user_id]),
        fetch.read_where(settings, "business", "user_id", [user_id]),
        fetch.read_where(settings, "follow", "userId", [user_id]),
        fetch.read_blocks(settings, [user_id]),
        # E-03's window is the setting filters.feedback_hide_days (90; 30 to 365).
        writers.read_viewer_feedback(settings, user_id, utc_now() - timedelta(days=live.current().filters.feedback_hide_days)),
        # Kala, 16 Oct (ENG-17 Q7): every product already in the user's cart is left out
        # of every product list; the engine reads the cart itself.
        fetch.read_where(settings, "cart_line", "user_id", [user_id]),
    )
    own = {user_id, *(b.business_id for b in businesses)}
    if len(own) > 1:
        blocks = [*blocks, *await fetch.read_blocks(settings, sorted(own - {user_id}))]
    blocked = {b.blocked_id if b.blocker_id in own else b.blocker_id for b in blocks}
    muted, dismissed, mute_posts = set(), set(), []
    for row in feedback:
        kind = str(row.get("feedback_type") or "").lower()
        target, target_type = row.get("target_id"), str(row.get("target_type") or "").lower()
        if kind == "mute_author":
            # E13: target_type author names the author; otherwise the followed
            # account, or the author of the post the mute was made on.
            author = target if target and target_type == "author" else row.get("influencer_id")
            if author:
                muted.add(str(author))
            elif row.get("post_id") or (target and target_type == "post"):
                mute_posts.append(row.get("post_id") or target)
        elif kind in _DISMISSING:
            if target and target_type in ("post", "product"):
                dismissed.add(str(target))
            dismissed.update(str(row[k]) for k in ("item_id", "post_id", "product_id") if row.get(k))
    if mute_posts:  # a mute recorded against a post: the author is muted
        muted.update(p.author_id for p in await fetch.read_where(settings, "post", "_id", mute_posts))
    return Viewer(
        user_id=user_id,
        own_ids=frozenset(own),
        follows=frozenset(f.followed_id for f in follows),
        in_cart=frozenset(line.product_id for line in cart if line.product_id),
        blocked=frozenset(blocked),
        muted=frozenset(muted),
        dismissed=frozenset(dismissed),
        date_of_birth=users[0].date_of_birth if users else None,
    )


#: Accounts already read for this request: id -> record, or None if not found.
AccountCache = dict[str, "Account | None"]


async def _accounts(settings: Settings, ids: Iterable[str], cache: AccountCache | None = None) -> dict[str, Account]:
    """Authors and sellers: an id may be a user or a business account. Within one
    request each account is read once (the cache), however many items it has."""
    cache = cache if cache is not None else {}
    wanted = sorted({i for i in ids if i and i not in cache})
    if wanted:
        users, businesses = await asyncio.gather(
            fetch.read_where(settings, "user", "_id", wanted),
            fetch.read_where(settings, "business", "_id", wanted),
        )
        found = {**{u.user_id: u for u in users}, **{b.business_id: b for b in businesses}}
        cache.update({i: found.get(i) for i in wanted})
    return {i: a for i in ids if i and (a := cache.get(i)) is not None}


def _log(request_id: str | None, item_id: str, rule: str, item_type: str) -> None:
    logger.info("excluded", extra={"request_id": request_id, "item_id": item_id, "item_type": item_type, "rule": rule})


async def eligible_posts(
    settings: Settings, posts: list[PostRecord], viewer: Viewer, request_id: str | None = None,
    cache: AccountCache | None = None,
) -> list[PostRecord]:
    """E-01 to E-12 on posts; a post card showing a product also needs that product
    sellable (E-07: out-of-stock products are never shown, DS-017 4.5)."""
    shown = sorted({p.product_ids[0] for p in posts if p.product_ids})
    authors, products, variant_rows = await asyncio.gather(
        _accounts(settings, [p.author_id for p in posts], cache),
        fetch.read_where(settings, "product", "_id", shown),
        fetch.read_where(settings, "variant", "productId", shown),
    )
    by_id = {p.product_id: p for p in products}
    variants: dict[str, list[VariantRecord]] = defaultdict(list)
    for v in variant_rows:
        variants[v.product_id].append(v)
    kept = []
    for post in posts:
        rule = post_rule(post, authors.get(post.author_id), viewer)
        if rule is None and post.product_ids:
            product = by_id.get(post.product_ids[0])
            if product is None or not product_is_sellable(product, variants[product.product_id]):
                rule = "E-07"
        if rule:
            _log(request_id, post.post_id, rule, "post")
        else:
            kept.append(post)
    return kept


async def eligible_products(
    settings: Settings, products: list[ProductRecord], viewer: Viewer, request_id: str | None = None,
    cache: AccountCache | None = None,
) -> list[ProductRecord]:
    """The checks that need no variants run first; variants (E-07's stock) are read
    only for products that can still pass."""
    sellers = await _accounts(settings, [p.seller_id for p in products if p.seller_id], cache)
    kept, pending = [], []
    for product in products:
        seller = sellers.get(product.seller_id or "")
        rule = product_rule(product, seller, None, viewer)
        if rule:
            _log(request_id, product.product_id, rule, "product")
        else:
            pending.append((product, seller))
    if not pending:
        return kept
    variants: dict[str, list[VariantRecord]] = defaultdict(list)
    for v in await fetch.read_where(settings, "variant", "productId", [p.product_id for p, _ in pending]):
        variants[v.product_id].append(v)
    for product, seller in pending:
        rule = product_rule(product, seller, variants[product.product_id], viewer)
        if rule:
            _log(request_id, product.product_id, rule, "product")
        else:
            kept.append(product)
    return kept


async def recheck(
    settings: Settings, items: list[dict[str, Any]], viewer: Viewer, request_id: str | None,
    cache: AccountCache | None = None,
) -> set[str]:
    """ENG-08: before a list is returned, its items are re-read on the platform (one
    read per list, for the returned ids) for blocks, visibility and stock. Returns
    the item_ids that now fail. Accounts read earlier in the same request are
    reused (`cache`); blocks were read from the platform when the list was built."""
    # A card with a post id is a post card -- including one showing a product,
    # whose item_type is product (X-16, F10); product rails carry product ids only.
    post_ids = [i["item_id"] for i in items if i.get("post_id")]
    product_ids = [i["item_id"] for i in items if not i.get("post_id")]
    failed: set[str] = set()
    if post_ids:
        posts = await fetch.read_where(settings, "post", "_id", post_ids)
        still = {p.post_id for p in await eligible_posts(settings, posts, viewer, request_id, cache)}
        failed |= set(post_ids) - still
    if product_ids:
        products = await fetch.read_where(settings, "product", "_id", product_ids)
        still = {p.product_id for p in await eligible_products(settings, products, viewer, request_id, cache)}
        failed |= set(product_ids) - still
    return failed
