"""GET /profile/{user_id}. The read path, exposed. RE-05, RE-07.

Always 200 with a profile. There is no 404 for an unknown user: the ladder's
whole purpose is that nobody is served nothing, and a user with no history is a
rung-3 answer rather than an absence.

Every response carries the rung, the method and the model version, so a served
result can be traced back to the configuration that produced it (task 20).
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query

from reco.config import Settings, get_settings
from reco.config import live
from reco.platform import readers
from reco.store.connection import ml_db
from reco.store.writers import current_job_run_id
from reco.store.scores import Method, utc_now
from reco.slots.interest.context import ScoringContext
from reco.fallback.read_path import get_profile
from reco.jobs.refresh import METHODS as REFRESH_METHODS

router = APIRouter(tags=["profiles"])


def _as_dict(result) -> dict:
    """One response shape, used by every endpoint that returns a profile."""
    return {
        "user_id": result.user_id,
        # The rung is part of the answer, not a log line. A screen that cannot
        # tell rung 3 from rung 1 might label platform popularity as
        # "Recommended for you".
        "rung": int(result.rung),
        "rung_description": result.rung_description,
        "personalised": result.personalised,
        "fell_through_from": (
            int(result.fell_through_from) if result.fell_through_from else None
        ),
        # Task 20: the stamp travels with every response.
        "method": result.method,
        "model_version": result.model_version,
        "computed_at": (
            result.computed_at.isoformat() if result.computed_at else None
        ),
        "popularity_window_days": result.popularity_window_days,
        "categories": [
            {
                "category": c.category,
                "share": c.share,
                "raw": c.raw,
                "event_count": c.event_count,
            }
            for c in result.categories
        ],
    }


@router.get("/profile/{user_id}")
async def profile(
    user_id: str,
    method: Method = Query(
        Method.RECENCY_DECAY,
        description="which method's scores to serve",
    ),
    settings: Settings = Depends(get_settings),
) -> dict:
    return _as_dict(await get_profile(settings, user_id, method=method))


@router.get("/profile/{user_id}/compare")
async def compare(
    user_id: str,
    settings: Settings = Depends(get_settings),
) -> dict:
    """One user under every method in the store, for a side-by-side.

    Three of the running order's steps are comparisons, and a display that can
    only show one method at a time cannot carry them -- which is why DS-014
    states the side-by-side requirement rather than assuming it.
    """
    return {
        "user_id": user_id,
        "methods": {
            str(method): _as_dict(
                await get_profile(settings, user_id, method=method)
            )
            for method in Method
        },
    }


@router.get("/users")
async def users(
    method: Method = Query(Method.RECENCY_DECAY),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Who has a score, split into the narrated users and the filler.

    The twenty narrated users are a coverage claim, not a scale claim -- each
    proves one thing none of the others prove. The filler exists so platform
    popularity is computed over two hundred profiles rather than twenty
    deliberately skewed ones.
    """
    collection = ml_db(settings)[settings.scores_collection]
    scored = sorted(
        await collection.distinct(
            "user_id",
            {"method": str(method), "model_version": settings.model_version,
             "job_run_id": await current_job_run_id(settings, "interest", str(method))},
        )
    )
    all_users = await readers.read_all_user_ids(settings)

    return {
        "method": str(method),
        "model_version": settings.model_version,
        "narrated": [u for u in all_users if not u.startswith("F")],
        "filler_count": sum(1 for u in all_users if u.startswith("F")),
        "scored": scored,
        "unscored": [u for u in all_users if u not in set(scored)],
    }


@router.get("/methods")
async def methods(settings: Settings = Depends(get_settings)) -> dict:
    """What is actually in the store, and the parameters behind each.

    `decay_off` marks the run with the decay term switched off. It is stored
    under its own method value: sharing one with the decay-on run would have the
    data checks compare it against the wrong expectations.
    """
    collection = ml_db(settings)[settings.scores_collection]
    present = sorted(await collection.distinct("method"))

    return {
        "collection": settings.scores_collection,
        "model_version": settings.model_version,
        "methods": [
            {
                "method": name,
                "rows": await collection.count_documents({"method": name}),
                "decay_off": name.endswith("_h_inf"),
            }
            for name in present
        ],
        "tunables": live.current().m1(),
    }


@router.get("/diagnostics/{user_id}")
async def diagnostics(
    user_id: str,
    method: Method = Query(Method.RECENCY_DECAY),
    settings: Settings = Depends(get_settings),
) -> dict:
    """What the model refused to count for this user, and why.

    Three counters, kept apart on purpose. A rising unresolved-category rate and
    a rising sub-threshold-view rate mean different things and want different
    fixes; one combined "dropped" figure would hide both.

    Recomputed on demand rather than stored: these are properties of a read, and
    they change when a tunable changes.
    """
    module, window, decay_enabled = REFRESH_METHODS[method]

    events, read_stats = await readers.read_user_events(settings, user_id)
    ctx = ScoringContext(
        tunables=live.current().m1(),
        declared_interests=await readers.read_declared_interests(settings, user_id),
        order_created_at=await readers.read_all_order_creation_times(settings),
        now=utc_now(),
        decay_enabled=decay_enabled,
    )
    _, stats = module.score(events, ctx)

    return {
        "user_id": user_id,
        "method": str(method),
        "events_read": read_stats.read,
        "events_scored": stats.events_scored,
        "dropped": [
            {
                "reason": "view too short to mean anything",
                "detail": f"under P-02 = {live.current().events.qualified_view_seconds}s",
                "count": stats.sub_threshold_views,
            },
            {
                "reason": "view with no recorded duration",
                "detail": "neither qualified nor below threshold",
                "count": stats.views_without_duration,
            },
            {
                "reason": "category could not be resolved",
                "detail": "no canonical equivalent, so dropped and counted",
                "count": read_stats.unresolved_category,
            },
            {
                "reason": "timestamp missing",
                "detail": "cannot be aged, and never treated as new",
                "count": read_stats.missing_timestamp,
            },
            {
                "reason": "timestamp in the future",
                "detail": "would give a decay factor above one",
                "count": read_stats.future_timestamp,
            },
            {
                "reason": "event type carries no weight",
                "detail": "not assumed to be a view",
                "count": read_stats.unknown_event_type,
            },
            {
                "reason": "older than the last window",
                "detail": "time windows only; decay still counts it",
                "count": stats.events_outside_window,
            },
        ],
        "unmapped_categories": read_stats.unmapped_examples,
        "reversals_applied": stats.reversals_applied,
        "reversals_unaged": stats.reversals_unaged,
    }


