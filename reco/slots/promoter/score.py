"""M8 promoter score, the maths: components, percentiles, both methods. ENG-16. Pure.

    scored = score_promoters(inputs, settings=PromoterSettings.from_tunables(t), commerce_on=True)
    scored["p1"].method_one.score, .method_two.score, .confidence, .flags

Components (Build List v1.4 ENG-16), each turned into a percentile (0 to 1) within
the promoter's main category:

    reach            unique users with a qualified view of their original posts, 30 days
    content_quality  likes + saves + shares + comments per qualified view, original posts, 30 days
    consistency      the share of the last 8 weeks with at least one original post
    net_commerce     value (total_price) of completed sales through their posts, 90 days
    conversion       completed sales per 1,000 qualified views
    sales_quality    1 - (cancelled + rejected + returned) / orders that reached a final state

Weights 0.20, 0.20, 0.10, 0.25, 0.15, 0.10 (promoter.weights), rescaled over the
components in use: at launch, without commerce data, 0.40, 0.40, 0.20.

Method one (shrinkage): (n x own + 20 x category average) / (n + 20), n = qualified
views / 100; confidence n / (n + 20); low_confidence when n is below 20.
Method two (cohort_percentile): own as a percentile within the cohort of the same
main category and follower band; a cohort under 20 uses the whole category; still
under 20, every scored promoter, marked small_cohort. It stores method one's
confidence. No other scored promoter in the category: category average 0.5 and
no_peer_group. A confirmed fraud case that led to a restriction halves both.

Percentiles: (below + (equal - 1) / 2) / (n - 1), as ENG-15; a group of one gives 0.5.
Where the pack is silent (decided 17 Oct 2026, docs/engineering/ENG-16.md): a
promoter with no order in a final state takes 0.5 for sales quality; the
commerce components are in use once any scored promoter has an order in a final
state (and returnrequests can be read); conversion uses the qualified views of
the same 90 days as its sales.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

COMPONENTS = ("reach", "content_quality", "consistency", "net_commerce", "conversion", "sales_quality")
COMMERCE = ("net_commerce", "conversion", "sales_quality")
NEUTRAL = 0.5
NO_CATEGORY = "(none)"


@dataclass(frozen=True)
class PromoterSettings:
    weights: Mapping[str, float]
    strength: float = 20
    cohort_minimum: int = 20
    trust_multiplier: float = 0.5
    low_confidence_below: float = 20
    follower_bands: tuple[int, ...] = (1000, 10000)

    @classmethod
    def from_tunables(cls, tunables: Any) -> PromoterSettings:
        p = tunables.promoter
        return cls(p.weights.model_dump(), p.shrinkage_strength, p.cohort_minimum, p.fraud_trust_multiplier,
                   p.low_confidence_below, tuple(p.follower_bands))


@dataclass
class PromoterInput:
    promoter_id: str
    kind: str  # "user" or "business" (a store with original posts is scored like any promoter)
    main_category: str | None
    followers: int
    qualified_views_30d: int  # qualified view rows (one per viewer per post) on original posts
    reach_30d: int  # unique viewers among them
    engagements_30d: int  # likes + saves + shares + comments on original posts
    weeks_posted: int  # of the last 8, weeks with at least one original post
    qualified_views_90d: int = 0
    completed_value: float = 0.0
    completed_count: int = 0
    final_count: int = 0
    bad_count: int = 0
    trust_halved: bool = False


@dataclass
class MethodScore:
    score: float
    group: str  # method one: "category"; method two: "band", "category" or "all"


@dataclass
class Scored:
    promoter_id: str
    kind: str
    main_category: str | None
    follower_band: str
    raw: dict[str, float | None]
    percentiles: dict[str, float]
    weights: dict[str, float]
    own: float
    category_average: float
    confidence: float
    n: float
    method_one: MethodScore
    method_two: MethodScore
    flags: list[str] = field(default_factory=list)


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Each id's percentile among the group, 0 to 1 (ties counted half); one id: 0.5."""
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {k: NEUTRAL for k in values}
    ordered = sorted(values.values())
    out = {}
    for key, value in values.items():
        below = bisect_left(ordered, value)
        equal = bisect_right(ordered, value) - below
        out[key] = (below + (equal - 1) / 2) / (n - 1)
    return out


def follower_band(followers: int, bands: tuple[int, ...]) -> str:
    """Under 1,000; 1,000 to 10,000; over 10,000 (with the default bands)."""
    if followers < bands[0]:
        return f"under_{bands[0]}"
    for low, high in zip(bands, bands[1:]):
        if followers <= high:
            return f"{low}_to_{high}"
    return f"over_{bands[-1]}"


