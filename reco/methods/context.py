"""What a scoring method is given.

A method does no I/O. Everything it needs arrives in its two arguments -- the
events, and this. That is not a style preference: a method that reads a database
cannot be replayed, cannot be compared against another method on identical
inputs, and behaves differently depending on where it runs.

So the caller does the reading and hands the result over. `ScoringContext` is the
whole of what a method may see.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ScoringContext(BaseModel):
    """The second argument to every method on this surface.

    Frozen, so a method cannot mutate what it was given and quietly change the
    inputs of the method that runs after it on the same data.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    #: Every DS-007 parameter, keyed by reference -- "P-04", "P-06" and so on.
    #: Keyed by reference rather than by name so a method's source says which
    #: parameter it is reading, and a reader can look it up in the list.
    tunables: dict[str, Any]

    #: The categories this user chose at signup. NOT events: they carry no
    #: timestamp, contribute a constant floor (P-25), and must never reach the
    #: event stream, where the decay term would consume them.
    declared_interests: list[str] = Field(default_factory=list)

    #: order_id -> when the order was CREATED. A reversal is aged from this, not
    #: from the cancellation. A cancellation is always more recent than the order
    #: it cancels, so it decays less, so it is always larger -- aged from the
    #: cancellation the reversal removes more than the purchase ever added.
    order_created_at: dict[str, datetime] = Field(default_factory=dict)

    #: The instant the score is computed as of. Injected rather than read from
    #: the clock so a run is reproducible: the generated dataset pins one, and
    #: the expected scores only reproduce when the engine decays from it.
    now: datetime

    #: Whether the decay term applies at all.
    #:
    #: NOT a DS-007 parameter, and deliberately not in `tunables`. P-04's
    #: permitted range is 7 to 180 days and that range is a hard bound -- a value
    #: outside it is a specification change, not a configuration change. "Half
    #: life set to infinity" therefore cannot be expressed as a P-04 value, so
    #: switching decay off is its own flag rather than an out-of-range number.
    #:
    #: With it False every decay factor is exactly 1 and the score reduces to a
    #: plain weighted sum, which is what demonstration step 4 puts beside the
    #: decayed one.
    decay_enabled: bool = True

    @field_validator("now")
    @classmethod
    def _now_is_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("now must be timezone-aware")
        return v.astimezone(timezone.utc)

    @field_validator("order_created_at")
    @classmethod
    def _orders_are_aware(cls, v: dict[str, datetime]) -> dict[str, datetime]:
        return {
            k: (t if t.tzinfo else t.replace(tzinfo=timezone.utc))
            for k, t in v.items()
        }

    # --- convenience readers, so a method never indexes a raw dict ----------

    @property
    def half_life_days(self) -> float:
        """P-04."""
        return float(self.tunables["P-04"])

    def half_life_for(self, category: str) -> float:
        """P-05 if this category has an override, else P-04.

        Launch value for P-05 is none, so this is P-04 for every category today.
        Honoured anyway: a parameter the engine ignores is a parameter that is
        not really configuration.

        With decay switched off this is infinite, which makes 2**(-age/H) exactly
        1 for every age. Expressing "no decay" as an infinite half-life rather
        than as a branch keeps one formula in the method: there is no second code
        path that could drift from the first.
        """
        if not self.decay_enabled:
            return math.inf
        overrides = self.tunables.get("P-05") or {}
        return float(overrides.get(category, self.half_life_days))

    @property
    def event_weights(self) -> dict[str, float]:
        """P-06, keyed view / click / cart / purchase / search."""
        return self.tunables["P-06"]

    @property
    def window_boundaries(self) -> list[int]:
        """P-10. Three ascending inclusive upper bounds, in days."""
        return list(self.tunables["P-10"])

    @property
    def window_weights(self) -> list[float]:
        """P-11. One per window, each 0-1, summing to 1.

        Settings validates the sum at load, so a method never has to.
        """
        return list(self.tunables["P-11"])

    @property
    def qualified_view_seconds(self) -> float:
        """P-02."""
        return float(self.tunables["P-02"])

    @property
    def declared_floor(self) -> float:
        """P-25."""
        return float(self.tunables["P-25"])

    @property
    def declared_floor_decays(self) -> bool:
        """P-26. Launch value No."""
        return bool(self.tunables["P-26"])
