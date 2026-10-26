"""Keep the settings in force in step with the file, and log every change. ENG-02 items 3-4.

    await load_at_start(settings)   once, when the API or a job starts
    await reload(settings)          again and again; the API runs reload_loop()

Every accepted change is written to ml_config_changes (SD-09, ENG-02 item 4):
when, the old and new value of each changed setting, who made it, and a full
snapshot. The snapshot means a restart with a broken file still finds the last
good version, so "no good version has ever loaded" really means never.

The rule (review point 3, 26 Oct 2026): a change is applied only once its diary
entry is written. If the entry cannot be written, the settings in force stay, an
alert fires (settings_change_not_recorded), and the change is tried again on the
next reload, because the file still differs.

The one exception is a change that only turns a surface off (SD-10: the owner
sets a surface off at once, no approval needed). It is applied at once. Its diary
entry, with its own id, and the off state are first kept in the state directory
(reco.config.state), which survives a restart and a redeploy; a start applies
that off state before serving, database or not. When the database is back the
entry is written once, however many times it is replayed (keyed on its id), and
then removed. Turning a surface back on is any other change: it waits for its
diary entry, and for every entry still waiting before it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from pydantic_core import to_jsonable_python
from reco.config import Settings
from reco.config import live, state
from reco.config.tunables import Tunables
from reco.monitoring.alerts import alert
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.settings")

#: The surface modes (SD-10). A change that only sets these to "off" is the exception.
SURFACES = ("serving.surface_mode_feed", "serving.surface_mode_product")


def only_turns_surfaces_off(changes: list[dict[str, Any]]) -> bool:
    """True when every changed value is a surface going to "off" (and something changed)."""
    return bool(changes) and all(c["key"] in SURFACES and c["new"] == "off" for c in changes)


def _record(settings: Settings, previous: Tunables, new: Tunables, changes: list[dict[str, Any]]) -> dict[str, Any]:
    # The diary holds plain values: a date (a test account's expiry) is its ISO
    # text, as the file writes it, and reads back through Tunables unchanged.
    return {
        # The entry's own id: writing it again (a replay, or a retry after a
        # timeout that did write) finds it there and adds nothing.
        "_id": uuid.uuid4().hex,
        "changed_at": utc_now(),
        "config_version": new.config_version,
        "previous_version": previous.config_version,
        "changed_by": new.changed_by,
        "environment": settings.engine_env,
        "source": settings.settings_file,
        "changes": to_jsonable_python(changes),
        "values": new.model_dump(mode="json"),
        "rollback": _is_rollback(previous.config_version, new.config_version),
    }


def _is_rollback(previous: str, new: str) -> bool:
    try:
        return int(new) < int(previous)
    except ValueError:
        return False


#: The last refused change alerted, as (in force, refused): one alert per refusal,
#: not one every reload while the database stays down.
_alerted: tuple[str, str] | None = None


def _refuse(settings: Settings, previous: Tunables, new: Tunables, reason: str) -> None:
    """The rule: not written, not applied. Alert once; look again on the next reload."""
    global _alerted
    fields = {"config_version": new.config_version, "config_version_in_force": previous.config_version,
              "changed_by": new.changed_by, "reason_not_recorded": reason}
    logger.error("settings change not applied: its diary entry could not be written to ml_config_changes; "
                 "keeping the settings in force", extra=fields)
    if _alerted != (previous.config_version, new.config_version):
        _alerted = (previous.config_version, new.config_version)
        alert("settings_change_not_recorded",
              f"settings version {new.config_version} was not applied: its diary entry could not be written",
              **fields)
    # The file still differs from the settings in force, so the next reload tries again.
    live.state().seen = None


async def _apply(settings: Settings, previous: Tunables, new: Tunables, changes: list[dict[str, Any]]) -> bool:
    """Write the diary entry, then put `new` in force. Returns whether it is in force."""
    global _alerted
    record = _record(settings, previous, new, changes)
    waiting = state.pending(settings)
    reason = None
    recorded = False
    if waiting:
        # Entries are written in the order the changes were made.
        reason = f"{len(waiting)} earlier change(s) still waiting to be written"
    else:
        # Kala F5 (16 Oct): every version put in force is written, a return to a lower
        # version too (a rollback). One entry per transition: an entry is keyed on the
        # versions and the entry it follows, so the API and a job noticing the same
        # change still write it once, and going back to a version already used is new.
        try:
            latest = await writers.read_latest_config_change(settings)
            record["follows"] = latest.get("_id") if latest else None
            # False when another process (the API or a job) recorded it first.
            recorded = await writers.record_config_change(settings, record)
        except Exception as exc:
            logger.warning("could not write the settings change to ml_config_changes", exc_info=True)
            reason = f"{type(exc).__name__}: {exc}"

    if reason is not None:
        if only_turns_surfaces_off(changes):
            return _turn_off_now(settings, previous, new, record, changes, reason)
        _refuse(settings, previous, new, reason)
        return False

    state.save_last_recorded(settings, record)
    live.put_in_force(new, "file")
    _alerted = None
    logger.info(
        "settings changed",
        extra={
            "config_version": new.config_version,
            "previous_version": previous.config_version,
            "changed_by": new.changed_by,
            "changed_keys": [c["key"] for c in changes],
            "recorded": recorded,
            "entry_id": record["_id"],
        },
    )
    return True


def _turn_off_now(settings: Settings, previous: Tunables, new: Tunables, record: dict[str, Any],
                  changes: list[dict[str, Any]], reason: str) -> bool:
    """The exception: a surface goes off at once; its entry waits on the server's disk."""
    record["follows"] = None  # set when it is written: the entry it then follows
    record["applied_before_recorded"] = True
    try:
        path = state.add_pending(settings, record)
    except OSError as exc:
        # Neither the diary nor the state directory: nothing would remember the
        # change, so it is not applied either.
        logger.exception("could not keep the surface-off change in the state directory either")
        _refuse(settings, previous, new, f"{reason}; state directory: {exc}")
        return False
    live.put_in_force(new, "file")
    fields = {"config_version": new.config_version, "previous_version": previous.config_version,
              "changed_by": new.changed_by, "changed_keys": [c["key"] for c in changes],
              "entry_id": record["_id"], "pending_file": str(path), "reason_not_recorded": reason}
    logger.warning("settings changed: surface turned off at once; its diary entry waits in the state directory "
                   "until the engine database is back", extra=fields)
    alert("settings_change_pending",
          f"settings version {new.config_version} turned a surface off before its diary entry could be written",
          **fields)
    return True


