"""What the read path returns: an interest profile and the ladder rung behind it. ENG-09.

A profile is never a bare list of categories. It always says which rung of the
fallback ladder produced it, and which method and version were involved.

That is the whole point. A guess and a real profile must not look the same to
whoever is building the screen: rung 3 is platform popularity, identical for
every user, and an app that cannot tell might put "Recommended for you" above it.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel, Field, field_validator


class Rung(IntEnum):
    """The fallback ladder (Build List ENG-09, SD-23), checked in order. First match wins.

    Every user, every request, gets one of these -- nobody is ever served
    nothing.
    """

    #: At least 5 qualified actions in the last 90 days, and a score computed in
    #: the last 48 hours that passes its checks.
    PERSONALISED = 1

    #: Fewer than 5 qualified actions, with interests declared at sign-up: the
    #: floor for those interests plus whatever actions they have.
    DECLARED_ONLY = 2

    #: Fewer than 5 qualified actions and no declared interests: platform-wide
    #: category popularity (qualified views) over the last 30 days. NOT personalised.
    POPULARITY = 3

    #: The stored score is older than 48 hours, or fails its checks (or, with 5 or
    #: more actions, there is none): the old delivered interest score.
    STALE = 4

    #: The engine's own store cannot be read: the old delivered interest score.
    UNAVAILABLE = 5


#: What each rung means, in words the caller can show or log.
RUNG_DESCRIPTION = {
    Rung.PERSONALISED: "personalised score from this user's activity",
    # Specific to this user -- they chose these -- but based on nothing they have
    # done. `personalised` is True here; what it lacks is behaviour, not
    # relevance to the individual.
    Rung.DECLARED_ONLY: "this user's declared interests, no activity yet",
    Rung.POPULARITY: "platform popularity, not personalised",
    Rung.STALE: "stored score stale or failed its checks; the old delivered score",
    Rung.UNAVAILABLE: "engine store unreadable; the old delivered score",
}

#: Rungs 4 and 5 serve the old delivered score. Where none exists, both fall
#: through to rung 3, each logged separately: a stale score is a refresh problem,
#: an unreadable store is a serving problem, and they need different fixes.
FALLS_THROUGH_TO_POPULARITY = {Rung.STALE, Rung.UNAVAILABLE}

#: Rungs a new user lands on with the engine working normally (cold start). Rungs 4
#: and 5 are operational fallback. ENG-24 counts the two apart.
COLD_START = {Rung.DECLARED_ONLY, Rung.POPULARITY}


class CategoryShare(BaseModel):
    """One category and its share of the user's interest."""

    model_config = {"frozen": True, "extra": "forbid"}

    category: str
    share: float
    raw: float | None = None
    event_count: int | None = None

    @field_validator("share")
    @classmethod
    def _share_in_unit_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"share must be within 0-1, got {v}")
        return v


class Profile(BaseModel):
    """A user's interest profile, and where it came from.

    `personalised` is a separate field rather than something the caller infers
    from the rung number, so a screen can ask the question directly instead of
    encoding the ladder in its own logic.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    user_id: str
    categories: list[CategoryShare]

    #: Which rung served this. Always present, even at rung 1.
    rung: Rung
    rung_description: str

    #: False at rung 3 -- that answer is the same for every user.
    personalised: bool

    #: Task 20. The stamp travels with every response, and the same stamp goes on
    #: the impression event when that exists, so a served result can be traced
    #: back to the configuration that produced it.
    method: str | None = None
    model_version: str
    computed_at: datetime | None = None

    #: Set when rung 4 or 5 fell through to rung 3. Carries the rung that was
    #: reached first, so the reason is not lost when the answer changes.
    fell_through_from: Rung | None = None

    #: The window popularity was computed over, at rung 3.
    popularity_window_days: int | None = None

    @field_validator("categories")
    @classmethod
    def _shares_are_coherent(cls, v: list[CategoryShare]) -> list[CategoryShare]:
        if not v:
            return v
        total = sum(c.share for c in v)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"shares must sum to 1, got {total}")
        names = [c.category for c in v]
        if len(names) != len(set(names)):
            raise ValueError("a profile must not repeat a category")
        return v

    @property
    def fallback_step(self) -> str | None:
        """What the response and the E1 record name as the fallback step (DS-017 4.2:
        "string or null"; null when none was needed, i.e. rung 1).

        rung_2, rung_3, rung_4, rung_5; rung_4_to_3 / rung_5_to_3 where no delivered
        score existed; and _empty when rung 3 had nothing either, so the list is
        eligible posts newest first (ENG-09 "rung 3 empty")."""
        if self.rung is Rung.PERSONALISED:
            return None
        step = f"rung_{int(self.fell_through_from)}_to_3" if self.fell_through_from else f"rung_{int(self.rung)}"
        return step + "_empty" if self.rung is Rung.POPULARITY and not self.categories else step

    @property
    def cold_start(self) -> bool:
        """Rung 2 or 3 reached directly: a new user, not a failure (ENG-09, ENG-24)."""
        return self.rung in COLD_START and self.fell_through_from is None

    def top(self, n: int = 5) -> list[CategoryShare]:
        return self.categories[:n]

    def summary(self) -> str:
        head = ", ".join(f"{c.category} {c.share:.2f}" for c in self.top(3))
        stamp = f"{self.method} v{self.model_version}" if self.method else self.model_version
        through = (
            f" (fell through from rung {int(self.fell_through_from)})"
            if self.fell_through_from
            else ""
        )
        return (
            f"{self.user_id}: rung {int(self.rung)} -- {self.rung_description}"
            f"{through} [{stamp}] {head or 'no categories'}"
        )


def evenly_spread(categories: list[str]) -> list[CategoryShare]:
    """Equal shares across the categories given.

    Used at rung 2. This is NOT the forbidden uniform distribution: that rule is
    about inventing a spread across the whole vocabulary for a user we know
    nothing about. Here the user told us exactly these categories at signup and
    we have nothing to rank them by, so an equal split is the honest answer --
    and it is labelled as not personalised either way.
    """
    unique = list(dict.fromkeys(c for c in categories if c and c.strip()))
    if not unique:
        return []
    share = 1.0 / len(unique)
    return [CategoryShare(category=c, share=share) for c in unique]
