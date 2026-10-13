"""M1's inputs from the engine's own copies. ENG-10 (Build List v1.3).

    inputs = await read_inputs(settings, anchor)
    inputs.events_by_user[user_id] -> [Event, ...]   what the two methods score
    inputs.declared[user_id]       -> [category]     the floor (10 each, never decays)
    inputs.user_ids                                   every platform user

Each action is read from one place only, so nothing is counted twice (ENG-10):

    qualified views     ml_events view rows; dwell_ms >= 3 s; one per viewer per post
    likes, saves,       ml_events like / save / comment / share / add_to_cart rows
      comments, shares,
      add-to-carts
    clicks              ml_events click rows (product_click from older builds too)
    Not interested,     ml_events feedback rows (not_interested, hide): -5 on the
      Hide                item's category
    purchases           ml_orders: the order itself, at its creation time
    business follows    the platform's follows (followingReference businessRegister),
                        on the business's category, which must be one of the 23

Undo: an undone action (undone_at set) and the undo row itself (undo_of) both
contribute nothing. That is the pack's "the undo removes the weight of the action
it undoes, aged from the original action's time", applied once: weight minus the
same weight at the same age is exactly zero.

Reversal: an order that is Cancelled or Rejected (order_status), or reached Return
Requested or Returned, contributes nothing: its +20 and its -20 are both aged
from the order's creation, so it nets to exactly zero, once.

Incognito orders count for the buyer (purchase privacy only). Impressions,
remove_from_cart and the other new platform events carry no weight. Only user
accounts are scored. Every category is matched to the 23 (ENG-03); anything else
is dropped and counted.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from reco.config import Settings, live
from reco.platform import fetch
from reco.platform.ids import as_utc, to_str
from reco.platform.records import status_is
from reco.slots.interest.events import Event, EventType, ReadStats
from reco.store import writers

logger = logging.getLogger(__name__)

#: postevents type -> M1 action. feedback is narrowed by feedback_type below.
ACTION = {
    "view": EventType.VIEW,
    "click": EventType.CLICK,
    "product_click": EventType.CLICK,
    "like": EventType.LIKE,
    "save": EventType.SAVE,
    "comment": EventType.COMMENT,
    "share": EventType.SHARE,
    "add_to_cart": EventType.CART,
    "feedback": EventType.FEEDBACK,
}

#: Feedback that carries the −5 (ENG-10). Mute and report filter (ENG-08) but don't score.
WEIGHTED_FEEDBACK = {"not_interested", "hide"}

_POSTS_PER_READ = 500
_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class CopyInputs:
    events_by_user: dict[str, list[Event]]
    declared: dict[str, list[str]]
    user_ids: list[str]
    read_stats: ReadStats
    #: What was left out before scoring, and why (logged with the run).
    skipped: Counter = field(default_factory=Counter)


def _is_reversed(order: dict[str, Any]) -> bool:
    statuses = live.current().lists.order_status
    status = order.get("status")
    return bool(
        order.get("is_returned") or order.get("cancelled_at")
        or status_is(status, statuses.cancelled) or status_is(status, statuses.rejected)
    )


def _latest_qualified_views(rows: list[dict[str, Any]], qualified_ms: float) -> list[dict[str, Any]]:
    """One view per viewer per post (ENG-10): the most recent qualified one, so a
    re-watch keeps the interest current. A pair with no qualified view keeps its
    most recent view, which the method then counts as below the threshold."""
    best: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("user_id"), row.get("post_id") or row.get("_id"))
        held = best.get(key)
        qualified = (row.get("dwell_ms") or 0) >= qualified_ms
        held_qualified = held is not None and (held.get("dwell_ms") or 0) >= qualified_ms
        newer = held is None or (as_utc(row.get("created_at")) or _EARLIEST) > (as_utc(held.get("created_at")) or _EARLIEST)
        if held is None or (qualified and not held_qualified) or (qualified == held_qualified and newer):
            best[key] = row
    return list(best.values())


async def _post_categories(settings: Settings, post_ids: set[str]) -> dict[str, list[str]]:
    ids = sorted(post_ids)
    found: dict[str, list[str]] = {}
    for start in range(0, len(ids), _POSTS_PER_READ):
        found |= await fetch.read_post_categories(settings, ids[start:start + _POSTS_PER_READ])
    return found


async def read_inputs(settings: Settings, anchor: datetime) -> CopyInputs:
    tunables = live.current()
    qualified_ms = tunables.events.qualified_view_seconds * 1000
    stats = ReadStats()
    skipped: Counter = Counter()

    users = await fetch.read_records(settings, "user")
    user_ids = [u.user_id for u in users]
    declared = {u.user_id: u.declared_interests for u in users if u.declared_interests}
    known = set(user_ids)

    # --- postevents copies ----------------------------------------------------------
    kept: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    for row in await writers.read_m1_event_copies(settings):
        # Only user accounts are scored. Older rows carry no user_model (actor
        # "unknown"): the id decides, since user and business ids never coincide.
        if row.get("actor") == "business" or to_str(row.get("user_id")) not in known:
            skipped["not_a_user"] += 1
            continue
        if row.get("undone_at") or row.get("undo_of"):
            skipped["undone"] += 1
            continue
        if row.get("event_type") == "feedback" and str(row.get("feedback_type") or "").strip().lower() not in WEIGHTED_FEEDBACK:
            skipped["feedback_not_weighted"] += 1
            continue
        (views if row.get("event_type") == "view" else kept).append(row)
    deduped = _latest_qualified_views(views, qualified_ms)
    skipped["repeat_views"] += len(views) - len(deduped)
    kept += deduped

    orders = []
    for order in await writers.read_order_copies(settings):
        if order.get("buyer_actor") == "business" or to_str(order.get("buyer_id")) not in known:
            skipped["order_not_by_a_user"] += 1
        elif _is_reversed(order):
            skipped["order_reversed"] += 1  # +20 and -20 at the same age: exactly zero
        else:
            orders.append(order)

    follows = [f for f in await fetch.read_records(settings, "follow")
               if f.followed_kind == "business" and f.follower_id in known]

    # --- categories, matched to the 23 ------------------------------------------------
    def target(row: dict[str, Any], kind: str) -> str | None:
        if row.get("event_type") == "feedback" and row.get("target_type") == kind and row.get("target_id"):
            return to_str(row["target_id"])
        return to_str(row[f"{kind}_id"]) if row.get(f"{kind}_id") else None

    post_ids = {p for r in kept if (p := target(r, "post"))} | {to_str(o["post_id"]) for o in orders if o.get("post_id")}
    product_ids = {p for r in kept if (p := target(r, "product"))} | {to_str(o["product_id"]) for o in orders if o.get("product_id")}
    by_post = await _post_categories(settings, post_ids)
    by_product = await fetch.read_product_categories(settings, sorted(product_ids))
    by_business = await fetch.read_business_categories(settings, sorted({f.followed_id for f in follows}))

    events: dict[str, list[Event]] = defaultdict(list)

    def add(user_id: str, kind: EventType, categories: list[str], at: Any, **extra: Any) -> None:
        stats.read += 1
        when = as_utc(at)
        if when is None:
            stats.missing_timestamp += 1
        elif when > anchor:
            stats.future_timestamp += 1
        elif not categories:
            stats.unresolved_category += 1
        else:
            events[user_id].append(Event(user_id=user_id, event_type=kind, categories=categories, timestamp=when, **extra))

    for row in kept:
        if row.get("event_type") == "feedback" and row.get("target_type") == "author":
            skipped["feedback_on_an_author"] += 1  # an author has no one category
            continue
        post, product = target(row, "post"), target(row, "product")
        # A post card's categories are the post's; a product's, through the category tree.
        categories = by_post.get(post) if post else None
        if not categories and product and by_product.get(product):
            categories = [by_product[product]]
        extra = {}
        if row["event_type"] == "view":
            extra["view_duration_seconds"] = row["dwell_ms"] / 1000 if row.get("dwell_ms") is not None else None
        add(to_str(row["user_id"]), ACTION[row["event_type"]], categories or [], row.get("created_at"), **extra)

    for order in orders:
        product, post = order.get("product_id"), order.get("post_id")
        categories = [by_product[to_str(product)]] if product and by_product.get(to_str(product)) else by_post.get(to_str(post), []) if post else []
        add(to_str(order["buyer_id"]), EventType.PURCHASE, categories, order.get("created_at"), order_id=to_str(order.get("order_id") or order["_id"]))

    for follow in follows:
        category = by_business.get(follow.followed_id)
        if category is None:
            skipped["business_follow_no_category"] += 1  # "or the follow adds nothing"
            continue
        add(follow.follower_id, EventType.BUSINESS_FOLLOW, [category], follow.created_at)

    return CopyInputs(dict(events), declared, user_ids, stats, skipped)
