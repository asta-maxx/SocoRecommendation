"""Every value on the Build List's Settings sheet. ENG-02 item 3, SD-07.

The settings file (settings/engine.toml) is parsed into this model. The defaults
here ARE the Settings sheet's starting values, so "no good version has ever
loaded" (SD-09) means exactly these.

Validation follows the sheet's "Allowed range" column. Where the sheet gives no
range and says the value is fixed for Wave 1A, the value may not change at all
(a range of one value). A value the sheet ties to a rule ("sum to 1",
"ascending") is checked for that rule.

Secrets, connection strings and which environment this is are NOT here: they live
in the server environment (SD-08) and in reco.config.Settings.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --- helpers ------------------------------------------------------------------


def fixed(value: float) -> Any:
    """A number the Settings sheet fixes for Wave 1A: only this value is valid.
    The sheet: "A value changes only where the 'When it changes' column says so"
    -- rows marked "Fixed for Wave 1A" keep their value even where a range is given."""
    return Field(value, ge=value, le=value)


def between(value: float, low: float, high: float) -> Any:
    """A number with the Settings sheet's allowed range."""
    return Field(value, ge=low, le=high)


class _Section(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}


def _sums_to_one(section: BaseModel, label: str) -> None:
    total = sum(float(v) for v in section.model_dump().values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"{label} must sum to 1, got {total}")


# --- Serving --------------------------------------------------------------------


class Serving(_Section):
    service_p95_target_ms: int = fixed(200)  # ENG-06, APP-15
    soco_be_timeout_ms: int = between(250, 100, 400)  # APP-15
    stage_limit_retrieval_ms: int = fixed(80)  # ENG-12, ENG-19
    stage_limit_ranking_ms: int = fixed(80)
    stage_limit_network_ms: int = fixed(40)
    circuit_breaker_failures: int = fixed(5)  # APP-15; sheet range 3-20, fixed for Wave 1A
    circuit_breaker_test_call_seconds: int = fixed(30)  # sheet range 10-300, fixed for Wave 1A
    over_fetch_items: int = fixed(0)  # ENG-06: the engine returns exactly `limit`
    cache_max_seconds: int = fixed(60)  # APP-15
    #: ENG-06, ENG-24, SD-10. off, internal or live -- no shadow mode. Internal
    #: gives engine lists only to the test accounts in lists.test_accounts (503
    #: to everyone else), for checks on production before launch. The sheet's
    #: value is "live, each only if its checks pass"; none has passed, so both
    #: are off until ENG-24 switches them.
    surface_mode_feed: Literal["off", "internal", "live"] = "off"
    surface_mode_product: Literal["off", "internal", "live"] = "off"
    sample_random_percent: int = fixed(10)  # ENG-06; sheet range 1-100, fixed for Wave 1A
    exploration_percent: int = fixed(5)  # ENG-06, feed only; sheet: "Stays at 5% for Wave 1A"
    exploration_top_kept: int = fixed(3)
    page_dedup_hours: int = fixed(24)  # ENG-19; sheet range 1-72, fixed for Wave 1A


# --- Method choice ---------------------------------------------------------------