async def _write_pending(settings: Settings) -> bool:
    """Write the waiting entries to the diary, oldest first, each once. True when none is left."""
    for entry in state.pending(settings):
        try:
            latest = await writers.read_latest_config_change(settings)
            entry["follows"] = latest.get("_id") if latest and latest.get("_id") != entry["_id"] else None
            entry["recorded_at"] = utc_now()
            # False: already in the diary (an earlier replay, or another process).
            written = await writers.record_config_change(settings, entry)
        except Exception as exc:
            logger.warning("settings diary entry still waiting: the engine database cannot be written",
                           extra={"entry_id": entry["_id"], "config_version": entry["config_version"],
                                  "reason_not_recorded": f"{type(exc).__name__}: {exc}"})
            return False
        state.remove_pending(settings, entry["_id"])
        state.save_last_recorded(settings, entry)
        logger.info("settings change written to the diary after the engine database came back",
                    extra={"entry_id": entry["_id"], "config_version": entry["config_version"],
                           "previous_version": entry["previous_version"], "written": written})
    return True


def _fault(fault: str) -> None:
    logger.error(
        "settings file rejected; keeping the settings in force",
        extra={"fault": fault, "config_version_in_force": live.current().config_version,
               "source_in_force": live.state().source},
    )


def _readable(entry: dict[str, Any] | None) -> Tunables | None:
    if not entry:
        return None
    try:
        return Tunables.model_validate(entry["values"])
    except ValidationError as exc:
        # A code update changed the settings' shape (v1.4: the order-history map), so
        # the recorded copy no longer reads. It can't be a fallback; the file still can.
        logger.warning(
            "the last recorded settings no longer match the settings model; not used as a fallback",
            extra={"config_version": entry.get("config_version") or entry.get("new_version"),
                   "errors": exc.error_count()},
        )
        return None


async def load_at_start(settings: Settings) -> None:
    """Choose the settings to start with: the file, else the last good, else the defaults.

    A surface turned off while the database was down stays off: that waiting
    state is the settings in force to start from, and the file replaces it only
    under the rule (a change that turns the surface back on waits for the diary).
    """
    live.reset()
    await _write_pending(settings)
    try:
        last = await writers.read_latest_config_change(settings)
        last_from = "engine database"
        if last:
            state.save_last_recorded(settings, last)
    except Exception:
        logger.exception("could not read ml_config_changes; using the copy of the last entry in the state directory")
        last = state.last_recorded(settings)
        last_from = "state directory"
    waiting = state.pending(settings)
    if waiting:
        last = waiting[-1]
        last_from = "state directory"
        logger.warning("a surface was turned off before its diary entry could be written: starting from that state",
                       extra={"config_version": last["config_version"], "entry_id": last["_id"],
                              "waiting_entries": len(waiting)})
    last_good = _readable(last)
    read = live.read_file(settings.settings_file)
    live.state().seen = read.fingerprint

    if read.tunables is not None:
        baseline = last_good or live.current()
        decision = live.decide(baseline, read.tunables)
        if decision.fault:
            _fault(decision.fault)
        elif decision.accept:
            if await _apply(settings, baseline, read.tunables, decision.changes):
                return
        else:
            # The file is exactly the last recorded (or waiting) version.
            live.put_in_force(read.tunables, "file")
            logger.info("settings loaded", extra={"config_version": read.tunables.config_version})
            return
    else:
        _fault(read.fault or "unreadable")

    if last_good is not None:
        live.put_in_force(last_good, last_from)
        logger.warning(
            "using the last good settings" + (" recorded in ml_config_changes" if last_from == "engine database"
                                              else " kept in the state directory"),
            extra={"config_version": last_good.config_version, "source_in_force": last_from},
        )
    else:
        logger.warning(
            "no recorded settings to start from; using the Settings sheet defaults",
            extra={"config_version": live.current().config_version},
        )


async def reload(settings: Settings) -> None:
    """Look at the file again. Apply a good change once it is recorded; keep the settings in force otherwise."""
    await _write_pending(settings)
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