def raw_components(p: PromoterInput) -> dict[str, float | None]:
    return {
        "reach": float(p.reach_30d),
        "content_quality": p.engagements_30d / p.qualified_views_30d if p.qualified_views_30d > 0 else None,
        "consistency": p.weeks_posted / 8,
        "net_commerce": float(p.completed_value),
        "conversion": p.completed_count / p.qualified_views_90d * 1000 if p.qualified_views_90d > 0 else None,
        "sales_quality": 1 - p.bad_count / p.final_count if p.final_count > 0 else None,
    }


def components_in_use(commerce_on: bool) -> tuple[str, ...]:
    return COMPONENTS if commerce_on else tuple(c for c in COMPONENTS if c not in COMMERCE)


def rescaled(weights: Mapping[str, float], in_use: Iterable[str]) -> dict[str, float]:
    used = {c: weights[c] for c in in_use}
    total = sum(used.values()) or 1.0
    return {c: w / total for c, w in used.items()}


def score_promoters(inputs: Iterable[PromoterInput], *, settings: PromoterSettings, commerce_on: bool) -> dict[str, Scored]:
    """Both methods for every promoter given (the caller has already applied who is
    scored, including "no qualified views: not scored")."""
    promoters = [p for p in inputs if p.qualified_views_30d > 0]
    in_use = components_in_use(commerce_on)
    weights = rescaled(settings.weights, in_use)
    raw = {p.promoter_id: raw_components(p) for p in promoters}
    by_category: dict[str, list[PromoterInput]] = defaultdict(list)
    for p in promoters:
        by_category[p.main_category or NO_CATEGORY].append(p)

    pct: dict[str, dict[str, float]] = {p.promoter_id: {} for p in promoters}
    for members in by_category.values():
        for component in in_use:
            have = {m.promoter_id: raw[m.promoter_id][component] for m in members
                    if raw[m.promoter_id][component] is not None}
            ranks = percentile_ranks(have)
            for m in members:
                pct[m.promoter_id][component] = ranks.get(m.promoter_id, NEUTRAL)

    own = {pid: sum(weights[c] * pct[pid][c] for c in in_use) for pid in pct}
    averages = {cat: (sum(own[m.promoter_id] for m in members) / len(members) if len(members) > 1 else NEUTRAL)
                for cat, members in by_category.items()}

    bands = {p.promoter_id: follower_band(p.followers, settings.follower_bands) for p in promoters}
    cohorts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in promoters:
        cohorts[(p.main_category or NO_CATEGORY, bands[p.promoter_id])].append(p.promoter_id)
    everyone = {p.promoter_id: own[p.promoter_id] for p in promoters}
    everyone_ranks = percentile_ranks(everyone)
    category_ranks = {cat: percentile_ranks({m.promoter_id: own[m.promoter_id] for m in members})
                      for cat, members in by_category.items()}
    cohort_ranks = {key: percentile_ranks({pid: own[pid] for pid in ids}) for key, ids in cohorts.items()}

    out: dict[str, Scored] = {}
    k = settings.strength
    for p in promoters:
        pid, cat = p.promoter_id, p.main_category or NO_CATEGORY
        flags: list[str] = []
        if len(by_category[cat]) == 1:
            flags.append("no_peer_group")
        if p.main_category is None:
            flags.append("no_main_category")
        n = p.qualified_views_30d / 100
        confidence = n / (n + k)
        if n < settings.low_confidence_below:
            flags.append("low_confidence")
        one = (n * own[pid] + k * averages[cat]) / (n + k)
        cohort = cohorts[(cat, bands[pid])]
        if len(cohort) >= settings.cohort_minimum:
            two, group = cohort_ranks[(cat, bands[pid])][pid], "band"
        elif len(by_category[cat]) >= settings.cohort_minimum:
            two, group = category_ranks[cat][pid], "category"
        else:
            two, group = everyone_ranks[pid], "all"
            flags.append("small_cohort")
        if p.trust_halved:
            one, two = one * settings.trust_multiplier, two * settings.trust_multiplier
            flags.append("trust_halved")
        out[pid] = Scored(
            promoter_id=pid, kind=p.kind, main_category=p.main_category, follower_band=bands[pid],
            raw=raw[pid], percentiles=pct[pid], weights=weights, own=own[pid], category_average=averages[cat],
            confidence=confidence, n=n, method_one=MethodScore(one, "category"), method_two=MethodScore(two, group),
            flags=flags,
        )
    return out
