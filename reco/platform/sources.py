"""Where each kind of data is read from: one place each. ENG-03 (Build List v1.3).

There is no event source switch: the platform's production migration (DB-16)
moves the older collections into postevents before the engine backfill, and the
engine reads events from one source only -- its own copy of postevents, made by
the engine sync (ENG-04). Models read the engine copies, never the live platform
rows, so nothing is counted twice:

    events (views, likes, saves, comments, shares,      -> copy of postevents  (ml_events)
      follows and unfollows, add/remove cart, purchase
      rows, feedback, impressions, clicks)
    orders, order history, cancellations, returns        -> copy of orders      (ml_orders)
    served lists: the engine's own lists                 -> the engine's E1     (ml_events)
                  fallback lists                         -> copy of recommendationrequests (ml_events)
    who follows whom (the follow graph)                  -> follows             (platform)
    blocks                                               -> followers           (platform, read when
                                                                                 each list is built, ENG-08)
    current eligibility state of posts, accounts,        -> ml_item_state       (ENG-27)
      products

ENG-29 adds rec_serve_log copies (the serve log) to ml_events.
"""

from __future__ import annotations

from typing import Literal

Source = Literal["ml_events", "ml_orders", "ml_item_state", "follow", "follower"]

#: Every kind of data the engine reads, and its one source.
SOURCES: dict[str, Source] = {
    "event": "ml_events",
    "served_list": "ml_events",
    "order": "ml_orders",
    "order_history": "ml_orders",
    "cancellation": "ml_orders",
    "return": "ml_orders",
    "follow_graph": "follow",
    "block": "follower",
    "eligibility_state": "ml_item_state",
}


def source_of(kind: str) -> Source:
    """The one place `kind` is read from."""
    try:
        return SOURCES[kind]
    except KeyError:
        raise ValueError(f"no ENG-03 source for {kind!r}") from None
