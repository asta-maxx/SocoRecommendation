"""Choose each user's method in each slot, the same way every time. ENG-05.

    bucket("interest", user_id)          0-99
    assign("interest", user_id)          Assignment(slot, method, which, bucket, config_version)
    policy_id(a1, a2)                    "cfg2.interest-recency_decay.promoter_score-shrinkage"

The rule (Build List ENG-05):

  1. SHA-256 of "<slot name>:<user_id>"; the first 8 hex characters, mod 100,
     are the user's bucket.
  2. A bucket below the slot's split gets method two; everyone else method one.
  3. Split, method one, method two and the default are settings (slots.*); the
     split starts at 50 in every slot and the default is method one.
  4. If the settings are missing, everyone gets the default and the fault is
     logged.

policy_id names each method (Build List ENG-26: "so history stays readable
across the swap").

Never Python's hash() (salted per process, so it changes on restart), never a
session or device id: the same user keeps the same method across restarts and
devices. Changing a split moves users at once, with no deploy, because the
settings in force are read at the moment of use.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Literal

from reco.config import live
from reco.config.tunables import Slot, Slots, Tunables

logger = logging.getLogger("reco.slots")

SLOT_NAMES = tuple(Slots.model_fields)  # interest, product_ranking, promoter_score

Which = Literal["method_one", "method_two"]


@dataclass(frozen=True)
class Assignment:
    slot: str
    method: str  # the method's name, e.g. recency_decay
    which: Which
    bucket: int
    config_version: str
    from_default: bool = False  # the settings were missing: the default was used


def bucket(slot: str, user_id: str) -> int:
    """Item 1: the first 8 hex characters of SHA-256("<slot>:<user_id>"), mod 100."""
    digest = hashlib.sha256(f"{slot}:{user_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _slot_settings(slot: str, tunables: Tunables | None) -> Slot | None:
    try:
        found = getattr(tunables.slots, slot)
    except AttributeError:
        return None
    return found if isinstance(found, Slot) else None


def assign(slot: str, user_id: str, tunables: Tunables | None = None) -> Assignment:
    """The method `user_id` gets in `slot` under the settings in force (or `tunables`)."""
    if slot not in SLOT_NAMES:
        raise ValueError(f"unknown slot {slot!r}; the slots are {', '.join(SLOT_NAMES)}")
    tunables = tunables if tunables is not None else live.current()
    user_bucket = bucket(slot, str(user_id))
    settings = _slot_settings(slot, tunables)
    version = str(getattr(tunables, "config_version", "") or "")
    if settings is None:
        # Item 4: no settings for the slot -- everyone gets the default, and the fault is logged.
        logger.error("slot settings missing; using the default method", extra={"slot": slot})
        fallback = getattr(Slots(), slot)
        which: Which = fallback.default_method
        return Assignment(slot, getattr(fallback, which), which, user_bucket, version, from_default=True)
    if not str(user_id or "").strip():
        # DS-017 4.1: if user_id is ever missing, the default method in every slot.
        which = settings.default_method
        return Assignment(slot, getattr(settings, which), which, user_bucket, version, from_default=True)
    which = "method_two" if user_bucket < settings.split else "method_one"
    return Assignment(slot, getattr(settings, which), which, user_bucket, version)


def method_number(assignment: Assignment) -> int:
    return 2 if assignment.which == "method_two" else 1


def policy_id(*assignments: Assignment, config_version: str | None = None) -> str:
    """cfg<version>.<slot>-<method> for each slot the request touched, with the
    method's NAME: "cfg2.interest-recency_decay.promoter_score-shrinkage".

    Build List ENG-05 ("cfg<version>.<slot>-<method>") and ENG-26 ("policy_id
    records method names, so history stays readable across the swap"), with
    SD-15. DS-017 4.2's example ("cfg3.interest-2.promoter-1") shows numbers;
    the Build List comes first in the pack's order."""
    version = config_version if config_version is not None else (assignments[0].config_version if assignments else "")
    return ".".join([f"cfg{version}", *(f"{a.slot}-{a.method}" for a in assignments)])


def assign_all(user_id: str, tunables: Tunables | None = None) -> dict[str, Assignment]:
    """Every slot's assignment for one user, under one reading of the settings."""
    tunables = tunables if tunables is not None else live.current()
    return {slot: assign(slot, user_id, tunables) for slot in SLOT_NAMES}
