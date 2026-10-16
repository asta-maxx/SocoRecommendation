"""Keep the settings in force in step with the file, and log every change. ENG-02 items 3-4.

    await load_at_start(settings)   once, when the API or a job starts
    await reload(settings)          again and again; the API runs reload_loop()

Every accepted change is written to ml_config_changes (SD-09, ENG-02 item 4):
when, the old and new value of each changed setting, who made it, and a full
snapshot. The snapshot means a restart with a broken file still finds the last
good version, so "no good version has ever loaded" really means never.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import ValidationError
from reco.config import Settings
from reco.config import live
from reco.config.tunables import Tunables
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.settings")


def _record(settings: Settings, previous: Tunables, new: Tunables, changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "changed_at": utc_now(),
        "config_version": new.config_version,
        "previous_version": previous.config_version,
        "changed_by": new.changed_by,
        "environment": settings.engine_env,
        "source": settings.settings_file,
        "changes": changes,
        "values": new.model_dump(),
    }


#: A change in force whose record could not be written yet; tried again on every
#: reload until it is (ENG-02 item 4: every change is logged).
_unrecorded: dict[str, Any] | None = None


async def _record_pending(settings: Settings) -> None:
    global _unrecorded
    if _unrecorded is None:
        return
    try:
        await writers.record_config_change(settings, _unrecorded)
        logger.info("settings change recorded late", extra={"config_version": _unrecorded["config_version"]})
        _unrecorded = None
    except Exception:
        logger.exception("still could not record the settings change in ml_config_changes")


def _is_rollback(previous: str, new: str) -> bool:
    try:
        return int(new) < int(previous)
    except ValueError:
        return False


async def _apply(settings: Settings, previous: Tunables, new: Tunables, changes: list[dict[str, Any]]) -> None:
    global _unrecorded
    live.put_in_force(new, "file")
    record = _record(settings, previous, new, changes)
    # Kala F5 (16 Oct): every version put in force is written, a return to a lower
    # version too (a rollback). One entry per transition: an entry is keyed on the
    # versions and the entry it follows, so the API and a job noticing the same
    # change still write it once, and going back to a version already used is new.
    try:
        latest = await writers.read_latest_config_change(settings)
    except Exception:
        latest = None
    record["follows"] = latest.get("_id") if latest else None
    record["rollback"] = _is_rollback(previous.config_version, new.config_version)
    try:
        recorded = await writers.record_config_change(settings, record)
    except Exception:
        # The change is in force either way; only its record is missing. It is
        # tried again on every reload until it is written.
        logger.exception("could not record the settings change in ml_config_changes")
        _unrecorded = record
        recorded = False
    logger.info(
        "settings changed",
        extra={
            "config_version": new.config_version,
            "previous_version": previous.config_version,
            "changed_by": new.changed_by,
            "changed_keys": [c["key"] for c in changes],
            # False when another process (the API or a job) recorded it first.
            "recorded": recorded,
        },
    )


def _fault(fault: str) -> None:
    logger.error(
        "settings file rejected; keeping the settings in force",
        extra={"fault": fault, "config_version_in_force": live.current().config_version,
               "source_in_force": live.state().source},
    )


async def load_at_start(settings: Settings) -> None:
    """Choose the settings to start with: the file, else the last good, else the defaults."""
    live.reset()
    try:
        last = await writers.read_latest_config_change(settings)
    except Exception:
        logger.exception("could not read ml_config_changes; starting without the last good record")
        last = None
    last_good = None
    if last:
        try:
            last_good = Tunables.model_validate(last["values"])
        except ValidationError as exc:
            # A code update changed the settings' shape (v1.4: the order-history map), so
            # the recorded copy no longer reads. It can't be a fallback; the file still can.
            logger.warning(
                "the last recorded settings no longer match the settings model; not used as a fallback",
                extra={"config_version": last.get("config_version") or last.get("new_version"),
                       "errors": exc.error_count()},
            )
    read = live.read_file(settings.settings_file)
    live.state().seen = read.fingerprint

    if read.tunables is not None:
        baseline = last_good or live.current()
        decision = live.decide(baseline, read.tunables)
        if decision.fault:
            _fault(decision.fault)
        elif decision.accept:
            await _apply(settings, baseline, read.tunables, decision.changes)
            return
        else:
            # The file is exactly the last recorded version.
            live.put_in_force(read.tunables, "file")
            logger.info("settings loaded", extra={"config_version": read.tunables.config_version})
            return
    else:
        _fault(read.fault or "unreadable")

    if last_good is not None:
        live.put_in_force(last_good, "engine database")
        logger.warning(
            "using the last good settings recorded in ml_config_changes",
            extra={"config_version": last_good.config_version},
        )
    else:
        logger.warning(
            "no good settings have ever loaded; using the Settings sheet defaults",
            extra={"config_version": live.current().config_version},
        )


async def reload(settings: Settings) -> None:
    """Look at the file again. Apply a good change; keep the last good one otherwise."""
    await _record_pending(settings)
    read = live.read_file(settings.settings_file)
    if read.fingerprint is not None and read.fingerprint == live.state().seen:
        return  # unchanged since last look, good or bad
    live.state().seen = read.fingerprint

    if read.tunables is None:
        _fault(read.fault or "unreadable")
        return
    in_force = live.current()
    decision = live.decide(in_force, read.tunables)
    if decision.fault:
        _fault(decision.fault)
    elif decision.accept:
        await _apply(settings, in_force, read.tunables, decision.changes)


async def reload_loop(settings: Settings) -> None:
    """Run for the life of the API: reload every RELOAD_SECONDS, whatever happens."""
    while True:
        await asyncio.sleep(live.RELOAD_SECONDS)
        try:
            await reload(settings)
        except Exception:
            logger.exception("settings reload failed; keeping the settings in force")
