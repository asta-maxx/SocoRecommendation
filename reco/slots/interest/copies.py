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
                        on the business's category (businessregisters.category),
                        which must map to one of the 23 (the tree rule, ENG-29)

Open return request (ENG-30 point 10): an order with an open return request
(ml_return_requests, isActive true) contributes nothing while it is open; when the
request ends without a return, the order counts again at the next refresh. If the
copy of returnrequests is not current, M1 runs on the last good copy and says so.

Seed posts (ENG-30 point 9): actions on a post carrying _seedTag are test data and
are left out, like a test account's.

Own-post actions (Kala, 16 Oct): an action on the user's own post (is_self) is left
out of the interest score under both methods, as well as the count, consistent
with ENG-03. Fraud (ENG-21) still reads them from the copies.

Qualified actions (Kala, 16 Oct, ENG-09 2a): per user, the actions in the last 90
days that count towards the ladder's 5: a qualified view (one per post), click,
like, save, comment, share, add-to-cart, a kept order, a business follow; never
Not interested / Hide, impressions, undone actions, actions on your own post
(is_self), or actions on seed posts. The total (whatever the category) is stored
on every score row as qualified_actions; event_count is the same set, per category.
The ladder counts with the same rules, so the two are equal.

Undo: an undone action (undone_at set) and the undo row itself (undo_of) both
contribute nothing. That is the pack's "the undo removes the weight of the action
it undoes, aged from the original action's time", applied once: weight minus the
same weight at the same age is exactly zero.

Reversal: an order whose order_status is Cancelled, Rejected or Returned contributes
nothing: its +20 and its -20 are both aged from the order's creation, so it nets to
exactly zero, once. (There is no Return Requested status, ENG-30 point 6; leaving a
purchase out while a return request is open is ENG-30 point 10.)

Incognito orders count for the buyer (purchase privacy only). Impressions,
remove_from_cart and the other new platform events carry no weight. Only user
accounts are scored. Every category is matched to the 23 (ENG-03); anything else
is dropped and counted.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    #: Qualified actions in the last 90 days: per user, and per user per category.
    qualified: Counter = field(default_factory=Counter)
    qualified_by_category: dict[str, Counter] = field(default_factory=dict)
    #: The same, as the set of distinct action ids (Kala, 16 Oct: the check proves every
    #: category-level action belongs to the user's set, and the set's size is the count).
    qualified_ids: dict[str, set] = field(default_factory=dict)
    qualified_ids_by_category: dict[str, dict[str, set]] = field(default_factory=dict)
    #: Whether the return-request copy was current (ENG-30 point 7), and why not.
    return_requests: str = "current"


def _is_reversed(order: dict[str, Any]) -> bool:
    """ENG-10 (and ENG-30 point 6): Cancelled, Rejected or Returned, read from
    order_status, the order's state. A history event never decides it."""
    statuses = live.current().lists.order_status
    status = order.get("status")
    return any(status_is(status, value) for value in (statuses.cancelled, statuses.rejected, statuses.returned))


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


