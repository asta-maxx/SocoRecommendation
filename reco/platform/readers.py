"""The only module that reads source collections. S11.

Read-only credential for application collections, secondary preferred. Nothing
outside this file touches an application collection, and nothing in this file
writes.

No collection name is written down here -- every name arrives from Settings, so
the demonstration runs the same code as production with a different
`DATA_PROFILE` and there is no demo branch to keep in step.

But a name is not enough. The two event sources are structurally different:

  demo  ml_demo_events carries its categories array on the event row
  live  postevents carries a post_id and no categories; the category resolves
        through the post, which is a join

So this module holds one adapter per source, both producing the single
`domain.events.Event` shape. The methods see only that shape and never learn
which source they are reading. Adding a third source means adding a third
adapter here and nothing else.

Two facts about the live data are encoded here rather than rediscovered at each
call site:

  * Live events live in `postevents`. `userevents` holds zero documents -- its
    TTL index was never created -- so reading it returns an empty result that
    looks like a user with no activity.
  * `view_duration_seconds` is on `postevents`, not on `trackings`, which
    carries no duration at all.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from bson import ObjectId

from reco.config import Settings
from reco.platform.ids import id_match, to_str
from reco.platform.connection import app_db, source_db
from reco.platform.categories import CategoryVocabulary, resolve_all
from reco.slots.interest.events import Event, EventType, ReadStats

logger = logging.getLogger(__name__)

#: Source field names that mean "when". The three sources disagree: the generator
#: writes `timestamp`, postevents writes `created_at`, and the DS-017 ingest
#: proposal writes `occurred_at`. Reconciling them is the adapter's whole job.
#:
#: A missing timestamp must be dropped rather than silently treated as new -- and
#: it arrives as an explicit null, not as an absent key, so this checks the VALUE.
#: `if "timestamp" not in row` misses every one of U10's rows.
_TIMESTAMP_FIELDS = ("timestamp", "created_at", "createdAt", "occurred_at")

#: Order field names. The generator writes `placed_at`; the application writes
#: `created_at`. Both mean the instant the order was created, which is the
#: instant a reversal is aged from.
_ORDER_PLACED_FIELDS = ("placed_at", "created_at", "createdAt")

#: The user record's declared-interest array. The generator writes
#: `declared_interests`; the application writes `interest`.
_DECLARED_INTEREST_FIELDS = ("declared_interests", "interest")

#: How each source spells an event type. Anything not listed is dropped and
#: counted -- it is not assumed to be a view.
_EVENT_TYPE_ALIASES = {
    "view": EventType.VIEW,
    "product_view": EventType.VIEW,
    "search": EventType.SEARCH,
    "keyword_search": EventType.SEARCH,
    "click": EventType.CLICK,
    "product_click": EventType.CLICK,
    "cart": EventType.CART,
    "add_to_cart": EventType.CART,
    "purchase": EventType.PURCHASE,
    "order": EventType.PURCHASE,
    # A reversal is its own row type rather than a boolean flag, which keeps the
    # generated row contract at seven fields and makes a row self-describing.
    "purchase_reversal": EventType.PURCHASE,
}

#: Row types that mean "reverse a purchase". Kept separate from the alias map so
#: the reversal is not mistaken for P-07 negative feedback -- it is not, and
#: multiplying it by P-07 (0 at launch) would zero it silently.
_REVERSAL_TYPES = {"purchase_reversal", "reversal", "cancellation"}

#: Order states that reverse a purchase. A reversal is applied with the purchase
#: weight negated and aged from the ORIGINAL order -- it is not P-07 negative
#: feedback, and multiplying it by P-07 would zero it silently.
REVERSING_ORDER_STATES = {"Cancelled", "Rejected"}


def _read_timestamp(
    row: dict[str, Any],
    fields: tuple[str, ...] = _TIMESTAMP_FIELDS,
) -> datetime | None:
    for field in fields:
        value = row.get(field)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str) and value:
            # JSON-loaded fixtures carry ISO strings where Mongo carries dates.
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                continue
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _read_event_type(row: dict[str, Any]) -> tuple[EventType | None, bool]:
    """The event type, and whether the row reverses a purchase."""
    raw = row.get("event_type") or row.get("eventType") or row.get("type")
    if not isinstance(raw, str):
        return None, False
    key = raw.strip().lower()
    return _EVENT_TYPE_ALIASES.get(key), key in _REVERSAL_TYPES


def _read_categories(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [c.strip() for c in value if isinstance(c, str) and c.strip()]


_VOCABULARY: CategoryVocabulary | None = None


def vocabulary(settings: Settings) -> CategoryVocabulary:
    """The category vocabulary, loaded once.

    Cached because resolution runs per category per event -- 6,361 events is
    tens of thousands of lookups, and re-reading a file for each would be absurd.
    """
    global _VOCABULARY
    if _VOCABULARY is None:
        _VOCABULARY = CategoryVocabulary.load(settings.category_vocabulary_path)
    return _VOCABULARY


def reset_vocabulary_cache() -> None:
    """Test seam. Not called on production paths."""
    global _VOCABULARY
    _VOCABULARY = None


def _build_event(
    row: dict[str, Any],
    categories: list[str],
    stats: ReadStats,
    now: datetime,
    vocab: CategoryVocabulary | None = None,
) -> Event | None:
    """Shared tail of both adapters: validate and drop with the right counter."""
    event_type, is_reversal = _read_event_type(row)
    if event_type is None:
        stats.unknown_event_type += 1
        return None

    timestamp = _read_timestamp(row)
    if timestamp is None:
        # Never treat a missing timestamp as "now": that would hand the event a
        # decay factor of 1 and make it the strongest signal the user has.
        stats.missing_timestamp += 1
        return None

    if timestamp > now:
        # A future timestamp produces a decay factor greater than 1 and inflates
        # the score without bound.
        stats.future_timestamp += 1
        return None

    # DS-008 section 3.2, step one. Resolve what the source supplied onto a
    # canonical category, or determine it has none. Seller-created product
    # categories are unconstrained, so this is where "Casual Sneakers" stops
    # being treated as a category and starts being counted as a drop.
    if vocab is not None:
        resolution = resolve_all(vocab, categories)
        if resolution.dropped:
            stats.record_unmapped(resolution.dropped)
        categories = resolution.resolved

    if not categories:
        stats.unresolved_category += 1
        return None

    duration = row.get("view_duration_seconds")
    return Event(
        user_id=to_str(row.get("user_id") or row.get("userId")),
        event_type=event_type,
        categories=categories,
        timestamp=timestamp,
        view_duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
        order_id=to_str(row["order_id"]) if row.get("order_id") else None,
        is_reversal=is_reversal or bool(row.get("is_reversal", False)),
    )


async def _resolve_post_categories(
    settings: Settings,
    rows: Iterable[dict[str, Any]],
) -> dict[str, list[str]]:
    """Categories for every post referenced by these events, in one query.

    Done as a lookup map rather than a $lookup stage because post identifiers are
    stored as BOTH ObjectId and String across documents. A $lookup matches one
    type and returns a partial result -- which is worse than an empty one,
    because it looks like the query worked.
    """
    post_ids = {
        to_str(row["post_id"])
        for row in rows
        if row.get("post_id") not in (None, "")
    }
    if not post_ids:
        return {}

    forms: list[Any] = list(post_ids)
    forms += [ObjectId(p) for p in post_ids if ObjectId.is_valid(p)]

    collection = settings.posts_collection
    cursor = source_db(settings, collection)[collection].find(
        {"_id": {"$in": forms}},
        {"categories": 1},
    )
    return {
        to_str(document["_id"]): _read_categories(document.get("categories"))
        async for document in cursor
    }


async def read_user_events(
    settings: Settings,
    user_id: str,
    since: datetime | None = None,
    reference_date: datetime | None = None,
) -> tuple[list[Event], ReadStats]:
    """Every qualifying event for one user, newest first, plus what was dropped.

    `reference_date` is what "future" is measured against, and it is a parameter
    rather than a call to the clock on purpose. The generated dataset pins one in
    `ml_demo_meta.reference_date`, and U10's future rows sit just ahead of it --
    if the engine compared against its own clock and ran a day late, those rows
    would stop being future, start contributing, inflate U10 and break the check.
    Passing None falls back to now, which is correct for a live run.

    Returns the counters alongside the events rather than logging them away: the
    unresolved-category rate is one of the seven data checks, and a check needs a
    number it can report against.

    NOTE: there is no {user_id: 1, created_at: -1} index on postevents -- all
    seven existing indexes lead with influencer, post or product. Until that
    index exists (B9) this scans. Fine on generated data, not fine against
    production shape.
    """
    query: dict[str, Any] = {"user_id": id_match(user_id)}
    if since is not None:
        query["created_at"] = {"$gte": since}

    collection = settings.events_collection
    cursor = source_db(settings, collection)[collection].find(query)
    rows = [row async for row in cursor]

    stats = ReadStats(read=len(rows))
    now = reference_date or datetime.now(timezone.utc)
    vocab = vocabulary(settings)

    if settings.event_shape == "flat":
        # Generated rows carry their categories directly.
        events = [
            event
            for row in rows
            if (event := _build_event(row, _read_categories(row.get("categories")), stats, now, vocab))
        ]
    else:
        # Live rows carry a post_id; the category is a join away.
        by_post = await _resolve_post_categories(settings, rows)
        events = [
            event
            for row in rows
            if (
                event := _build_event(
                    row,
                    by_post.get(to_str(row["post_id"]), []) if row.get("post_id") else [],
                    stats,
                    now,
                    vocab,
                )
            )
        ]

    if stats.dropped:
        logger.info(
            "user %s: read %d events, dropped %d "
            "(unresolved category %d, missing timestamp %d, future timestamp %d, "
            "unknown type %d)",
            user_id,
            stats.read,
            stats.dropped,
            stats.unresolved_category,
            stats.missing_timestamp,
            stats.future_timestamp,
            stats.unknown_event_type,
        )

    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events, stats


async def read_declared_interests(settings: Settings, user_id: str) -> list[str]:
    """A user's signup category picks -- the P-25 floor source.

    Read from the user record's `interest` array. NOT from interestScores:
    addInterest seeds that map with 10 per declared category and event tracking
    increments the same map, so the declared floor and accumulated events are
    fused there and cannot be decomposed.

    These carry no timestamp and must never be written to the event stream, where
    the decay term would consume them.
    """
    collection = settings.users_collection
    document = await source_db(settings, collection)[collection].find_one(
        {"$or": [{"_id": id_match(user_id)}, {"user_id": user_id}]}
    )
    if not document:
        return []
    for field in _DECLARED_INTEREST_FIELDS:
        if field in document:
            return _read_categories(document[field])
    return []


async def read_order_creation_times(
    settings: Settings,
    order_ids: Iterable[str],
) -> dict[str, datetime]:
    """When each order was CREATED, for aging a reversal correctly.

    A purchase is credited at order creation -- `createOrder` writes the order at
    `order_status: "Pending"` and creates the purchase event in the same call;
    nothing waits for Delivered. M1 measures interest, not commercial outcome,
    and under cash on delivery waiting for delivery would leave the profile blind
    to the user's strongest recent signal for up to a fortnight.

    The reversal is then aged from THIS timestamp, never from the cancellation.
    """
    ids = [i for i in order_ids if i]
    if not ids:
        return {}

    forms: list[Any] = list(ids)
    forms += [ObjectId(i) for i in ids if ObjectId.is_valid(i)]

    collection = settings.orders_collection
    cursor = source_db(settings, collection)[collection].find(
        {"$or": [{"_id": {"$in": forms}}, {"order_id": {"$in": list(ids)}}]}
    )
    times: dict[str, datetime] = {}
    async for document in cursor:
        placed = _read_timestamp(document, _ORDER_PLACED_FIELDS)
        if placed is None:
            continue
        key = to_str(document.get("order_id") or document["_id"])
        times[key] = placed
    return times


async def read_all_user_ids(settings: Settings) -> list[str]:
    """Every user the refresh should score.

    The union of who has a user record and who has an event. A user with events
    but no record still gets a score; a user with a record and no events still
    gets their declared floor, which is rung 2 and the common case at launch --
    everyone who signed up on day one has picked interests and done nothing.
    """
    users_collection = settings.users_collection
    events_collection = settings.events_collection

    ids: set[str] = set()
    cursor = source_db(settings, users_collection)[users_collection].find({})
    async for document in cursor:
        raw = document.get("user_id") or document.get("_id")
        if raw is not None:
            ids.add(to_str(raw))

    for raw in await source_db(settings, events_collection)[
        events_collection
    ].distinct("user_id"):
        if raw is not None:
            ids.add(to_str(raw))

    return sorted(ids)


async def read_all_declared_interests(settings: Settings) -> dict[str, list[str]]:
    """Every user's signup picks, in one pass.

    The refresh scores every user, so reading these one at a time would be one
    round trip per user against a collection small enough to read whole.
    """
    collection = settings.users_collection
    cursor = source_db(settings, collection)[collection].find({})

    declared: dict[str, list[str]] = {}
    async for document in cursor:
        raw = document.get("user_id") or document.get("_id")
        if raw is None:
            continue
        for field in _DECLARED_INTEREST_FIELDS:
            if field in document:
                declared[to_str(raw)] = _read_categories(document[field])
                break
    return declared


async def read_all_order_creation_times(settings: Settings) -> dict[str, datetime]:
    """When every order was created, in one pass.

    A reversal is aged from its order, and the refresh may meet a reversal for
    any user, so the whole map is cheaper than a lookup per reversal.
    """
    collection = settings.orders_collection
    cursor = source_db(settings, collection)[collection].find({})

    times: dict[str, datetime] = {}
    async for document in cursor:
        placed = _read_timestamp(document, _ORDER_PLACED_FIELDS)
        if placed is None:
            continue
        key = to_str(document.get("order_id") or document["_id"])
        times[key] = placed
    return times


async def read_events_by_user(
    settings: Settings,
    reference_date: datetime | None = None,
) -> tuple[dict[str, list[Event]], ReadStats]:
    """Every event, adapted and grouped by user, in one pass.

    One scan rather than one query per user. That matters more than it looks:
    `postevents` has no {user_id, created_at} index, so a per-user query scans
    the collection anyway -- 195 users would be 195 scans.

    The returned stats are for the whole pass, which is what the unresolved
    category and timestamp rates are reported over.
    """
    collection = settings.events_collection
    cursor = source_db(settings, collection)[collection].find({})
    rows = [row async for row in cursor]

    stats = ReadStats(read=len(rows))
    now = reference_date or datetime.now(timezone.utc)
    vocab = vocabulary(settings)

    by_post: dict[str, list[str]] = {}
    if settings.event_shape != "flat":
        by_post = await _resolve_post_categories(settings, rows)

    grouped: dict[str, list[Event]] = {}
    for row in rows:
        if settings.event_shape == "flat":
            categories = _read_categories(row.get("categories"))
        else:
            post_id = row.get("post_id")
            categories = by_post.get(to_str(post_id), []) if post_id else []

        event = _build_event(row, categories, stats, now, vocab)
        if event is not None:
            grouped.setdefault(event.user_id, []).append(event)

    for events in grouped.values():
        events.sort(key=lambda e: e.timestamp, reverse=True)

    logger.info(
        "read %d events for %d users; dropped %d (unresolved category %d, "
        "missing timestamp %d, future timestamp %d, unknown type %d)",
        stats.read,
        len(grouped),
        stats.dropped,
        stats.unresolved_category,
        stats.missing_timestamp,
        stats.future_timestamp,
        stats.unknown_event_type,
    )
    return grouped, stats


async def read_category_popularity(
    settings: Settings,
    window_days: int,
    reference_date: datetime | None = None,
) -> dict[str, int]:
    """How often each category was engaged with across the whole platform.

    Rung 3 of the fallback ladder: what a user with no events and no declared
    interests is served. Counted over the P-27 window, because popularity over
    all time and popularity over the last week are different rankings -- left
    unstated it becomes a number typed into a file.

    Counts EVENTS, not weighted score. Rung 3 answers "what is the platform
    interested in", and weighting it by purchase value would answer a different
    question -- what sells -- which is not what an interest profile is for.

    An event contributes to each of its categories, matching how scoring treats a
    multi-category post.
    """
    collection = settings.events_collection
    now = reference_date or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    cursor = source_db(settings, collection)[collection].find({})
    rows = []
    async for row in cursor:
        when = _read_timestamp(row)
        if when is None or when > now or when < cutoff:
            continue
        rows.append(row)

    # The live source resolves its category through the post, exactly as scoring
    # does. Skipping the join here would make rung 3 silently empty on live data
    # -- and rung 3 is the answer for everyone we know nothing about.
    by_post: dict[str, list[str]] = {}
    if settings.event_shape != "flat":
        by_post = await _resolve_post_categories(settings, rows)

    counts: Counter[str] = Counter()
    for row in rows:
        if settings.event_shape == "flat":
            categories = _read_categories(row.get("categories"))
        else:
            post_id = row.get("post_id")
            categories = by_post.get(to_str(post_id), []) if post_id else []
        counts.update(categories)

    return dict(counts.most_common())


async def read_one_event(settings: Settings) -> dict[str, Any] | None:
    """A single raw event document from the configured source. S12.

    Proves the credential works and the collection is reachable before anything
    is designed around it. Raw, not adapted, because its purpose is to show what
    the source actually looks like.

    Returns None on an empty collection, which is the expected result against a
    fresh database -- an absence of data is not an absence of connectivity, and
    the caller must not read it as one.
    """
    collection = settings.events_collection
    return await source_db(settings, collection)[collection].find_one()


async def count_events(settings: Settings) -> int:
    """How many events exist in the configured source."""
    collection = settings.events_collection
    return await source_db(settings, collection)[collection].count_documents({})


async def list_source_collections(settings: Settings) -> list[str]:
    """What the application connection can actually see.

    So a misconfigured source shows up as a name that is not there, rather than
    as a silently empty result set.
    """
    return sorted(await app_db(settings).list_collection_names())
