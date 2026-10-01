"""The platform's native event types and surfaces, mapped as the pack says. ENG-03, ENG-04.

    NATIVE_EVENTS  Capture Register (29 Sep), sheet "4 Native event map": the 26
                   postevents types, the E code each maps to, and whether a Wave
                   1A model scores it ("capture only" types are copied and kept
                   with no model weight).
    SURFACES       F02 note (28 Sep): home_for_you -> feed; product_detail and
                   cart -> product. Other tabs and post_detail are not engine
                   surfaces; a post_detail impression is a page visit (X-05).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeEvent:
    code: str | None  # E code, or None where sheet 4 gives "—"
    scored: bool  # used by a Wave 1A model (False = capture only, or measurement only)
    undoes: str | None = None  # the native type this one undoes (its row carries undo_of)


#: Sheet 4, row by row. "Scored" follows its "Scored in Wave 1A" column:
#: impressions are measurement only (M1 does not use them).
NATIVE_EVENTS: dict[str, NativeEvent] = {
    "impression": NativeEvent("E2", scored=False),
    "click": NativeEvent("E3", scored=True),
    "product_click": NativeEvent("E3", scored=True),  # older builds
    "view": NativeEvent(None, scored=True),  # M1 qualified view when dwell_ms >= 3,000
    "like": NativeEvent("E9", scored=True),
    "unlike": NativeEvent("E9", scored=True, undoes="like"),
    "comment": NativeEvent("E9", scored=True),
    "uncomment": NativeEvent("E9", scored=True, undoes="comment"),
    "share": NativeEvent("E9", scored=True),
    "save": NativeEvent("E9", scored=True),
    "unsave": NativeEvent("E9", scored=True, undoes="save"),
    "repost": NativeEvent("E9", scored=False),
    "follow": NativeEvent("E9", scored=True),  # M1 business follows; influencer_id = the account followed
    "unfollow": NativeEvent("E9", scored=True, undoes="follow"),
    "add_to_cart": NativeEvent("E4", scored=True),  # M1, M5; list from carts.ml
    "remove_from_cart": NativeEvent("E4", scored=False),
    "purchase": NativeEvent("E5", scored=True),  # via the order: the order is the authority (X-18)
    "feedback": NativeEvent("E13", scored=True),  # not_interested, hide, report, mute_author
    "product_view": NativeEvent(None, scored=False),
    "video_play": NativeEvent(None, scored=False),
    "video_complete": NativeEvent(None, scored=False),
    "variant_select": NativeEvent(None, scored=False),
    "checkout_start": NativeEvent(None, scored=False),  # carries checkout_id
    "wishlist_add": NativeEvent(None, scored=False),
    "wishlist_remove": NativeEvent(None, scored=False, undoes="wishlist_add"),
    "search": NativeEvent(None, scored=False),  # full log in searchqueries
}

#: F02: the platform's native surfaces mapped to the two engine surfaces.
SURFACES: dict[str, str] = {
    "home_for_you": "feed",
    "product_detail": "product",
    "cart": "product",
}

#: X-05, ENG-03: impressions on the post page are page visits, never card
#: impressions or qualified card views, and never counted as seen.
PAGE_VISIT_SURFACE = "post_detail"


def native(event_type: str | None) -> NativeEvent | None:
    """The sheet 4 entry for a native event type, or None for a type the sheet doesn't list."""
    return NATIVE_EVENTS.get((event_type or "").strip().lower())


def engine_surface(surface: str | None) -> str | None:
    """feed, product, or None for a native surface that is not an engine surface."""
    return SURFACES.get((surface or "").strip().lower())
