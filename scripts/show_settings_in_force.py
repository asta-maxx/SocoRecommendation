"""Print the settings in force: the last diary entry, the file, and anything waiting. ENG-02 items 3-4.

    .venv/bin/python scripts/show_settings_in_force.py                # the engine database in .env
    ML_MONGO_DB=reco_demo SETTINGS_FILE=settings/engine.toml .venv/bin/python scripts/show_settings_in_force.py

Read-only. A change is in force only once it is in ml_config_changes (review point 3,
26 Oct 2026), so the last diary entry is the settings in force, except that a surface
turned off while the database was down is in force first and waits in the state
directory (reco.config.state). The file is shown beside it: "in step" means the file
is what is in force.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings, live, state  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store import writers  # noqa: E402


def describe(values: dict) -> str:
    serving = values.get("serving", {})
    return f"feed {serving.get('surface_mode_feed')}, product {serving.get('surface_mode_product')}"


async def main() -> int:
    settings = get_settings()
    store_conn.init_client(settings)
    try:
        latest = await writers.read_latest_config_change(settings)
    finally:
        await store_conn.close_client()
    waiting = state.pending(settings)
    read = live.read_file(settings.settings_file)

    print(f"settings in force for {settings.ml_mongo_db} ({settings.engine_env})")
    if latest:
        print(f"  last diary entry:   config_version {latest['config_version']} "
              f"(from {latest.get('previous_version')}, by {latest.get('changed_by')}, "
              f"{latest['changed_at'].isoformat(timespec='seconds')}), {describe(latest.get('values') or {})}")
    else:
        print("  last diary entry:   none (the Settings sheet defaults)")
    for entry in waiting:
        print(f"  waiting on disk:    config_version {entry['config_version']} (a surface turned off, "
              f"entry {entry['_id']}), {describe(entry.get('values') or {})}")
    if not waiting:
        print(f"  waiting on disk:    nothing ({state.directory(settings)})")
    if read.tunables is not None:
        file_values = read.tunables.model_dump(mode="json")
        print(f"  settings file:      config_version {read.tunables.config_version} ({settings.settings_file}), "
              f"{describe(file_values)}")
    else:
        print(f"  settings file:      rejected ({read.fault})")

    in_force = waiting[-1] if waiting else latest
    version = in_force["config_version"] if in_force else "0"
    print(f"  in force:           config_version {version}, "
          + (describe(in_force.get("values") or {}) if in_force else "feed off, product off"))
    same = read.tunables is not None and in_force is not None and read.tunables.config_version == version
    print(f"  in step with the file: {'yes' if same else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