@router.get("/overview")
async def overview(settings: Settings = Depends(get_settings)) -> dict:
    """Everything a dashboard needs about the whole population, in one call.

    Aggregates rather than a user at a time: how many land on each rung, where
    the two methods disagree, what is being dropped and how often. These are the
    figures that say whether the engine is healthy; a single profile says only
    whether one user is.
    """
    collection = ml_db(settings)[settings.scores_collection]
    version = settings.model_version

    rows = [
        row
        async for row in collection.find(
            {"model_version": version, "$or": [
                {"method": m, "job_run_id": await current_job_run_id(settings, "interest", m)}
                for m in await collection.distinct("method")
            ] or [{"_id": None}]},
            {"_id": 0, "user_id": 1, "category": 1, "share": 1, "raw": 1,
             "event_count": 1, "method": 1},
        )
    ]

    by_method: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        by_method.setdefault(row["method"], {}).setdefault(row["user_id"], []).append(row)

    primary = str(Method.RECENCY_DECAY)
    primary_users = by_method.get(primary, {})
    all_users = await readers.read_all_user_ids(settings)

    # --- the ladder, across the whole population -------------------------
    #
    # Derived from what is stored rather than by walking the ladder 195 times:
    # a score with contributing events is rung 1, a score with none is the
    # declared floor alone (rung 2), and no score at all is rung 3.
    rungs = {1: [], 2: [], 3: []}
    for user_id in all_users:
        scores = primary_users.get(user_id)
        if not scores:
            rungs[3].append(user_id)
        elif sum(s.get("event_count") or 0 for s in scores) == 0:
            rungs[2].append(user_id)
        else:
            rungs[1].append(user_id)

    # --- where the methods disagree --------------------------------------
    def top_category(scores: list[dict]) -> str | None:
        return max(scores, key=lambda s: s["share"])["category"] if scores else None

    comparisons = []
    for other in sorted(by_method):
        if other == primary:
            continue
        shared = set(primary_users) & set(by_method[other])
        disagreed = [
            u for u in shared
            if top_category(primary_users[u]) != top_category(by_method[other][u])
        ]
        comparisons.append({
            "method": other,
            "users_compared": len(shared),
            "top_category_differs": len(disagreed),
            "examples": sorted(u for u in disagreed if not u.startswith("F"))[:8],
        })

    # --- category coverage ------------------------------------------------
    coverage: Counter[str] = Counter()
    weight: dict[str, float] = {}
    for user_id, scores in primary_users.items():
        for s in scores:
            coverage[s["category"]] += 1
            weight[s["category"]] = weight.get(s["category"], 0.0) + s["share"]

    # --- what was dropped, over the whole read ----------------------------
    _, read_stats = await readers.read_events_by_user(settings)

    return {
        "model_version": version,
        "collection": settings.scores_collection,
        "users_total": len(all_users),
        "narrated": [u for u in all_users if not u.startswith("F")],
        "rungs": {
            "1": {"label": "personalised score", "users": len(rungs[1]),
                  "narrated": [u for u in rungs[1] if not u.startswith("F")]},
            "2": {"label": "declared interests only", "users": len(rungs[2]),
                  "narrated": [u for u in rungs[2] if not u.startswith("F")]},
            "3": {"label": "platform popularity", "users": len(rungs[3]),
                  "narrated": [u for u in rungs[3] if not u.startswith("F")]},
        },
        "methods": [
            {"method": m, "rows": sum(len(v) for v in users.values()),
             "users": len(users)}
            for m, users in sorted(by_method.items())
        ],
        "comparisons": comparisons,
        "categories": [
            {"category": c, "users": n, "share_total": round(weight[c], 3)}
            for c, n in coverage.most_common()
        ],
        "events": {
            "read": read_stats.read,
            "dropped": read_stats.dropped,
            "unresolved_category": read_stats.unresolved_category,
            "missing_timestamp": read_stats.missing_timestamp,
            "future_timestamp": read_stats.future_timestamp,
            "unknown_event_type": read_stats.unknown_event_type,
            "unmapped_values": read_stats.unmapped_category_values,
            "unmapped_examples": read_stats.unmapped_examples,
        },
    }


@router.get("/popularity")
async def popularity(settings: Settings = Depends(get_settings)) -> dict:
    """Rung 3: platform-wide category popularity over the P-27 window.

    The same answer for every user who lands here, which is why it is labelled
    as not personalised wherever it is served.
    """
    counts = await readers.read_category_popularity(
        settings, window_days=live.current().interest.popularity_window_days
    )
    total = sum(counts.values())

    return {
        "window_days": live.current().interest.popularity_window_days,
        "personalised": False,
        "total_events": total,
        "categories": [
            {"category": c, "events": n, "share": n / total if total else 0.0}
            for c, n in counts.items()
        ],
    }
