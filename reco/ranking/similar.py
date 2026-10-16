"""M2 retrieval method two: similar posts, the maths. ENG-14. Pure: no database.

    post_type_of(detailed, post_type, listed)       the post's type, or "other"
    post_vector(categories, post_type, days_old, ...) one post's unit vector
    post_is_eligible(post, author)                  None, or why the post is left out
    engaged_by_user(rows, ...)                      each user's engaged posts, weighted
    user_profile(engaged, vectors, ...)             the user's unit profile, or None
    top_similar(profile, pool, limit)               the most similar posts, ranked

The vector (Build List v1.4, ENG-14 step 1), in this order of dimensions:

    23 categories   a post with k of the 23 carries 1/k in each, 0 elsewhere
    post types      one per entry of retrieval.post_types: 1 in the post's own type
    age             0.2 * exp(-days_old / 30), so age can never dominate
    then the whole vector is scaled to length 1.

The post's type (Kala, 16 Oct 2026): posts.postTypeDetailed where filled, else
posts.postType; both empty gives "normal"; anything not in the list gives "other"
and is reported by the job.

The profile (step 2): the weighted average of the vectors of the user's last 50
engaged posts, scaled to length 1. A post's weight is the sum, over the user's
qualifying actions on it, of the ENG-10 action weight times the 30-day decay
2 ** (-age_days / half_life_days). Fewer than 3 engaged posts: no profile.

Similarity (step 3): cosine, which for two unit vectors is their dot product.
Every coordinate is 0 or more, so it lies in 0..1. Ties: the newer post first,
then the post id.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from reco.eligibility.rules import BLOCKED_COMPLIANCE, account_rule
from reco.platform.ids import as_utc
from reco.platform.records import PostRecord, status_is

#: The age dimension's scale and time constant (ENG-14: "exp(minus days old divided
#: by 30), multiplied by 0.2"). Part of the method, not settings.
AGE_WEIGHT = 0.2
AGE_DAYS = 30.0

#: The type a post gets when both type fields are empty, and the catch-all.
EMPTY_TYPE = "normal"
OTHER_TYPE = "other"

#: postevents type -> the ENG-10 weight (InterestWeights field) it carries.
#: Views count only when qualified (dwell_ms at or above the threshold).
ACTION_WEIGHT_FIELD = {
    "view": "qualified_view",
    "click": "click",
    "product_click": "click",  # older builds (ENG-10)
    "like": "like",
    "save": "save",
    "comment": "comment",
    "share": "share",
    "add_to_cart": "add_to_cart",
}

Vector = list[float]


# --- the post vector ---------------------------------------------------------------


def _clean(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def post_type_of(detailed: Any, post_type: Any, listed: Sequence[str]) -> tuple[str, bool]:
    """(type, listed?) -- postTypeDetailed where filled, else postType; empty gives
    "normal"; a value not in `listed` gives "other" and listed? False, so the
    job can report it."""
    value = _clean(detailed) or _clean(post_type) or EMPTY_TYPE
    names = [_clean(t) for t in listed]
    if value in names:
        return value, True
    return OTHER_TYPE, False


def raw_type_of(detailed: Any, post_type: Any) -> str:
    """The value the type was read from (for the report of unlisted types)."""
    return _clean(detailed) or _clean(post_type) or EMPTY_TYPE


def normalise(vector: Sequence[float]) -> Vector:
    length = math.sqrt(sum(x * x for x in vector))
    return [x / length for x in vector] if length > 0 else [0.0] * len(vector)


def age_value(days_old: float) -> float:
    return AGE_WEIGHT * math.exp(-max(0.0, days_old) / AGE_DAYS)


def post_vector(
    categories: Iterable[str],
    post_type: str,
    days_old: float,
    category_names: Sequence[str],
    post_types: Sequence[str],
) -> Vector:
    """One post's vector, length 1. `categories` are already matched to the 23;
    `post_type` is already resolved (post_type_of). Dimensions: the 23 categories in
    `category_names` order, then `post_types` in order, then age."""
    own = {c for c in categories if c in category_names}
    share = 1.0 / len(own) if own else 0.0
    vector = [share if name in own else 0.0 for name in category_names]
    vector += [1.0 if _clean(t) == post_type else 0.0 for t in post_types]
    vector.append(age_value(days_old))
    return normalise(vector)


def days_between(earlier: datetime, later: datetime) -> float:
    return max(0.0, (later - earlier).total_seconds() / 86400)


# --- which posts get a vector in the pool --------------------------------------------


def post_is_eligible(post: PostRecord, author: Any) -> str | None:
    """Post-level rules only; the viewer's own rules (blocks, mutes, private authors,
    age, own posts) are applied when the list is served (ENG-08). Returns None
    when the post may be in the pool, else the reason it is left out."""
    if post.is_seed:
        return "seed_post"  # ENG-30 point 9
    if post.is_repost:
        return "repost"  # ENG-13 counts a repost as its original
    if post.is_hidden or not status_is(post.visibility, "public"):
        return "E-04"
    if post.product_ids or (post.product_status and not status_is(post.product_status, "N/A")):
        if not status_is(post.product_status, "Activated"):
            return "E-06"
    rule = account_rule(author)  # E-08 author not active, E-09 restricted
    if rule:
        return rule
    if any(status_is(post.compliance_status, s) for s in BLOCKED_COMPLIANCE):
        return "E-12"
    return None


# --- engaged posts and the profile -------------------------------------------------------


@dataclass
class Engagement:
    """One user's engagement with one post."""

    weight: float = 0.0  # sum of action weight x decay
    last_at: datetime | None = None  # the most recent qualifying action
    actions: int = 0


