"""The settings in force, and the rules for replacing them. ENG-02 item 3, SD-09.

    current()          the Tunables every request and job reads right now
    read_file(path)    parse and validate the settings file
    decide(...)        should a newly read file replace the settings in force?

The rules (SD-09, ENG-02):
  - A file that cannot be read, cannot be parsed or breaks a range is rejected:
    the last good version stays in force and the fault is logged.
  - A file whose values changed but whose config_version did not is rejected
    too: every change needs a new version (SD-07), because the version is what a
    served list records.
  - With no good version at all, the Settings-sheet defaults apply.

No database here. reco.config.sync connects these rules to ml_config_changes.
"""

from __future__ import annotations

import hashlib
import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reco.config.tunables import Slots, Tunables

logger = logging.getLogger("reco.settings")

#: SD-09 says at least once a minute. Every 30 seconds keeps well inside that.
RELOAD_SECONDS = 30

#: Where the file is looked for when a relative path is given: the repo root.
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class State:
    tunables: Tunables = field(default_factory=Tunables)
    #: Where the settings in force came from: "defaults", "file" or "engine database".
    source: str = "defaults"
    #: Fingerprint of the file bytes last looked at, good or bad, so an
    #: unchanged file is not re-parsed and a broken one is logged once.
    seen: str | None = None


_state = State()


def current() -> Tunables:
    """The settings in force. Read this at the moment of use; it can change."""
    return _state.tunables


def state() -> State:
    return _state


def reset() -> None:
    """Back to the Settings-sheet defaults. Test seam."""
    global _state
    _state = State()


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


@dataclass
class FileRead:
    fingerprint: str | None
    tunables: Tunables | None = None
    fault: str | None = None


def read_file(path: str) -> FileRead:
    """Read and validate the settings file. Never raises: a fault is reported."""
    target = resolve(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return FileRead(fingerprint=None, fault=f"cannot read {target}: {exc.strerror or exc}")

    fingerprint = hashlib.sha256(raw).hexdigest()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return FileRead(fingerprint, fault=f"not valid TOML: {exc}")
    try:
        tunables = Tunables.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()
        )
        return FileRead(fingerprint, fault=f"outside the Settings sheet's rules: {problems}")
    return FileRead(fingerprint, tunables=_slots_as_written(tunables, data))


def _slots_as_written(tunables: Tunables, data: dict[str, Any]) -> Tunables:
    """DS-017 section 5, "Missing configuration": a slot the file leaves out gives
    every user the default method (split 0; the default is method one), and the
    fault is logged. Without this the Settings-sheet split of 50 would apply
    silently."""
    written = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    missing = [slot for slot in Slots.model_fields if slot not in written]
    if not missing:
        return tunables
    logger.error(
        "settings file has no " + ", ".join(f"[slots.{slot}]" for slot in missing)
        + ": everyone gets the default method there",
        extra={"missing_slots": missing},
    )
    return tunables.with_changes({f"slots.{slot}.split": 0 for slot in missing})


def differences(old: Tunables, new: Tunables) -> list[dict[str, Any]]:
    """Every value that differs, as {key, old, new}. Keys are dotted: interest.half_life_days."""
    before, after = old.values(), new.values()
    return [
        {"key": key, "old": before.get(key), "new": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


@dataclass
class Decision:
    accept: bool
    changes: list[dict[str, Any]] = field(default_factory=list)
    fault: str | None = None


def decide(in_force: Tunables, candidate: Tunables) -> Decision:
    """Should `candidate` replace the settings `in_force`?"""
    changes = differences(in_force, candidate)
    if candidate.config_version == in_force.config_version:
        if changes:
            return Decision(
                accept=False,
                fault=(
                    f"values changed but config_version is still "
                    f"{candidate.config_version!r}: raise config_version for every change"
                ),
            )
        # Same version, same values: nothing to do (a comment or spacing edit).
        return Decision(accept=False)
    return Decision(accept=True, changes=changes)


def put_in_force(tunables: Tunables, source: str) -> None:
    _state.tunables = tunables
    _state.source = source
