"""The score document. RE-02 / ST1 / ST2.

One document per user per category. Two forms of the value are stored for every
score:

  raw    the weighted sum. Unbounded, not comparable between users. Diagnostics.
  share  raw divided by the user's total raw across all categories. Sums to 1.
         This is what every downstream consumer reads.

Beyond the value, every score carries four metadata fields: method,
model_version, window and computed_at. They are NOT optional and their being
required is enforced here, in the model, rather than by convention. Without them
two methods writing to one store are indistinguishable, a stale score cannot be
detected, and no comparison between methods can be reconstructed afterwards.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# NOTE: no collection name is defined in this module, deliberately. The score
# collection is configuration -- see config.PROFILE_COLLECTIONS -- so that the
# demonstration and the live run are the same code reading and writing different
# collections, rather than two branches that have to be kept in step.


class Method(StrEnum):
    """The two methods that ship at launch.

    Both are built, both compute a score for every user. One serves; the other is
    computed alongside and serves nobody. They read identical inputs and identical
    weights -- the only difference is how they treat time.

    THESE STRINGS ARE A CONTRACT, NOT A LABEL. ml_demo_meta.json pins
    `decay_method_name` to "recency_decay" and run_data_checks.py matches it
    verbatim. Its own source carries the warning: an engine spelling the method
    anything else leaves checks 5 to 8 PENDING for ever, and the failure reads as
    a contract mismatch rather than as a scoring defect -- which is to say it
    looks like nothing is wrong.
    """

    RECENCY_DECAY = "recency_decay"
    TIME_WINDOWS = "time_windows"

    #: The same method with decay switched off, stored under its own name.
    #:
    #: Demonstration step 4 shows the two side by side, so both have to be in the
    #: store at once. They must NOT share a method value: the checks compare
    #: every row under `recency_decay` against the decay-on expectations, so
    #: decay-off rows written under that name are read as wrong answers rather
    #: than as a different question.
    #:
    #: The string is the one the display script expects on its
    #: --decay-off-method flag, and matching it is character-for-character.
    RECENCY_DECAY_NO_DECAY = "recency_decay_h_inf"


class Window(StrEnum):
    """The window a score was computed over.

    Method A's exponential decay has no hard cutoff, so it reads ALL. Method B
    discards anything older than its last boundary, so it reads that boundary.
    Stored as a plain string: it is metadata for reconstructing a comparison, not
    something the engine branches on.
    """

    ALL = "all"
    LAST_90_DAYS = "90d"


class InterestScore(BaseModel):
    """One user's score in one category, under one method and model version.

    Rejecting bad input at construction is the point of this class. A score that
    reaches the database missing its provenance can never be repaired, because
    nothing records what produced it.
    """

    model_config = {"extra": "forbid"}

    user_id: str
    category: str

    raw: float
    share: float
    event_count: int

    # --- the four metadata fields. No defaults, deliberately. ---------------
    method: Method
    model_version: str
    window: Window
    computed_at: datetime

    # --- ENG-07: the batch the row belongs to. None only for rows written
    # outside a job run (the M1 demo's loader and the store tests); a nightly
    # job always sets them. A request reads only the batch marked current.
    job_run_id: str | None = None
    config_version: str | None = None
    slot: Literal["interest"] = "interest"
    confidence: float | None = None  # the interest methods have none
    #: Kala, 16 Oct (ENG-09 2a): the user's qualified actions in the last 90 days, the
    #: same count the ladder makes (reco.store.writers.count_qualified_actions).
    qualified_actions: int | None = None
    data_window: dict[str, datetime | None] | None = None  # {"from": ..., "to": ...}

    @field_validator("user_id", "category", "model_version")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    # NOTE: the category is deliberately NOT validated beyond being non-blank.
    #
    # An earlier version of this model required toCategoryKey() shape -- lowercase
    # and no underscores. That was wrong, and it would have refused almost every
    # real score. The generated data is title case ("Fashion & Apparel"), and it
    # carries legacy and unmappable values on purpose: "home & decor",
    # "Casual Sneakers", "Fashion" and "fashion" all appear, because U06 and U08
    # exist to demonstrate mapping and dropping.
    #
    # The event contract is explicit: any string is allowed, and the engine maps
    # or drops -- it does not validate at read. The score map is keyed on whatever
    # string the source supplies. Constraining it here would also have created a
    # fourth category vocabulary alongside the three that already exist.

    @field_validator("raw")
    @classmethod
    def _raw_non_negative(cls, v: float) -> float:
        """A raw score cannot be negative.

        The one path that could produce one is a purchase reversal aged from the
        cancellation rather than from the original order, which decays less than
        the purchase it reverses and so is always larger. Aged correctly, the
        reversal exactly cancels. If this ever fires, that is the bug to look for.
        """
        if v < 0:
            raise ValueError(
                f"raw must not be negative, got {v} -- clamp at 0, store no share, "
                f"and log a coherence failure"
            )
        return v

    @field_validator("share")
    @classmethod
    def _share_in_unit_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"share must be within 0-1, got {v}")
        return v

    @field_validator("event_count")
    @classmethod
    def _event_count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"event_count must not be negative, got {v}")
        return v

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_aware_utc(cls, v: datetime) -> datetime:
        """A naive timestamp silently breaks the P-08 staleness check, because
        comparing it against an aware 'now' either raises or compares against the
        wrong instant depending on how it is handled downstream. Reject it here.
        """
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "computed_at must be timezone-aware -- a naive timestamp breaks "
                "the P-08 staleness check"
            )
        return v.astimezone(timezone.utc)

    def key(self) -> dict[str, str]:
        """The unique key this document is upserted on.

        Method and model_version are part of it so that two methods, and two
        generations of the same method, coexist as distinct documents rather than
        overwriting each other.
        """
        return {
            "user_id": self.user_id,
            "category": self.category,
            "method": str(self.method),
            "model_version": self.model_version,
            "job_run_id": self.job_run_id,
        }

    def to_document(self) -> dict:
        """The MongoDB representation. StrEnum values are written as plain strings
        so the collection stays readable to the Node backend and to mongosh.
        """
        return {
            "user_id": self.user_id,
            "category": self.category,
            "raw": self.raw,
            "share": self.share,
            "event_count": self.event_count,
            "method": str(self.method),
            "model_version": self.model_version,
            "window": str(self.window),
            "computed_at": self.computed_at,
            # ENG-07: what is scored (user_id, category), slot, method,
            # model_version, config_version, score, confidence, data window,
            # computed_at and job_run_id on every row. The score is the share.
            "score": self.share,
            "slot": self.slot,
            "confidence": self.confidence,
            "config_version": self.config_version,
            "data_window": self.data_window,
            "job_run_id": self.job_run_id,
        }

    @classmethod
    def from_document(cls, document: dict) -> InterestScore:
        """Rebuild from a stored document, dropping Mongo's _id.

        The same validators run, so a document that was written before a rule
        existed fails loudly on read rather than flowing on unnoticed.
        """
        fields = {k: v for k, v in document.items() if k not in ("_id", "score")}
        computed_at = fields.get("computed_at")
        if isinstance(computed_at, datetime) and computed_at.tzinfo is None:
            # PyMongo returns naive UTC datetimes unless the client is configured
            # with a tz_aware codec. store/connection.py sets tz_aware=True; this is a
            # safety net for documents arriving from anywhere else.
            fields["computed_at"] = computed_at.replace(tzinfo=timezone.utc)
        return cls(**fields)


class CoherenceFailure(BaseModel):
    """A raw score that went negative.

    A defect, not a state. It cannot occur once the purchase reversal is aged
    from the original order: a cancellation is always more recent than the order
    it cancels, so it decays less, so it is always larger -- aged from the
    cancellation the reversal overshoots and the raw goes below zero.

    The handling still has to exist, because data check 7 needs something to
    report against. Silently clamping and carrying on would leave the profile
    wrong with nothing in the logs to say so.
    """

    model_config = {"extra": "forbid"}

    user_id: str
    category: str
    observed_raw: float
    detected_at: datetime


def normalise_with_coherence(
    user_id: str,
    raws: dict[str, float],
) -> tuple[dict[str, float], dict[str, float], list[CoherenceFailure]]:
    """Turn a user's raw map into (clamped raws, shares, failures).

    Three rules, in this order:

    1. A negative raw is clamped to zero and recorded as a coherence failure.
    2. If ANY category failed, NO share is stored for that user -- the whole
       distribution is suspect, not just the one category, because every share
       is computed against a denominator the bad value contributed to.
    3. If the total raw is zero, no share is stored either. A uniform
       distribution is indistinguishable from a genuine even spread of interest
       and would hide that the user is unknown; the cold-start ladder answers
       instead.

    The raws are still returned in both cases: they are diagnostics, and they are
    what makes the failure explainable afterwards.
    """
    detected_at = utc_now()

    failures = [
        CoherenceFailure(
            user_id=user_id,
            category=category,
            observed_raw=raw,
            detected_at=detected_at,
        )
        for category, raw in raws.items()
        if raw < 0
    ]
    clamped = {category: max(raw, 0.0) for category, raw in raws.items()}

    if failures:
        logger.error(
            "coherence failure for user %s: %d categor%s with negative raw (%s). "
            "Clamped at 0 and storing no share. Check that the purchase reversal "
            "is aged from the original order's creation, not from the "
            "cancellation.",
            user_id,
            len(failures),
            "y" if len(failures) == 1 else "ies",
            ", ".join(f"{f.category}={f.observed_raw:.4f}" for f in failures),
        )
        return clamped, {}, failures

    return clamped, normalise_to_shares(clamped), []


def clip_to_shares(raws: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """Build List v1.3 ENG-10's order of calculation, after the weighted actions and
    the floor are added: clip each category at 0 ("so raw is never negative"), then
    share = raw / the user's total raw. A negative is legitimate here (Not
    interested and Hide are −5), so it is clipped, not treated as a fault. If every
    category comes to 0, no shares: the ladder (ENG-09) serves that user."""
    clipped = {category: max(raw, 0.0) for category, raw in raws.items()}
    return clipped, normalise_to_shares(clipped)


def normalise_to_shares(raws: dict[str, float]) -> dict[str, float]:
    """Turn a user's raw category map into shares summing to 1.

    Returns an EMPTY map when the total raw is zero. It does not fabricate a
    uniform distribution: a uniform spread is indistinguishable from a genuine
    even spread of interest and would hide that the user is unknown. An empty
    result is the signal for the cold-start ladder to take over.
    """
    total = sum(raws.values())
    if total <= 0:
        return {}
    return {category: raw / total for category, raw in raws.items()}


def utc_now() -> datetime:
    """Timezone-aware now. The only clock this service reads."""
    return datetime.now(timezone.utc)


class ScoreBatch(BaseModel):
    """A whole user's category map, written in one call.

    The refresh path writes per user, not per category (ST8). Validating the set
    together is what makes the share-sum check possible at all -- it is not a
    property any single document has.
    """

    model_config = {"extra": "forbid"}

    user_id: str
    scores: list[InterestScore] = Field(min_length=1)

    @field_validator("scores")
    @classmethod
    def _coherent(cls, scores: list[InterestScore]) -> list[InterestScore]:
        if len({s.user_id for s in scores}) > 1:
            raise ValueError("a batch must belong to exactly one user")
        if len({(s.method, s.model_version, s.window) for s in scores}) > 1:
            raise ValueError(
                "a batch must be one method, one model_version and one window -- "
                "mixing them makes the shares meaningless, since they were "
                "normalised over different totals"
            )
        categories = [s.category for s in scores]
        if len(categories) != len(set(categories)):
            raise ValueError("a batch must not repeat a category")
        total_share = sum(s.share for s in scores)
        if abs(total_share - 1.0) > 1e-6:
            raise ValueError(
                f"shares across a user's categories must sum to 1, got {total_share}"
            )
        return scores

    @model_validator(mode="after")
    def _batch_user_matches_scores(self) -> ScoreBatch:
        for score in self.scores:
            if score.user_id != self.user_id:
                raise ValueError(
                    f"batch is for user {self.user_id!r} but carries a score for "
                    f"{score.user_id!r}"
                )
        return self
