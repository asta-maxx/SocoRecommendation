"""Settings state kept on the server's own disk. ENG-02 items 3-4, SD-09, SD-10.

The diary (ml_config_changes) is the record of every settings change, and a
change is applied only once its diary entry is written. One exception: turning a
surface off (SD-10: "at once ... No approval is needed") is applied even while
the engine database is down. Its diary entry then waits here, with the off state
it puts in force, until the database is back.

    directory(settings)               <state dir>/<engine database>/
    add_pending(settings, entry)      keep a diary entry not written yet
    pending(settings)                 those entries, oldest first
    remove_pending(settings, entry_id)
    save_last_recorded(settings, entry), last_recorded(settings)
                                      a copy of the latest diary entry, so a
                                      start with the database down still finds
                                      the last good settings

The state directory is outside the code folder, so a restart and a redeploy both
keep it: RECO_STATE_DIR; unset, /var/lib/reco on test and production and .state/
(git-ignored) in the repo on dev. Each engine database has its own folder, so two
databases' entries never mix. Files are JSON, written to a temporary file, synced
and then moved into place, so a crash leaves the old file or the new one, never
half of one.

This is the server's disk, not a database: the engine database is written only by
reco.store.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reco.config import Settings

logger = logging.getLogger("reco.settings")

#: Where the state is kept when RECO_STATE_DIR is unset.
SERVER_DIR = Path("/var/lib/reco")
DEV_DIR = Path(__file__).resolve().parents[2] / ".state"

#: The file format. Raised if a file's shape changes.
FORMAT = 1

PENDING = "pending_settings"
LAST_RECORDED = "last_recorded_settings.json"


def directory(settings: Settings) -> Path:
    """The folder for this engine database's state (not created here)."""
    if settings.state_dir:
        base = Path(settings.state_dir)
    elif settings.engine_env in ("test", "production"):
        base = SERVER_DIR
    else:
        base = DEV_DIR
    return base / _safe(settings.ml_mongo_db)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "_"


# --- encoding -------------------------------------------------------------------


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # an ObjectId from an older diary entry


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$datetime"}:
            return datetime.fromisoformat(value["$datetime"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _write_atomically(path: Path, content: dict[str, Any]) -> None:
    """Temporary file, fsync, os.replace, then fsync the folder (where the system allows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(content, out, indent=1, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    try:
        folder = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return  # Windows cannot open a folder; os.replace is already durable there
    try:
        os.fsync(folder)
    except OSError:
        pass
    finally:
        os.close(folder)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.exception("a settings state file could not be read; left in place", extra={"path": str(path)})
        return None
    if not isinstance(content, dict) or content.get("format") != FORMAT:
        logger.error("a settings state file has an unknown format; left in place", extra={"path": str(path)})
        return None
    return content


# --- pending diary entries --------------------------------------------------------


def _pending_dir(settings: Settings) -> Path:
    return directory(settings) / PENDING


def _pending_name(entry: dict[str, Any]) -> str:
    # Named by the time of the change, then the entry's id: sorting the names gives
    # the order the changes were made in.
    when = entry["changed_at"].strftime("%Y%m%dT%H%M%S%fZ")
    return f"{when}-{_safe(str(entry['_id']))}.json"


def add_pending(settings: Settings, entry: dict[str, Any]) -> Path:
    """Keep a diary entry until it can be written. Raises OSError if it cannot be kept."""
    path = _pending_dir(settings) / _pending_name(entry)
    _write_atomically(path, {"format": FORMAT, "engine_database": settings.ml_mongo_db, "entry": _encode(entry)})
    return path


def pending(settings: Settings) -> list[dict[str, Any]]:
    """The diary entries waiting to be written, oldest first."""
    folder = _pending_dir(settings)
    try:
        names = sorted(p for p in folder.iterdir() if p.suffix == ".json" and not p.name.startswith(".tmp-"))
    except FileNotFoundError:
        return []
    except OSError:
        logger.exception("the settings state directory cannot be read", extra={"path": str(folder)})
        return []
    entries = []
    for path in names:
        content = _read(path)
        if content is not None and isinstance(content.get("entry"), dict):
            entries.append(_decode(content["entry"]))
    return entries


def remove_pending(settings: Settings, entry_id: str) -> None:
    """Forget an entry once it is in the diary. Already gone is fine (another process)."""
    folder = _pending_dir(settings)
    try:
        paths = list(folder.glob(f"*-{_safe(str(entry_id))}.json"))
    except FileNotFoundError:
        return
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# --- the copy of the latest diary entry ------------------------------------------------


def save_last_recorded(settings: Settings, entry: dict[str, Any]) -> None:
    """Keep a copy of the latest diary entry. Never raises: the copy is a convenience."""
    copy = {k: entry.get(k) for k in ("_id", "config_version", "previous_version", "changed_at", "changed_by", "values")}
    try:
        _write_atomically(directory(settings) / LAST_RECORDED,
                          {"format": FORMAT, "engine_database": settings.ml_mongo_db, "entry": _encode(copy)})
    except OSError:
        logger.warning("could not keep a copy of the latest settings diary entry on disk",
                       extra={"state_dir": str(directory(settings))}, exc_info=True)


def last_recorded(settings: Settings) -> dict[str, Any] | None:
    content = _read(directory(settings) / LAST_RECORDED)
    if content is None or not isinstance(content.get("entry"), dict):
        return None
    return _decode(content["entry"])
