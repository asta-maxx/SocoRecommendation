"""Act out the settings diary's rule and its exception (ENG-02 item 4, SD-09, SD-10;
review point 3, 26 Oct 2026) against a throwaway engine database.

    .venv/bin/python scripts/demo_settings_diary.py

Uses the engine cluster in .env, but only the throwaway database reco_diary_check
(dropped at the start and the end), a settings copy and a state directory in a
temporary folder. "The database is down" is the same settings pointed at an
address nothing listens on (127.0.0.1:1), the way the checklist's 2.4 does it.

  1. a change with a test account's expiry date is written to the diary
  2. the rule: database down, a change is not applied, an alert fires
  3. the exception: database down, the feed is turned off at once; its entry waits on disk
  4. a restart (new process) and a redeploy (new code folder, the older file) with the
     database still down: both start with the feed off
  5. turning the feed back on with the database down waits
  6. the database is back: the off entry is written once (replayed five times), then the
     feed goes back on with its own entry
Prints PASS or FAIL per step and exits 0 only if every step passes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings, live, state, sync  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store import writers  # noqa: E402

DATABASE = "reco_diary_check"
DOWN = "mongodb://127.0.0.1:1"
ACCOUNT = "64f1c0ffee0000000000abcd"
FILE = (ROOT / "settings" / "engine.toml").read_text(encoding="utf-8")
RESULTS: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail else ""), flush=True)


def settings_text(number: int, feed: str, product: str = "live", stale_after: int = 48) -> str:
    current = next(line for line in FILE.splitlines() if line.startswith("config_version = "))
    return (FILE.replace(current, f'config_version = "{number}"', 1)
            .replace('changed_by = "Allen"', 'changed_by = "Diary demo"', 1)
            .replace('surface_mode_feed = "off"', f'surface_mode_feed = "{feed}"', 1)
            .replace('surface_mode_product = "off"', f'surface_mode_product = "{product}"', 1)
            .replace("stale_after_hours = 48", f"stale_after_hours = {stale_after}", 1)
            .replace("test_accounts = []", f'test_accounts = [{{ account_id = "{ACCOUNT}", reason = "diary demo", '
                                           f'expiry = 2026-12-31, changed_by = "Allen" }}]', 1))


class Caught(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def alerts(self, reason: str) -> int:
        return sum(1 for r in self.records if getattr(r, "reason", None) == reason)


def in_force() -> str:
    t = live.current()
    return f"config_version {t.config_version}, feed {t.serving.surface_mode_feed}, product {t.serving.surface_mode_product}"


def start_new_process(code: Path, settings_file: Path, state_dir: Path) -> dict:
    """A new engine process (the API's start) from `code`, the database unreachable."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("ML_", "APP_", "SETTINGS_", "RECO_"))}
    environment.update({"ENGINE_ENV": "dev", "ML_MONGO_URI": DOWN, "APP_MONGO_URI": "mongodb://127.0.0.1:2",
                        "ML_MONGO_DB": DATABASE, "MONGO_TIMEOUT_SECONDS": "1", "RECO_STATE_DIR": str(state_dir),
                        "SETTINGS_FILE": str(settings_file), "PYTHONPATH": str(code)})
    script = ("import asyncio, json, logging\nlogging.disable(logging.CRITICAL)\n"
              "from reco.config import get_settings, live, sync\nfrom reco.store import connection\n"
              "async def main():\n    s = get_settings(); connection.init_client(s); await sync.load_at_start(s)\n"
              "    t = live.current()\n    print(json.dumps({'config_version': t.config_version, "
              "'feed': t.serving.surface_mode_feed, 'product': t.serving.surface_mode_product, "
              "'source': live.state().source, 'code': sync.__file__}))\nasyncio.run(main())\n")
    done = subprocess.run([sys.executable, "-c", script], cwd=code, env=environment,
                          capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        return {"error": done.stderr.strip().splitlines()[-1:] or ["no output"]}
    return json.loads(done.stdout.strip().splitlines()[-1])


async def main() -> int:
    base = get_settings()
    work = Path(tempfile.mkdtemp(prefix="soco-diary-"))
    path = work / "release1" / "settings" / "engine.toml"
    path.parent.mkdir(parents=True)
    state_dir = work / "var-lib-reco"
    up = base.model_copy(update={"ml_mongo_db": DATABASE, "settings_file": str(path), "state_dir": str(state_dir)})
    down = up.model_copy(update={"ml_mongo_uri": DOWN, "mongo_timeout_seconds": 1.0})
    caught = Caught()
    for name in ("reco.settings", "reco.alert"):
        logging.getLogger(name).addHandler(caught)
        logging.getLogger(name).setLevel(logging.INFO)

    async def connect(settings) -> None:
        await store_conn.close_client()
        store_conn.init_client(settings)

    print(f"Engine database {DATABASE} (throwaway), state directory {state_dir}")
    await connect(up)
    def diary():  # a fresh handle: the client is replaced when the database "goes down"
        return store_conn.ml_db(up)["ml_config_changes"]

    try:
        await store_conn.ml_db(up).client.drop_database(DATABASE)
        await writers.ensure_engine_collections(up)

        print("1. A change with a date")
        path.write_text(settings_text(10, feed="live"), encoding="utf-8")
        await sync.load_at_start(up)
        row = await diary().find_one({"config_version": "10"})
        expiry = row["values"]["lists"]["test_accounts"][0]["expiry"] if row else None
        check("a change with a test account's expiry (2026-12-31) is in ml_config_changes", expiry == "2026-12-31",
              f"in force: {in_force()}; diary expiry {expiry!r}")

        print("2. The rule, database down")
        await connect(down)
        path.write_text(settings_text(11, feed="live", stale_after=60), encoding="utf-8")
        await sync.reload(down)
        await sync.reload(down)  # tried again: the file still differs
        check("a change that cannot be written is not applied; the settings in force stay",
              live.current().config_version == "10" and live.current().interest.stale_after_hours == 48,
              f"in force: {in_force()}")
        check("an alert fired: settings_change_not_recorded (once)", caught.alerts("settings_change_not_recorded") == 1)

        print("3. The exception, database down: the feed off")
        path.write_text(settings_text(11, feed="off"), encoding="utf-8")
        await sync.reload(down)
        waiting = state.pending(down)
        check("the feed is off at once", live.current().serving.surface_mode_feed == "off", f"in force: {in_force()}")
        check("its diary entry waits in the state directory, with its own id",
              len(waiting) == 1 and waiting[0]["config_version"] == "11",
              f"entry {waiting[0]['_id'] if waiting else None} in {state.directory(down) / state.PENDING}")
        check("an alert fired: settings_change_pending", caught.alerts("settings_change_pending") == 1)

        print("4. A restart and a redeploy, database still down")
        restarted = start_new_process(ROOT, path, state_dir)
        check("restart (a new process): starts with the feed off",
              (restarted.get("config_version"), restarted.get("feed")) == ("11", "off"), json.dumps(restarted))
        release2 = work / "release2"
        shutil.copytree(ROOT / "reco", release2 / "reco", ignore=shutil.ignore_patterns("__pycache__"))
        (release2 / "settings").mkdir()
        (release2 / "settings" / "engine.toml").write_text(settings_text(10, feed="live"), encoding="utf-8")
        redeployed = start_new_process(release2, release2 / "settings" / "engine.toml", state_dir)
        check("redeploy (a new code folder carrying the older file, feed live): starts with the feed off",
              (redeployed.get("config_version"), redeployed.get("feed")) == ("11", "off")
              and str(redeployed.get("code", "")).startswith(str(release2)), json.dumps(redeployed))

        print("5. Turning the feed back on, database still down")
        path.write_text(settings_text(12, feed="live"), encoding="utf-8")
        await sync.reload(down)
        check("not applied until its diary entry is written: the feed stays off",
              live.current().serving.surface_mode_feed == "off" and live.current().config_version == "11",
              f"in force: {in_force()}")

        print("6. The database is back")
        await connect(up)
        entry = waiting[0]
        for _ in range(5):  # replayed: the entry put back as if a crash came before its file was removed
            state.add_pending(up, dict(entry))
            await sync._write_pending(up)
        rows = await diary().count_documents({"_id": entry["_id"]})
        check("the off entry is written once, replayed five times", rows == 1, f"{rows} row(s) with id {entry['_id']}")
        await sync.reload(up)
        check("then the feed goes back on, with its own entry",
              live.current().serving.surface_mode_feed == "live" and live.current().config_version == "12",
              f"in force: {in_force()}")
        transitions = [(r["previous_version"], r["config_version"]) async for r in diary().find({}).sort("changed_at", 1)]
        check("the diary holds each change once, in order: 0->10, 10->11, 11->12",
              transitions == [("0", "10"), ("10", "11"), ("11", "12")], str(transitions))
        check("nothing left waiting in the state directory", not state.pending(up))
        print("\n  The diary:")
        async for r in diary().find({}, {"values": 0}).sort("changed_at", 1):
            print(f"    {r['changed_at'].isoformat(timespec='seconds')}  {r['previous_version']} -> {r['config_version']}"
                  f"  by {r['changed_by']}" + ("  (applied first, written when the database was back)"
                                                if r.get("applied_before_recorded") else ""))
            for c in r.get("changes") or []:
                if c["key"].startswith(("serving.surface", "lists.test_accounts", "interest.stale")):
                    print(f"        {c['key']}: {c['old']} -> {c['new']}")
    finally:
        await store_conn.close_client()
        store_conn.init_client(up)
        await store_conn.ml_db(up).client.drop_database(DATABASE)
        await store_conn.close_client()
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n== {sum(RESULTS)} of {len(RESULTS)} passed; {DATABASE} dropped")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
