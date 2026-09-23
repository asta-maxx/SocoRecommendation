"""One settings object for the whole service.

Two rules, both from S4/S5 and both enforced here rather than by convention:

1. No configuration is read from the database. A method that behaves differently
   depending on where it runs cannot be evaluated.
2. Every tunable reaches a scoring method through the context argument, never as
   a module constant. A method that hard-codes one fails the contract test.

Parameter values are DS-007 v1.1 (10 September 2026), which is the authority.
v1.0 is superseded: P-25/P-26/P-27 are new, the declared-interest floor moved out
of P-06, the purchase weight is restated at order creation, and P-07 is rescoped
to hide/report/skip. Do not build from a v1.0 copy.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

#: ENG-01 / SD-04: the three environments. Each has its own engine database.
ENGINE_ENVIRONMENTS: tuple[str, ...] = ("dev", "test", "production")

#: ENGINE_ENV as the server itself set it, read before any .env file is loaded.
#:
#: SD-08: passwords and tokens live only in server environment settings, never in
#: a file. A .env file is a convenience for dev and test, so it is not read at all
#: when the server says production -- and a production setting that could only
#: have come from a .env file is refused in Settings.from_env().
_SERVER_ENGINE_ENV = os.environ.get("ENGINE_ENV", "").strip().lower()
if _SERVER_ENGINE_ENV != "production":
    load_dotenv()

#: ENG-01 item 2: every collection the engine database holds. All prefixed ml_
#: (SD-18). The build list names these twelve and no others.
ENGINE_COLLECTIONS: tuple[str, ...] = (
    "ml_events",
    "ml_user_interest_scores",
    "ml_product_scores",
    "ml_promoter_scores",
    "ml_promoter_scores_monthly",
    "ml_opportunity_scores",
    "ml_user_candidates",
    "ml_fraud_flags",
    "ml_fraud_cases",
    "ml_job_runs",
    "ml_config_changes",
    "ml_measurements",
)


#: Every collection each profile selects. The one place in the service where a
#: collection name is written down.
#:
#: FOUR sources, not two. Method A reads the declared floor from the user record
#: and ages a purchase reversal from the order's creation timestamp, so the user
#: and order sources have to move with the profile as well. Naming only the
#: event source and the score target leaves the demo unable to read the floor
#: without a special case -- and a special case built to make a demonstration
#: work is a finding about the build, not a shortcut.
PROFILE_COLLECTIONS: dict[str, dict[str, str]] = {
    "live": {
        "events": "postevents",
        "posts": "posts",
        # `users`, not `registers`. The specification refers to this as
        # registerModel.interest, but no `registers` collection exists on the
        # cluster -- the model is backed by `users`, where all 13 documents carry
        # an `interest` array. Reading `registers` returns nothing without
        # raising, so the floor would silently be zero for every user.
        "users": "users",
        "orders": "orders",
        "scores": "ml_user_interest_scores",
    },
    "demo": {
        # Generated data lives under ml_ throughout: the generator holds the
        # ml_-scoped credential and cannot write to an application collection.
        #
        # There is no ml_demo_posts. The generator emits three collections, and a
        # demo event carries its categories on the row, so nothing is ever joined
        # -- pointing at a posts collection here would name one that does not
        # exist, and a read of it would return nothing without raising.
        "events": "ml_demo_events",
        "posts": "",
        "users": "ml_demo_users",
        "orders": "ml_demo_orders",
        "scores": "ml_user_interest_scores_demo",
    },
}

#: Which sources each profile's events need joining against to resolve a
#: category. See reco.platform.readers -- swapping a collection name does not make
#: two differently shaped documents compatible.
PROFILE_EVENT_SHAPE: dict[str, str] = {
    "live": "postevent",
    "demo": "flat",
}


def _hosts_of(uri: str) -> tuple[str, ...]:
    """The server hosts a connection string addresses, without its credentials.

    Works for mongodb:// and mongodb+srv:// alike: the scheme, the user:password
    part and anything after the host list are dropped, and the ports kept.
    """
    authority = uri.split("//", 1)[-1]
    authority = authority.split("/", 1)[0].split("?", 1)[0]
    authority = authority.rsplit("@", 1)[-1]
    return tuple(sorted(host.strip().lower() for host in authority.split(",") if host))


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return default if raw is None or raw == "" else int(raw)


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return default if raw is None or raw == "" else float(raw)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_floats(key: str, default: list[float]) -> list[float]:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return list(default)
    return [float(part) for part in raw.split(",")]


def _env_ints(key: str, default: list[int]) -> list[int]:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return list(default)
    return [int(part) for part in raw.split(",")]


class EventWeights(BaseModel):
    """P-06. Each weight 0-50.

    The declared-interest floor is NOT in this table. It is P-25 and is held
    separately, because it is a statement of preference rather than an action and
    must never reach the event stream where the decay term would consume it.
    """

    model_config = {"frozen": True}

    view: float = 2.0
    click: float = 5.0
    cart: float = 10.0
    purchase: float = 20.0
    search: float = 3.0

    @field_validator("view", "click", "cart", "purchase", "search")
    @classmethod
    def _in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 50.0:
            raise ValueError(f"P-06 event weight must be within 0-50, got {v}")
        return v


class Settings(BaseModel):
    """The single settings object. Built once, passed down."""

    model_config = {"frozen": True}

    # --- Environment ---------------------------------------------------------
    # ENG-01 / SD-04: dev, test or production. Each has its own engine database.
    engine_env: str = "dev"

    # --- MongoDB -------------------------------------------------------------
    # app = the platform database, read only (SD-06, DB-02).
    # ml  = the engine's own database (AS-09). Never the platform database.
    # repr=False on both URIs. A connection string carries a password, and a
    # Settings object appears in pytest fixture headers, FastAPI error pages and
    # any log line that formats it -- which is how a live credential ends up in
    # a transcript or a CI log. Read them through the attribute; never print one.
    app_mongo_uri: str = Field(
        default="mongodb://localhost:27017/?readPreference=secondaryPreferred",
        repr=False,
    )
    app_mongo_db: str = "soco"
    ml_mongo_uri: str = Field(default="mongodb://localhost:27017", repr=False)
    ml_mongo_db: str = "soco_engine_dev"

    #: How long to wait for a server before giving up. Not a DS-007 parameter --
    #: an operational bound, so an unreachable cluster fails at startup with a
    #: message rather than hanging.
    mongo_timeout_seconds: float = 10.0

    # --- Model identity ------------------------------------------------------
    model_version: str = "1.0.0"

    # --- Category vocabulary -------------------------------------------------
    # Where the exported CANONICAL_CATEGORIES and LEGACY_LABEL_MAP are read from.
    # A path, not a list: the vocabulary is loaded, never written down in Python,
    # because a retyped copy is a fourth vocabulary alongside the three that
    # already exist. Produced by scripts/export_categories.py.
    category_vocabulary_path: str = "reco/platform/categories.json"

    # --- Source and target collections ---------------------------------------
    # No collection name is a constant anywhere else in this service. One config
    # value moves the whole pipeline between demo and live data, which is what
    # removes the need for a demo branch: the code that runs in the demonstration
    # is the same code, reading and writing different collections.
    #
    #   live  reads postevents / posts / registers / orders
    #         writes ml_user_interest_scores
    #   demo  reads ml_demo_events / ml_demo_posts / ml_demo_users /
    #         ml_demo_orders, all generated by scripts/generate_demo_data.py into
    #         the ml_ namespace because the generator cannot write to an
    #         application collection
    #         writes ml_user_interest_scores_demo
    #
    # data_profile sets them together, so the incoherent pairing -- demo events
    # scored into the live store -- cannot be reached by setting one variable and
    # forgetting another. Any single collection may still be named explicitly.
    data_profile: str = "live"
    events_collection: str = ""
    posts_collection: str = ""
    users_collection: str = ""
    orders_collection: str = ""
    scores_collection: str = ""

    # How this profile's event documents carry their category. Defaulted from the
    # profile, but a real field rather than a derived property: a source's name
    # and a source's shape are two independent facts, and pinning them together
    # is what made "just swap the collection name" look sufficient.
    #
    #   flat       the categories array is on the event row itself
    #   postevent  the row carries a post_id and the category resolves through
    #              the post -- a join, not a field
    event_shape: str = ""

    # --- DS-007 v1.1 tunables ------------------------------------------------
    # P-02 qualified view threshold, seconds. Range 1-10.
    qualified_view_threshold_seconds: float = 3.0

    # P-04 decay half life, days. Range 7-180. Base 2, so an event exactly this
    # old contributes half its weight.
    decay_half_life_days: float = 30.0

    # P-05 per-category half life override. Launch value: none. Keys are category
    # keys as produced by toCategoryKey(); values follow the P-04 range.
    per_category_half_life_days: dict[str, float] = Field(default_factory=dict)

    # P-06 event weights.
    event_weights: EventWeights = Field(default_factory=EventWeights)

    # P-07 negative FEEDBACK weight -- hide, report, skip. Range -20 to 0.
    # This does NOT govern the purchase reversal. Multiplying the reversal by
    # this zeroes it at launch, and the failure is silent.
    negative_feedback_weight: float = 0.0

    # P-08 score staleness age, hours. Range 1-72. Rung 4 of the fallback ladder.
    score_staleness_hours: float = 24.0

    # P-09 refresh cadence. hourly | daily | weekly.
    refresh_cadence: str = "daily"

    # P-10 window boundaries, days. Three ascending values within 1-365.
    # The windows they describe are DISJOINT: 0-7, 8-30, 31-90, and nothing
    # beyond the last boundary. Nested windows would triple-count recent events.
    window_boundaries_days: list[int] = Field(default_factory=lambda: [7, 30, 90])

    # P-11 per-window weights. Each 0-1, summing to 1.
    window_weights: list[float] = Field(default_factory=lambda: [0.5, 0.3, 0.2])

    # P-22 variant traffic split, percentage to the incumbent. Range 50-95.
    # The M1 comparison does not depend on this: both methods are computed for
    # every user. The split exists so a method can be switched, not measured.
    variant_split_incumbent: int = 90

    # P-25 declared interest floor. Range 0-50. Read from registerModel.interest,
    # never from interestScores -- addInterest seeds that map with 10 per declared
    # category and event tracking increments the same map, so the two are fused
    # and cannot be decomposed.
    declared_interest_floor: float = 10.0

    # P-26 whether the declared interest decays. Launch value: No.
    declared_interest_decays: bool = False

    # P-27 cold start popularity window, days. Range 7-365.
    cold_start_popularity_window_days: int = 30

    # --- Service -------------------------------------------------------------
    log_level: str = "INFO"

    # --- Validation ----------------------------------------------------------

    @field_validator("qualified_view_threshold_seconds")
    @classmethod
    def _p02(cls, v: float) -> float:
        if not 1.0 <= v <= 10.0:
            raise ValueError(f"P-02 must be within 1-10 seconds, got {v}")
        return v

    @field_validator("decay_half_life_days")
    @classmethod
    def _p04(cls, v: float) -> float:
        if not 7.0 <= v <= 180.0:
            raise ValueError(f"P-04 must be within 7-180 days, got {v}")
        return v

    @field_validator("per_category_half_life_days")
    @classmethod
    def _p05(cls, v: dict[str, float]) -> dict[str, float]:
        for category, half_life in v.items():
            if not 7.0 <= half_life <= 180.0:
                raise ValueError(
                    f"P-05 override for {category!r} must be within 7-180 days, "
                    f"got {half_life}"
                )
        return v

    @field_validator("negative_feedback_weight")
    @classmethod
    def _p07(cls, v: float) -> float:
        if not -20.0 <= v <= 0.0:
            raise ValueError(f"P-07 must be within -20 to 0, got {v}")
        return v

    @field_validator("score_staleness_hours")
    @classmethod
    def _p08(cls, v: float) -> float:
        if not 1.0 <= v <= 72.0:
            raise ValueError(f"P-08 must be within 1-72 hours, got {v}")
        return v

    @field_validator("refresh_cadence")
    @classmethod
    def _p09(cls, v: str) -> str:
        allowed = {"hourly", "daily", "weekly"}
        if v not in allowed:
            raise ValueError(f"P-09 must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("window_boundaries_days")
    @classmethod
    def _p10(cls, v: list[int]) -> list[int]:
        if len(v) != 3:
            raise ValueError(f"P-10 needs exactly three boundaries, got {v}")
        if not all(1 <= b <= 365 for b in v):
            raise ValueError(f"P-10 boundaries must each be within 1-365, got {v}")
        if not v[0] < v[1] < v[2]:
            raise ValueError(f"P-10 boundaries must be strictly ascending, got {v}")
        return v

    @field_validator("window_weights")
    @classmethod
    def _p11(cls, v: list[float]) -> list[float]:
        if len(v) != 3:
            raise ValueError(f"P-11 needs exactly three weights, got {v}")
        if not all(0.0 <= w <= 1.0 for w in v):
            raise ValueError(f"P-11 weights must each be within 0-1, got {v}")
        if abs(sum(v) - 1.0) > 1e-9:
            raise ValueError(f"P-11 weights must sum to 1, got {sum(v)}")
        return v

    @field_validator("variant_split_incumbent")
    @classmethod
    def _p22(cls, v: int) -> int:
        if not 50 <= v <= 95:
            raise ValueError(f"P-22 incumbent share must be within 50-95, got {v}")
        return v

    @field_validator("declared_interest_floor")
    @classmethod
    def _p25(cls, v: float) -> float:
        if not 0.0 <= v <= 50.0:
            raise ValueError(f"P-25 must be within 0-50, got {v}")
        return v

    @field_validator("cold_start_popularity_window_days")
    @classmethod
    def _p27(cls, v: int) -> int:
        if not 7 <= v <= 365:
            raise ValueError(f"P-27 must be within 7-365 days, got {v}")
        return v

    @field_validator("engine_env")
    @classmethod
    def _engine_env(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ENGINE_ENVIRONMENTS:
            raise ValueError(
                f"engine_env must be one of {list(ENGINE_ENVIRONMENTS)}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _engine_db_is_not_the_platform_db(self) -> Settings:
        """AS-09 / SD-06: the engine writes only to its own database.

        The same database on the same servers would put every ml_ write inside
        the platform database. Names are compared ignoring case: two names that
        differ only in case are one database on a case-insensitive server, and
        Atlas refuses to create both.
        """
        same_servers = _hosts_of(self.app_mongo_uri) == _hosts_of(self.ml_mongo_uri)
        same_name = self.app_mongo_db.lower() == self.ml_mongo_db.lower()
        if same_servers and same_name:
            raise ValueError(
                f"the engine database ({self.ml_mongo_db!r}) is the platform "
                f"database. The engine has its own database in every environment "
                f"(AS-09, SD-06): set ML_MONGO_DB to a different name."
            )
        return self

    @field_validator("model_version")
    @classmethod
    def _model_version(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "model_version must not be blank -- it is part of the score key"
            )
        return v.strip()

    @field_validator("data_profile")
    @classmethod
    def _data_profile(cls, v: str) -> str:
        if v not in PROFILE_COLLECTIONS:
            raise ValueError(
                f"data_profile must be one of {sorted(PROFILE_COLLECTIONS)}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _resolve_collections(self) -> Settings:
        """Fill in whichever collection names the profile is responsible for.

        An explicit name always wins, so a one-off run can read demo events and
        write somewhere else on purpose -- but it has to be said out loud.
        """
        defaults = PROFILE_COLLECTIONS[self.data_profile]
        for key, attribute in (
            ("events", "events_collection"),
            ("users", "users_collection"),
            ("orders", "orders_collection"),
            ("scores", "scores_collection"),
        ):
            if not getattr(self, attribute):
                object.__setattr__(self, attribute, defaults[key])
        # posts may legitimately be empty: the demo profile has no posts
        # collection, because a generated event carries its own categories.
        if self.posts_collection == "" and defaults["posts"]:
            object.__setattr__(self, "posts_collection", defaults["posts"])
        if not self.event_shape:
            object.__setattr__(self, "event_shape", PROFILE_EVENT_SHAPE[self.data_profile])
        return self

    @field_validator("event_shape")
    @classmethod
    def _event_shape(cls, v: str) -> str:
        if v and v not in set(PROFILE_EVENT_SHAPE.values()):
            raise ValueError(
                f"event_shape must be one of "
                f"{sorted(set(PROFILE_EVENT_SHAPE.values()))}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _scores_target_is_in_the_ml_namespace(self) -> Settings:
        """The write target must be an ml_ collection under every profile.

        writers.py refuses a non-ml_ name at the point of writing. Catching it
        here as well means a bad configuration fails at startup rather than at
        the first write of a refresh run, which could be hours later.
        """
        if not self.scores_collection.startswith("ml_"):
            raise ValueError(
                f"scores_collection must be in the ml_ namespace, got "
                f"{self.scores_collection!r} -- scores never go into an "
                f"application collection"
            )
        return self

    @model_validator(mode="after")
    def _windows_match_weights(self) -> Settings:
        if len(self.window_boundaries_days) != len(self.window_weights):
            raise ValueError(
                "P-10 boundaries and P-11 weights must describe the same "
                "number of windows"
            )
        return self

    # --- Construction --------------------------------------------------------

    @classmethod
    def from_env(cls) -> Settings:
        """Build from environment, falling back to the DS-007 v1.1 launch values."""
        engine_env = _env_str("ENGINE_ENV", "dev").strip().lower()
        _require_production_env_from_server(engine_env, _SERVER_ENGINE_ENV)
        return cls(
            engine_env=engine_env,
            app_mongo_uri=_env_str(
                "APP_MONGO_URI",
                "mongodb://localhost:27017/?readPreference=secondaryPreferred",
            ),
            app_mongo_db=_env_str("APP_MONGO_DB", "soco"),
            ml_mongo_uri=_env_str("ML_MONGO_URI", "mongodb://localhost:27017"),
            # Unset, each environment gets its own name, so two environments
            # never share an engine database by default.
            ml_mongo_db=_env_str("ML_MONGO_DB", f"soco_engine_{engine_env}"),
            mongo_timeout_seconds=_env_float("MONGO_TIMEOUT_SECONDS", 10.0),
            model_version=_env_str("MODEL_VERSION", "1.0.0"),
            category_vocabulary_path=_env_str(
                "CATEGORY_VOCABULARY_PATH", "reco/platform/categories.json"
            ),
            data_profile=_env_str("DATA_PROFILE", "live"),
            events_collection=_env_str("EVENTS_COLLECTION", ""),
            posts_collection=_env_str("POSTS_COLLECTION", ""),
            users_collection=_env_str("USERS_COLLECTION", ""),
            orders_collection=_env_str("ORDERS_COLLECTION", ""),
            scores_collection=_env_str("SCORES_COLLECTION", ""),
            event_shape=_env_str("EVENT_SHAPE", ""),
            qualified_view_threshold_seconds=_env_float(
                "P02_QUALIFIED_VIEW_SECONDS", 3.0
            ),
            decay_half_life_days=_env_float("P04_DECAY_HALF_LIFE_DAYS", 30.0),
            event_weights=EventWeights(
                view=_env_float("P06_WEIGHT_VIEW", 2.0),
                click=_env_float("P06_WEIGHT_CLICK", 5.0),
                cart=_env_float("P06_WEIGHT_CART", 10.0),
                purchase=_env_float("P06_WEIGHT_PURCHASE", 20.0),
                search=_env_float("P06_WEIGHT_SEARCH", 3.0),
            ),
            negative_feedback_weight=_env_float("P07_NEGATIVE_FEEDBACK_WEIGHT", 0.0),
            score_staleness_hours=_env_float("P08_STALENESS_HOURS", 24.0),
            refresh_cadence=_env_str("P09_REFRESH_CADENCE", "daily"),
            window_boundaries_days=_env_ints("P10_WINDOW_BOUNDARIES_DAYS", [7, 30, 90]),
            window_weights=_env_floats("P11_WINDOW_WEIGHTS", [0.5, 0.3, 0.2]),
            variant_split_incumbent=_env_int("P22_VARIANT_SPLIT_INCUMBENT", 90),
            declared_interest_floor=_env_float("P25_DECLARED_INTEREST_FLOOR", 10.0),
            declared_interest_decays=_env_bool("P26_DECLARED_INTEREST_DECAYS", False),
            cold_start_popularity_window_days=_env_int("P27_COLD_START_WINDOW_DAYS", 30),
            log_level=_env_str("LOG_LEVEL", "INFO"),
        )

    def tunables(self) -> dict[str, Any]:
        """The parameter surface a scoring method is allowed to see.

        Methods receive this through ctx.tunables. Connection strings and service
        settings are deliberately absent: a method performs no I/O.
        """
        return {
            "P-02": self.qualified_view_threshold_seconds,
            "P-04": self.decay_half_life_days,
            "P-05": dict(self.per_category_half_life_days),
            "P-06": self.event_weights.model_dump(),
            "P-07": self.negative_feedback_weight,
            "P-08": self.score_staleness_hours,
            "P-09": self.refresh_cadence,
            "P-10": list(self.window_boundaries_days),
            "P-11": list(self.window_weights),
            "P-22": self.variant_split_incumbent,
            "P-25": self.declared_interest_floor,
            "P-26": self.declared_interest_decays,
            "P-27": self.cold_start_popularity_window_days,
        }


def _require_production_env_from_server(engine_env: str, server_engine_env: str) -> None:
    """SD-08: production reads its settings from the server environment only.

    If ENGINE_ENV=production reached us but the server did not set it, it came
    from a .env file -- and so, very likely, did the credentials beside it.
    """
    if engine_env == "production" and server_engine_env != "production":
        raise RuntimeError(
            "ENGINE_ENV=production was read from a .env file. In production, "
            "passwords and tokens live only in server environment settings, never "
            "in a file (SD-08, ENG-01): set ENGINE_ENV and the connection strings "
            "in the server environment."
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide singleton. Built once, on first call."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings_cache() -> None:
    """Test seam. Not called in production paths."""
    global _settings
    _settings = None