class Slot(_Section):
    """ENG-05. The split is always the share on method two (ENG-26)."""

    method_one: str
    method_two: str
    split: int = between(50, 0, 50)
    default_method: Literal["method_one"] = "method_one"

    @field_validator("method_one", "method_two")
    @classmethod
    def _named(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a slot's method needs a name")
        return v.strip()


class Slots(_Section):
    interest: Slot = Slot(method_one="recency_decay", method_two="time_windows")
    product_ranking: Slot = Slot(
        method_one="attribute_similarity", method_two="bought_together"
    )
    #: ENG-16 calls these method one and method two; the names are ours.
    promoter_score: Slot = Slot(method_one="shrinkage", method_two="cohort_percentile")


# --- Events and session ------------------------------------------------------------


class Events(_Section):
    qualified_view_seconds: float = between(3, 1, 10)  # APP-00, ENG-10
    qualified_view_visible_fraction: float = between(0.5, 0.1, 1.0)
    app_batch_seconds: int = fixed(10)  # APP-12 (app side)
    app_batch_events: int = fixed(20)
    #: ENG-04 engine sync (replaces the retired SOCO_BE forward): every 5
    #: minutes, re-reading a 2-minute overlap; alert when more than 15 minutes behind.
    sync_interval_minutes: int = fixed(5)  # sheet range 1-15, fixed for Wave 1A
    sync_overlap_minutes: int = fixed(2)
    sync_lag_alert_minutes: int = fixed(15)
    #: DB-01, ENG-04, SD-29: engine copies kept at least this many days from the
    #: original event time, under the engine's own expiry (the platform keeps 90).
    retention_days: int = fixed(365)
    session_away_minutes: int = fixed(30)  # APP-01: new session after 30 minutes or more away


class Filters(_Section):
    feedback_hide_days: int = fixed(90)  # ENG-08, E-03; sheet range 30-365, fixed for Wave 1A
    #: ENG-27, ENG-08: full re-read of posts, accounts and products; completed
    #: refreshes only; blocks, visibility and stock re-checked on returned items.
    eligibility_refresh_minutes: int = fixed(15)  # sheet range 5-60, fixed for Wave 1A


# --- M1 interest -----------------------------------------------------------------


class InterestWeights(_Section):
    """ENG-10. Each −20 to 50."""

    qualified_view: float = between(2, -20, 50)
    click: float = between(5, -20, 50)
    like: float = between(3, -20, 50)
    save: float = between(4, -20, 50)
    share: float = between(4, -20, 50)
    comment: float = between(4, -20, 50)
    add_to_cart: float = between(10, -20, 50)
    purchase: float = between(20, -20, 50)
    business_follow: float = between(5, -20, 50)
    not_interested_or_hide: float = between(-5, -20, 50)


class Interest(_Section):
    weights: InterestWeights = InterestWeights()
    declared_floor: float = between(10, 0, 50)
    declared_floor_decays: Literal[False] = False  # "never decays"
    half_life_days: float = between(30, 7, 180)  # method one
    #: None at launch. Each value 7 to 180 days.
    per_category_half_life_days: dict[str, float] = Field(default_factory=dict)
    #: Method two: 0-7, 8-30, 31-90 days. Upper bounds, ascending.
    window_bounds_days: list[int] = Field(default_factory=lambda: [7, 30, 90])
    window_weights: list[float] = Field(default_factory=lambda: [0.5, 0.3, 0.2])
    refresh_cadence: Literal["daily"] = "daily"  # sheet range hourly to weekly, fixed for Wave 1A
    refresh_time_ist: Literal["02:00"] = "02:00"  # ENG-07, SD-22: a setting, fixed for Wave 1A
    stale_after_hours: float = between(48, 1, 72)  # ENG-09 rung 4
    personal_min_actions: int = fixed(5)  # ENG-09 rung 1
    personal_window_days: int = fixed(90)
    popularity_window_days: int = between(30, 7, 365)  # ENG-09 rung 3

    @field_validator("per_category_half_life_days")
    @classmethod
    def _per_category(cls, v: dict[str, float]) -> dict[str, float]:
        for category, days in v.items():
            if not 7 <= days <= 180:
                raise ValueError(f"half life for {category!r} must be 7-180 days, got {days}")
        return v

    @field_validator("window_bounds_days")
    @classmethod
    def _bounds(cls, v: list[int]) -> list[int]:
        if len(v) != 3 or not all(1 <= b <= 365 for b in v) or not v[0] < v[1] < v[2]:
            raise ValueError(f"window bounds must be three ascending days within 1-365, got {v}")
        return v

    @field_validator("window_weights")
    @classmethod
    def _window_weights(cls, v: list[float]) -> list[float]:
        if len(v) != 3 or not all(0 <= w <= 1 for w in v):
            raise ValueError(f"window weights must be three values within 0-1, got {v}")
        if abs(sum(v) - 1.0) > 1e-9:
            raise ValueError(f"window weights must sum to 1, got {sum(v)}")
        return v

    @field_validator("refresh_time_ist")
    @classmethod
    def _time(cls, v: str) -> str:
        hours, _, minutes = v.partition(":")
        if not (hours.isdigit() and minutes.isdigit() and int(hours) < 24 and int(minutes) < 60):
            raise ValueError(f"refresh_time_ist must be HH:MM, got {v!r}")
        return v


# --- M2 retrieval ------------------------------------------------------------------


class SourceShares(_Section):
    interest: float = fixed(0.4)
    follows: float = fixed(0.3)
    trending: float = fixed(0.2)
    platform_popular: float = fixed(0.1)

    @model_validator(mode="after")
    def _sum(self) -> SourceShares:
        _sums_to_one(self, "retrieval source shares")
        return self


class Retrieval(_Section):
    pool_size: int = between(300, 100, 2000)  # ENG-13; cut first if speed is missed
    source_shares: SourceShares = SourceShares()
    post_age_days: int = fixed(30)
    shortlist_size: int = fixed(200)  # ENG-15
    #: ENG-15 (Nisha, 16 Oct 2026): method two's share of the shortlist's places when
    #: both lists are full; 0.4 is the two lists' sizes, 200 of 300 + 200. A short list
    #: passes its places to the other. Not on the pack's Settings sheet.
    shortlist_method_two_share: float = between(0.4, 0.0, 1.0)
    source_time_limit_ms: int = between(20, 10, 40)  # ENG-12
    similar_engaged_posts: int = fixed(50)  # ENG-14
    similar_top_stored: int = fixed(200)
    similar_max_posts: int = fixed(5000)
    similar_min_engaged: int = fixed(3)
    #: ENG-14 (Kala, 16 Oct): a post's type is postTypeDetailed where filled, else postType;
    #: empty gives "normal"; anything not listed goes to "other" and is reported daily.
    #: Adding a type is a model_version change.
    post_types: list[str] = Field(default_factory=lambda: ["photo", "video", "normal", "other"])


# --- Ranking --------------------------------------------------------------------


class RankingWeights(_Section):
    """ENG-19. Commission is never a term."""

    interest: float = fixed(0.35)
    retrieval: float = fixed(0.15)
    promoter: float = fixed(0.20)
    freshness: float = fixed(0.20)
    engagement_quality: float = fixed(0.10)

    @model_validator(mode="after")
    def _sum(self) -> RankingWeights:
        _sums_to_one(self, "feed ranking weights")
        return self


class Ranking(_Section):
    weights: RankingWeights = RankingWeights()
    freshness_half_life_days: float = fixed(3)
    max_consecutive_same_author: int = fixed(2)
    max_per_author_per_page: int = fixed(3)
    max_category_fraction: float = fixed(0.4)
    min_category_cap: int = fixed(2)
    engagement_shrinkage_views: int = between(50, 10, 500)


# --- M5 product ---------------------------------------------------------------


class ProductWeights(_Section):
    category: float = fixed(0.35)
    cross_sell: float = fixed(0.20)
    price_band: float = fixed(0.15)
    popularity: float = fixed(0.20)
    same_seller: float = fixed(0.10)

    @model_validator(mode="after")
    def _sum(self) -> ProductWeights:
        _sums_to_one(self, "product ranker weights")
        return self


class Product(_Section):
    """ENG-17. The two methods are compared by the split, never blended."""

    weights: ProductWeights = ProductWeights()
    lift_strength: int = fixed(10)
    min_co_purchases: int = fixed(2)
    price_band_fraction: float = fixed(0.30)  # sheet range 10-50%, fixed for Wave 1A
    #: ENG-17, not on the pack's Settings sheet (decided 17 Oct 2026): how many products
    #: each stored list keeps per viewed product (both methods), and per top-level
    #: category for fallback step 2. A request needs at most a page plus one spare page
    #: (limit 50), so these leave room for the filters and for page 2.
    stored_per_product: int = between(100, 50, 500)
    stored_per_category: int = between(200, 50, 1000)
    #: ENG-17: "Until the basket test (APP-22) passes, compute it over cart contents
    #: instead, and label it 'intent'." cart until APP-22 passes (ENG-23 V5); then
    #: checkout (orders sharing a checkout_id). A setting, so the switch needs no deploy.
    basket_source: Literal["cart", "checkout"] = "cart"


# --- M6 opportunity ---------------------------------------------------------------


class OpportunityWeights(_Section):
    commission: float = fixed(0.30)
    sell_through: float = fixed(0.40)
    fit: float = fixed(0.30)

    @model_validator(mode="after")
    def _sum(self) -> OpportunityWeights:
        _sums_to_one(self, "opportunity weights")
        return self


class Opportunity(_Section):
    """ENG-18."""

    weights: OpportunityWeights = OpportunityWeights()
    default_commission_rate: float = fixed(0.10)
    sell_through_window_days: int = fixed(30)  # sheet range 7-180, fixed for Wave 1A


# --- M8 promoter --------------------------------------------------------------------


class PromoterWeights(_Section):
    """ENG-16. Rescaled over the components whose data exists."""

    reach: float = fixed(0.20)
    content_quality: float = fixed(0.20)
    consistency: float = fixed(0.10)
    net_commerce: float = fixed(0.25)
    conversion: float = fixed(0.15)
    sales_quality: float = fixed(0.10)

    @model_validator(mode="after")
    def _sum(self) -> PromoterWeights:
        _sums_to_one(self, "promoter component weights")
        return self


class Promoter(_Section):
    weights: PromoterWeights = PromoterWeights()
    shrinkage_strength: float = between(20, 5, 100)
    cohort_minimum: int = fixed(20)
    fraud_trust_multiplier: float = fixed(0.5)
    low_confidence_below: float = between(20, 10, 200)
    #: Under 1,000; 1,000 to 10,000; over 10,000.
    follower_bands: list[int] = Field(default_factory=lambda: [1000, 10000])

    @field_validator("follower_bands")
    @classmethod
    def _bands(cls, v: list[int]) -> list[int]:
        if not v or any(b <= 0 for b in v) or v != sorted(set(v)):
            raise ValueError(f"follower bands must be positive and ascending, got {v}")
        return v


# --- Commerce -------------------------------------------------------------------


class Commerce(_Section):
    """A completed sale is Delivered with no return requested in the window (fixed)."""

    pending_open_days: int = between(14, 7, 45)  # ENG-16
    #: ENG-30 point 7: the return-request copy is current when its last sync completed
    #: within this many hours and its last reconciliation passed (fixed for Wave 1A).
    return_request_current_hours: int = fixed(24)
    #: ENG-30 point 3: a repost is followed to its original for at most this many
    #: steps; a longer chain or a loop has no original and is logged (fixed for Wave 1A).
    repost_chain_max_steps: int = fixed(10)
    #: ENG-30 point 8: the return window when a product has none (logged as a
    #: fallback, not as product policy), and the buffer after any window.
    return_window_fallback_days: int = fixed(7)  # sheet range 0-90, fixed for Wave 1A
    return_buffer_days: int = between(2, 0, 7)


# --- M9 fraud --------------------------------------------------------------------


class Fraud(_Section):
    """ENG-21. Thresholds change only under the calibration rule."""

    r01_actions_per_minute: int = Field(30, gt=0)
    r02_actions_per_day: int = Field(1000, gt=0)
    r03_orders_for_review: int = Field(3, gt=0)
    r03_window_days: int = Field(30, gt=0)
    r04_delivered_rate_ratio: float = Field(0.5, gt=0, lt=1)
    r04_min_orders: int = between(10, 10, 100)
    r05_buyer_share: float = Field(0.5, gt=0, lt=1)
    r05_min_orders: int = Field(5, gt=0)
    r05_window_days: int = Field(30, gt=0)
    r06_exclusive_share: float = Field(0.4, gt=0, lt=1)
    r06_min_accounts: int = Field(50, gt=0)
    r06_window_days: int = Field(30, gt=0)
    r07_same_day_share: float = Field(0.3, gt=0, lt=1)
    r07_min_followers: int = Field(50, gt=0)
    r07_window_days: int = Field(7, gt=0)
    r08_multiple: float = Field(10, gt=1)
    r08_baseline_days: int = Field(14, gt=0)
    r08_min_engagements: int = Field(100, gt=0)
    r09_like_share_of_views: float = Field(0.8, gt=0, le=1)
    r09_min_views: int = Field(100, gt=0)
    r11_days_after_creation: int = Field(7, gt=0)
    r12_accounts_per_device: int = Field(3, gt=1)
    r12_window_days: int = Field(30, gt=0)
    #: Rules switched to watch-only by calibration, e.g. ["R09"].
    watch_only: list[str] = Field(default_factory=list)
    watch_clears_days: int = fixed(30)
    strike_months: int = fixed(12)
    review_due_working_days: int = fixed(5)
    review_due_urgent_working_days: int = fixed(1)
    restricted_days: int = fixed(14)  # APP-18
    suspended_days: int = fixed(30)
    appeal_days: int = fixed(30)  # APP-19
    appeal_decision_working_days: int = fixed(10)
    review_capacity_per_week: int = fixed(20)

    @field_validator("watch_only")
    @classmethod
    def _rules(cls, v: list[str]) -> list[str]:
        known = {f"R{n:02d}" for n in range(1, 13)}
        unknown = [r for r in v if r not in known]
        if unknown:
            raise ValueError(f"unknown fraud rules in watch_only: {unknown}")
        return v


# --- Comparison ------------------------------------------------------------------


class Comparison(_Section):
    """ENG-26. Fixed for Wave 1A."""

    min_weeks_live: int = fixed(4)
    min_impressions_per_method: int = fixed(2000)
    min_relative_lift: float = fixed(0.03)
    confidence: float = fixed(0.95)
    rollback_drop: float = fixed(0.05)
    cycle_days: int = fixed(14)


# --- Lists (ENG-29, Settings sheet "Lists") ------------------------------------------


class AccountEntry(_Section):
    """An exemption or test-account entry: account id, reason, expiry, who changed it."""

    account_id: str
    reason: str
    expiry: date
    changed_by: str

    @field_validator("account_id")
    @classmethod
    def _account(cls, v: str) -> str:
        v = v.strip()
        if len(v) != 24 or any(c not in "0123456789abcdef" for c in v.lower()):
            raise ValueError(f"account_id must be a 24-character id, got {v!r}")
        return v.lower()

    @field_validator("reason", "changed_by")
    @classmethod
    def _filled(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason and changed_by must not be blank")
        return v.strip()


class OrderStatusValues(_Section):
    """The exact stored order_status values the engine reads (ENG-23 V8). order_status
    is the order's state (Build List v1.4 ENG-30 points 5 and 6). There is no Return
    Requested status: a request is a returnrequests record (ENG-30 point 7)."""

    delivered: str = "Delivered"
    cancelled: str = "Cancelled"
    rejected: str = "Rejected"
    returned: str = "Returned"


#: History events (Build List v1.4 ENG-30 point 5).
TrackingStage = Literal["created", "accepted", "confirmed", "shipped", "payment", "delivered", "cancelled",
                        "rejected", "return_request", "refund", "returned", "replacement"]

#: ENG-30 point 5, the history-text map: each tracking_info entry's opening words ->
#: its history event, matched as whole words, ignoring case. Every text on the
#: platform database on 15 Oct 2026 maps.
TRACKING_STAGES: dict[str, str] = {
    "order created": "created",
    "order accepted": "accepted",
    "confirmed by buyer": "confirmed",
    "shipped": "shipped",
    "payment completed": "payment",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "return requested": "return_request",
    "refund of": "refund",
    "returned to seller": "returned",
    # The other texts the app writes (its code, 16 Oct). Information only: the state
    # is order_status. A replacement or exchange is never the Delivered event.
    "order placed": "created",
    # Nisha, 16 Oct: the status the platform sets for it (Rejected on all 5 dev orders).
    # Scoring treats Cancelled and Rejected alike; order_status stays the state.
    "rejected by buyer": "rejected",
    "replacement delivered": "replacement",
    "exchange delivered": "replacement",
}


class Lists(_Section):
    """Maintained by Allen; every change is a new config_version, logged in ml_config_changes."""

    #: Platform category (name, any case) -> one of the 23. Must cover every
    #: category in use; unmapped categories are reported daily and left out of
    #: category scoring until mapped, never guessed (ENG-29 item 1, X-20).
    category_map: dict[str, str] = Field(default_factory=dict)
    #: Status spellings, compared ignoring case: stored spelling -> the value the
    #: engine compares with (ENG-29 item 2), e.g. {"activated": "activate"}.
    status_spellings: dict[str, str] = Field(default_factory=dict)
    order_status: OrderStatusValues = OrderStatusValues()
    #: The history-text map (ENG-30 point 5, replacing ENG-29 point 4): tracking_info
    #: entries are free text ("Delivered (Urban Vogue ...)", "Refund of ..."). An
    #: entry is the event whose words it opens with, as whole words, ignoring case;
    #: the longest match wins. An entry that matches nothing is reported, never guessed.
    tracking_stages: dict[str, TrackingStage] = Field(default_factory=lambda: dict(TRACKING_STAGES))
    #: Flagged, never actioned (ENG-21, X-21).
    exemptions: list[AccountEntry] = Field(default_factory=list)
    #: Left out of learning, measurement and fraud; the accounts internal mode serves.
    test_accounts: list[AccountEntry] = Field(default_factory=list)

    @field_validator("status_spellings", "tracking_stages")
    @classmethod
    def _lower_keys(cls, v: dict[str, str]) -> dict[str, str]:
        """Keys are compared ignoring case and surrounding spaces."""
        return {k.strip().lower(): (val.strip().lower() if isinstance(val, str) else val) for k, val in v.items()}


# --- the whole file -----------------------------------------------------------------


class Tunables(_Section):
    """The settings file, validated. Defaults are the Settings sheet's values."""

    #: SD-07: the file is versioned. Every change needs a new version, and the
    #: version travels on every served list (config_version, policy_id).
    config_version: str = "0"
    #: ENG-02 item 4: who made the change, recorded in ml_config_changes.
    changed_by: str = "Settings sheet defaults"

    serving: Serving = Serving()
    slots: Slots = Slots()
    events: Events = Events()
    filters: Filters = Filters()
    interest: Interest = Interest()
    retrieval: Retrieval = Retrieval()
    ranking: Ranking = Ranking()
    product: Product = Product()
    opportunity: Opportunity = Opportunity()
    promoter: Promoter = Promoter()
    commerce: Commerce = Commerce()
    fraud: Fraud = Fraud()
    lists: Lists = Lists()
    comparison: Comparison = Comparison()

    @field_validator("config_version", "changed_by")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("config_version and changed_by must not be blank")
        return v.strip()

    # --- views -----------------------------------------------------------------

    def values(self) -> dict[str, Any]:
        """Every tunable as a flat {"section.key": value} map, without the header."""
        flat: dict[str, Any] = {}

        def walk(prefix: str, value: Any) -> None:
            if isinstance(value, dict):
                for key, inner in value.items():
                    walk(f"{prefix}.{key}" if prefix else key, inner)
            else:
                flat[prefix] = value

        body = self.model_dump(exclude={"config_version", "changed_by"})
        walk("", body)
        return flat

    def with_changes(self, changes: dict[str, Any]) -> Tunables:
        """A validated copy with dotted keys changed, e.g. {"interest.half_life_days": 60}."""
        data = self.model_dump()
        for dotted, value in changes.items():
            node = data
            *parents, leaf = dotted.split(".")
            for part in parents:
                node = node[part]
            if leaf not in node:
                raise KeyError(f"no setting called {dotted!r}")
            node[leaf] = value
        return Tunables.model_validate(data)

    def m1(self) -> dict[str, Any]:
        """What the M1 methods read, keyed as they read it (P-02 ... P-27).

        The interest methods predate the Settings sheet and read a reference-keyed
        map. This builds that map from the sheet's values, with every ENG-10
        weight (view, click, like, save, share, comment, add to cart, purchase,
        business follow, and Not interested / Hide).
        """
        weights = self.interest.weights
        return {
            "P-02": self.events.qualified_view_seconds,
            "P-04": self.interest.half_life_days,
            "P-05": dict(self.interest.per_category_half_life_days),
            "P-06": {
                "view": weights.qualified_view,
                "click": weights.click,
                "cart": weights.add_to_cart,
                "purchase": weights.purchase,
                # No weight on the Settings sheet: search events are deferred
                # (E11), so a search contributes nothing.
                "search": 0.0,
                "like": weights.like,
                "save": weights.save,
                "share": weights.share,
                "comment": weights.comment,
                "business_follow": weights.business_follow,
                "feedback": weights.not_interested_or_hide,
            },
            "P-07": weights.not_interested_or_hide,
            "P-08": self.interest.stale_after_hours,
            "P-09": self.interest.refresh_cadence,
            "P-10": list(self.interest.window_bounds_days),
            "P-11": list(self.interest.window_weights),
            "P-25": self.interest.declared_floor,
            "P-26": self.interest.declared_floor_decays,
            "P-27": self.interest.popularity_window_days,
        }
