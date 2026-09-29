"""Where each kind of data is read from, and the event source switch. ENG-03.

One place per kind of data, so nothing is counted twice (ENG-03). Sources are
named by record kind; reco.config.PLATFORM_COLLECTIONS holds the collection names.

    orders, order states, cancellations, returns    -> order records (orders)
    views, likes, saves, comments, shares,
      post add-to-carts                            -> postevent records (postevents)
    follows                                          -> follow records (follows)
    add-to-carts with the list that showed them      -> add_to_cart events in ml_events
    requests, impressions, clicks, content feedback  -> the switch rule below

order_placed, order_state_changed and social_interaction are stored in ml_events
as the record for the next wave, and are not read in Wave 1A.

The switch rule, by day, so no history is lost: ENG-04 fixes a switch date once
its reconciliation holds for 7 days. For any day before that date, requests,
impressions, clicks and content feedback come from the old collections; from that
day onward, from ml_events. Never both for the same day. With no switch date
yet, every day reads the old collections.

Days are UTC calendar days (choice: DS-017 stamps every server time in UTC; the
pack does not say which day boundary the switch uses).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

Source = Literal["order", "postevent", "follow", "ml_events", "legacy"]

#: Kinds whose source depends on the day (ENG-03 switch rule).
SWITCHED: frozenset[str] = frozenset({"request", "impression", "click", "content_feedback"})

#: Every kind of data the engine reads, and its one source.
SOURCES: dict[str, Source | Literal["switch"]] = {
    "order": "order",
    "order_state": "order",
    "cancellation": "order",
    "return": "order",
    "view": "postevent",
    "like": "postevent",
    "save": "postevent",
    "comment": "postevent",
    "share": "postevent",
    "post_add_to_cart": "postevent",
    "follow": "follow",
    "add_to_cart_with_list": "ml_events",
    "request": "switch",
    "impression": "switch",
    "click": "switch",
    "content_feedback": "switch",
}

#: Stored in ml_events for the next wave, not read in Wave 1A (ENG-03).
STORED_NOT_READ: frozenset[str] = frozenset({"order_placed", "order_state_changed", "social_interaction"})


def source_of(kind: str, day: date | None = None, switch_date: date | None = None) -> Source:
    """The one place `kind` is read from, for `day` when the kind is switched."""
    if kind in STORED_NOT_READ:
        raise ValueError(f"{kind} is stored in ml_events but not read in Wave 1A (ENG-03)")
    try:
        source = SOURCES[kind]
    except KeyError:
        raise ValueError(f"no ENG-03 source for {kind!r}") from None
    if source != "switch":
        return source
    if day is None:
        raise ValueError(f"{kind} needs the day it is read for: its source switches by day")
    return "ml_events" if switch_date is not None and day >= switch_date else "legacy"


@dataclass(frozen=True)
class Span:
    """A half-open time range [start, end) read from one source."""

    source: Literal["legacy", "ml_events"]
    start: datetime
    end: datetime


def spans(start: datetime, end: datetime, switch_date: date | None) -> list[Span]:
    """Split [start, end) at the switch date so each part has exactly one source.

    A 90-day window that spans the switch reads part from each; no instant is in
    two spans, and none is left out.
    """
    start, end = _utc(start), _utc(end)
    if end <= start:
        return []
    if switch_date is None:
        return [Span("legacy", start, end)]
    cut = datetime.combine(switch_date, time.min, tzinfo=timezone.utc)
    if end <= cut:
        return [Span("legacy", start, end)]
    if start >= cut:
        return [Span("ml_events", start, end)]
    return [Span("legacy", start, cut), Span("ml_events", cut, end)]


def days(start: datetime, end: datetime) -> list[date]:
    """The UTC calendar days that [start, end) touches."""
    start, end = _utc(start), _utc(end)
    out, day = [], start.date()
    while datetime.combine(day, time.min, tzinfo=timezone.utc) < end:
        out.append(day)
        day += timedelta(days=1)
    return out


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