async def _posts(settings: Settings, post_ids: set[str]) -> dict[str, Any]:
    ids = sorted(post_ids)
    found: dict[str, Any] = {}
    for start in range(0, len(ids), _POSTS_PER_READ):
        found |= await fetch.read_posts(settings, ids[start:start + _POSTS_PER_READ])
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

    # ENG-30 points 7 and 10: orders with an open return request are left out.
    current, why = await writers.return_requests_current(
        settings, anchor, tunables.commerce.return_request_current_hours)
    if not current:
        logger.warning("return-request copy not current; M1 runs on the last good copy", extra={"why": why})
    open_requests = await writers.read_open_return_orders(settings)

    orders = []
    for order in await writers.read_order_copies(settings):
        order_id = to_str(order.get("order_id") or order["_id"])
        if order.get("buyer_actor") == "business" or to_str(order.get("buyer_id")) not in known:
            skipped["order_not_by_a_user"] += 1
        elif _is_reversed(order):
            skipped["order_reversed"] += 1  # +20 and -20 at the same age: exactly zero
        elif order_id in open_requests:
            skipped["order_open_return_request"] += 1  # out while the request is open (ENG-30 point 10)
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
    posts = await _posts(settings, post_ids)
    by_post = {pid: post.categories for pid, post in posts.items()}
    seed = {pid for pid, post in posts.items() if post.is_seed}
    by_product = await fetch.read_product_categories(settings, sorted(product_ids))
    by_business = await fetch.read_business_categories(settings, sorted({f.followed_id for f in follows}))

    events: dict[str, list[Event]] = defaultdict(list)
    window_start = anchor - timedelta(days=tunables.interest.personal_window_days)
    qualified: Counter = Counter()
    qualified_by_category: dict[str, Counter] = defaultdict(Counter)
    qualified_ids: dict[str, set] = defaultdict(set)
    qualified_ids_by_category: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

    def add(user_id: str, kind: EventType, categories: list[str], at: Any, counts: bool = False,
            action_id: str | None = None, **extra: Any) -> None:
        stats.read += 1
        when = as_utc(at)
        if when is None:
            stats.missing_timestamp += 1
            return
        if when > anchor:
            stats.future_timestamp += 1
            return
        if counts and when >= window_start:
            # A qualified action (Kala 2a): counted once, whatever its category; in each
            # of its categories for event_count.
            qualified[user_id] += 1
            qualified_ids[user_id].add(action_id)
            for category in categories:
                qualified_by_category[user_id][category] += 1
                qualified_ids_by_category[user_id][category].add(action_id)
        if not categories:
            stats.unresolved_category += 1
        else:
            events[user_id].append(Event(user_id=user_id, event_type=kind, categories=categories, timestamp=when, **extra))

    for row in kept:
        if row.get("event_type") == "feedback" and row.get("target_type") == "author":
            skipped["feedback_on_an_author"] += 1  # an author has no one category
            continue
        post, product = target(row, "post"), target(row, "product")
        if post in seed:
            skipped["seed_post"] += 1  # test data (ENG-30 point 9)
            continue
        if row.get("is_self"):
            skipped["own_post"] += 1  # never scored or counted (Kala, 16 Oct); fraud still reads it
            continue
        # A post card's categories are the post's; a product's, through the category tree.
        categories = by_post.get(post) if post else None
        if not categories and product and by_product.get(product):
            categories = [by_product[product]]
        extra = {}
        kind = row["event_type"]
        if kind == "view":
            extra["view_duration_seconds"] = row["dwell_ms"] / 1000 if row.get("dwell_ms") is not None else None
        counts = (kind != "feedback" and not row.get("is_self")
                  and (kind != "view" or (row.get("dwell_ms") or 0) >= qualified_ms))
        add(to_str(row["user_id"]), ACTION[kind], categories or [], row.get("created_at"), counts,
            action_id=f"event:{to_str(row['_id'])}", **extra)

    for order in orders:
        product, post = order.get("product_id"), order.get("post_id")
        if post and to_str(post) in seed:
            skipped["seed_post"] += 1
            continue
        categories = [by_product[to_str(product)]] if product and by_product.get(to_str(product)) else by_post.get(to_str(post), []) if post else []
        order_id = to_str(order.get("order_id") or order["_id"])
        add(to_str(order["buyer_id"]), EventType.PURCHASE, categories, order.get("created_at"), True,
            action_id=f"order:{order_id}", order_id=order_id)

    for follow in follows:
        category = by_business.get(follow.followed_id)
        if category is None:
            # "Or the follow adds nothing" to the score; it is still a qualified action.
            skipped["business_follow_no_category"] += 1
            add(follow.follower_id, EventType.BUSINESS_FOLLOW, [], follow.created_at, True,
                action_id=f"follow:{follow.follower_id}:{follow.followed_id}")
            stats.unresolved_category -= 1  # not a dropped event: a follow that adds nothing
            continue
        add(follow.follower_id, EventType.BUSINESS_FOLLOW, [category], follow.created_at, True,
            action_id=f"follow:{follow.follower_id}:{follow.followed_id}")

    return CopyInputs(dict(events), declared, user_ids, stats, skipped, qualified, dict(qualified_by_category),
                      {u: set(ids) for u, ids in qualified_ids.items()},
                      {u: {c: set(ids) for c, ids in cats.items()} for u, cats in qualified_ids_by_category.items()},
                      "current" if current else why)