@dataclass
class EngagedRead:
    by_user: dict[str, dict[str, Engagement]]
    skipped: Counter = field(default_factory=Counter)


def engaged_by_user(
    rows: Iterable[Mapping[str, Any]],
    *,
    anchor: datetime,
    weights: Mapping[str, float],
    half_life_days: float,
    qualified_view_ms: float,
    seed_posts: set[str] | frozenset[str] = frozenset(),
    test_accounts: set[str] | frozenset[str] = frozenset(),
) -> EngagedRead:
    """Each user's engaged posts from the engine's copy of postevents.

    Counted: a qualified view (one per viewer per post: the most recent), click or
    product_click, like, save, comment, share, add_to_cart. Never: feedback,
    impressions, an action later undone (undone_at) or an undo row (undo_of), an
    action on the user's own post (is_self), an action on a seed post, an action
    by a test account or a business account, or one after `anchor`.

    `weights` maps the ENG-10 names (qualified_view, click, ...) to their weights."""
    skipped: Counter = Counter()
    #: (user_id, post_id, event_type, at) per counted action.
    views: dict[tuple[str, str], tuple[str, str, str, datetime]] = {}
    actions: list[tuple[str, str, str, datetime]] = []
    for row in rows:
        event_type = _clean(row.get("event_type"))
        user_id, post_id, at = row.get("user_id"), row.get("post_id"), as_utc(row.get("created_at"))
        if event_type not in ACTION_WEIGHT_FIELD:
            skipped["not_an_engagement"] += 1
        elif not user_id or not post_id or at is None:
            skipped["incomplete"] += 1
        elif row.get("undone_at") or row.get("undo_of"):
            skipped["undone"] += 1
        elif row.get("is_self"):
            skipped["own_post"] += 1
        elif str(post_id) in seed_posts:
            skipped["seed_post"] += 1
        elif str(user_id).strip().lower() in test_accounts:
            skipped["test_account"] += 1
        elif row.get("actor") == "business":
            skipped["not_a_user"] += 1
        elif at > anchor:
            skipped["future"] += 1
        elif event_type == "view":
            if (row.get("dwell_ms") or 0) < qualified_view_ms:
                skipped["view_not_qualified"] += 1
                continue
            key = (str(user_id), str(post_id))
            held = views.get(key)
            if held is not None:
                skipped["repeat_view"] += 1
            if held is None or at > held[3]:
                views[key] = (str(user_id), str(post_id), event_type, at)
        else:
            actions.append((str(user_id), str(post_id), event_type, at))

    by_user: dict[str, dict[str, Engagement]] = {}
    for user_id, post_id, event_type, at in [*actions, *views.values()]:
        weight = weights[ACTION_WEIGHT_FIELD[event_type]]
        decay = 2 ** (-days_between(at, anchor) / half_life_days)
        held = by_user.setdefault(user_id, {}).setdefault(post_id, Engagement())
        held.weight += weight * decay
        held.actions += 1
        if held.last_at is None or at > held.last_at:
            held.last_at = at
    return EngagedRead(by_user=by_user, skipped=skipped)


def last_engaged(engaged: Mapping[str, Engagement], vectors: Mapping[str, Vector], limit: int) -> list[str]:
    """The `limit` posts with the most recent qualifying action that have a vector
    (ties: post id). A post the platform no longer has has no vector."""
    known = [pid for pid in engaged if pid in vectors]
    known.sort(key=lambda pid: (-engaged[pid].last_at.timestamp(), pid))
    return known[:limit]


def user_profile(
    engaged: Mapping[str, Engagement],
    vectors: Mapping[str, Vector],
    *,
    last_posts: int,
    min_engaged: int,
) -> Vector | None:
    """The weighted average of the last `last_posts` engaged posts' vectors, length 1.
    None with fewer than `min_engaged` engaged posts, or no positive weight."""
    chosen = last_engaged(engaged, vectors, last_posts)
    if len(chosen) < min_engaged:
        return None
    total = sum(engaged[pid].weight for pid in chosen)
    if total <= 0:
        return None
    size = len(vectors[chosen[0]])
    summed = [0.0] * size
    for pid in chosen:
        w = engaged[pid].weight / total
        for i, x in enumerate(vectors[pid]):
            summed[i] += w * x
    profile = normalise(summed)
    return profile if any(profile) else None


# --- similarity and the stored list --------------------------------------------------------


@dataclass(frozen=True)
class PoolPost:
    """A post in the pool: its id, time and sparse unit vector."""

    post_id: str
    created_ts: float  # seconds since the epoch, for the newer-first tie-break
    nonzero: tuple[tuple[int, float], ...]

    @classmethod
    def of(cls, post_id: str, created_at: datetime, vector: Sequence[float]) -> PoolPost:
        return cls(post_id, created_at.timestamp(), tuple((i, x) for i, x in enumerate(vector) if x))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """For unit vectors, the dot product. Clipped to 0..1 against rounding."""
    return min(1.0, max(0.0, sum(x * y for x, y in zip(a, b))))


def top_similar(profile: Sequence[float], pool: Sequence[PoolPost], limit: int) -> list[tuple[str, float]]:
    """The `limit` pool posts most similar to `profile`, best first, as (post_id,
    score). Ties: newer post first, then post id."""
    scored = (
        (min(1.0, max(0.0, sum(profile[i] * x for i, x in post.nonzero))), post.created_ts, post.post_id)
        for post in pool
    )
    best = heapq.nsmallest(limit, scored, key=lambda s: (-s[0], -s[1], s[2]))
    return [(post_id, score) for score, _, post_id in best]
