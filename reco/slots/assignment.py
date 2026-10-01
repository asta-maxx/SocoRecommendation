"""Choose each user's method in each slot, the same way every time. ENG-05.

    bucket("interest", user_id)          0-99
    assign("interest", user_id)          Assignment(slot, method, which, bucket, config_version)
    policy_id(assignment)                "cfg2.interest-recency_decay"

The rule (Build List ENG-05):

  1. SHA-256 of "<slot name>:<user_id>"; the first 8 hex characters, mod 100,
     are the user's bucket.
  2. A bucket below the slot's split gets method two; everyone else method one.
  3. Split, method one, method two and the default are settings (slots.*); the
     split starts at 50 in every slot and the default is method one.
  4. If the settings are missing, everyone gets the default and the fault is
     logged.

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
    which = "method_two" if user_bucket < settings.split else "method_one"
    return Assignment(slot, getattr(settings, which), which, user_bucket, version)


def policy_id(assignment: Assignment) -> str:
    """cfg<version>.<slot>-<method>, as a served list records it."""
    return f"cfg{assignment.config_version}.{assignment.slot}-{assignment.method}"


def assign_all(user_id: str, tunables: Tunables | None = None) -> dict[str, Assignment]:
    """Every slot's assignment for one user, under one reading of the settings."""
    tunables = tunables if tunables is not None else live.current()
    return {slot: assign(slot, user_id, tunables) for slot in SLOT_NAMES}
