"""The service's environment settings: connections, environment, data profile.

Tunable values -- weights, windows, thresholds, every value on the Build List's
Settings sheet -- are NOT here. They live in one versioned settings file
(settings/engine.toml), parsed by reco.config.tunables and kept in force by
reco.config.live (SD-07, SD-09, ENG-02). This module holds what the server
environment provides: connection strings, database names, which environment
this is, and the data profile (SD-08).

No configuration is read from the database.
"""

from __future__ import annotations

import os

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

#: ENG-01 item 2 (Build List v1.3): every collection the engine database holds,
#: all prefixed ml_ (SD-18). The build list names these sixteen and no others.
ENGINE_COLLECTIONS: tuple[str, ...] = (
    "ml_events",  # copies of platform events and served lists, and the engine's own E1
    "ml_orders",  # copies of orders, with order_status, tracking_info and status history
    "ml_sync_state",  # the engine sync's checkpoint and lag per source collection
    "ml_item_state",  # current eligibility state of posts, accounts and products (ENG-27)
    "ml_deletions",  # accounts confirmed deleted, and when their data was purged (ENG-28)
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

#: ENG-03: the platform collections the engine reads, by record kind. Read-only,
#: through reco.platform. These are exactly DB-02's read-access list (Build List
#: v1.3, Waits sheet; DS-017 v2.5 section 7). There is no event source switch.
PLATFORM_COLLECTIONS: dict[str, str] = {
    "user": "users",
    "business": "businessregisters",
    "post": "posts",
    "postevent": "postevents",
    "follow": "follows",
    "follower": "followers",  # blocks: status blocked, either direction (X-19, ENG-08)
    "order": "orders",
    "cart_line": "carts",
    "product": "products",
    "variant": "productvariants",
    "category": "categories",
    "served_list": "recommendationrequests",
    "serve_log": "rec_serve_log",  # SOCO_BE's serve log (APP-15, ENG-29)
}

#: ENG-03 "Ignored" (v1.3): platform data the engine must not read, and the only
#: place each exception is allowed. users.addNew_Interest: never. users.interestScores
#: (the delivered score): only as the old score in the fallback ladder.
#: feedScore: only SOCO_BE's own fallback ordering, never the engine.
IGNORED_PLATFORM_DATA: dict[str, str] = {
    "addNew_Interest": "never",
    "interestScores": "reco/fallback only",
    "feedScore": "never (SOCO_BE's fallback ordering only)",
}


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


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return default if raw is None or raw == "" else float(raw)


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

    # --- Settings file ---------------------------------------------------------
    # ENG-02 / SD-07: every tunable value, versioned. Relative to the repo root.
    settings_file: str = "settings/engine.toml"

    # --- Tokens (SD-08: server environment only, never a file in production) -
    # DS-017 v2.5 section 3, AS-04: SOCO_BE sends Authorization: Bearer
    # <INGEST_TOKEN> on POST /v1/recommendations (the name is kept for the
    # serving token; POST /v1/events is retired). repr=False, so
    # it never appears in a log line, error page or test header. Empty means no
    # token is configured, and every call is refused.
    ingest_token: str = Field(default="", repr=False)

    # --- Service -------------------------------------------------------------
    log_level: str = "INFO"

    # --- Validation ----------------------------------------------------------

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
            settings_file=_env_str("SETTINGS_FILE", "settings/engine.toml"),
            ingest_token=_env_str("INGEST_TOKEN", ""),
            log_level=_env_str("LOG_LEVEL", "INFO"),
        )


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
