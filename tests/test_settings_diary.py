"""The settings diary: a change is applied only once it is written. ENG-02 item 4, SD-09, SD-10.

Review point 3 (26 Oct 2026):
  - a change with a date in it (a test account's expiry) is written to ml_config_changes;
  - the rule: a change that cannot be written is not applied, the settings in force
    stay, an alert fires, and the change is tried again;
  - the exception: a change that only turns a surface off is applied at once, kept
    with its own diary entry in the state directory through a restart and a
    redeploy, and written once when the database is back, however often replayed;
  - turning a surface back on waits for its diary entry.

The engine database is a stand-in here (it encodes every write with the driver's
own BSON codec, so a value MongoDB refuses is refused here too), except in the
tests marked mongo and the restart in a new process, where the database really
is unreachable.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import bson
import pytest
from bson.errors import InvalidDocument
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from reco.config import Settings, live, state, sync
from reco.config.tunables import Tunables
from reco.store import writers

ROOT = Path(__file__).resolve().parents[1]
FILE = (ROOT / "settings" / "engine.toml").read_text(encoding="utf-8")
ACCOUNT = "64f1c0ffee0000000000abcd"
DATED = (f'test_accounts = [{{ account_id = "{ACCOUNT}", reason = "diary check", '
         f'expiry = 2026-12-31, changed_by = "Allen" }}]')


def version(text: str, number: int, by: str = "Allen") -> str:
    """The committed file under another config_version (and changed_by)."""
    current = next(line for line in text.splitlines() if line.startswith("config_version = "))
    text = text.replace(current, f'config_version = "{number}"', 1)
    return text.replace('changed_by = "Allen"', f'changed_by = "{by}"', 1)


def surfaces(text: str, feed: str, product: str) -> str:
    return (text.replace('surface_mode_feed = "off"', f'surface_mode_feed = "{feed}"', 1)
            .replace('surface_mode_product = "off"', f'surface_mode_product = "{product}"', 1))


LIVE = surfaces(version(FILE, 10), "live", "live")           # both surfaces live
FEED_OFF = surfaces(version(FILE, 11), "off", "live")        # only the feed goes off
FEED_ON = surfaces(version(FILE, 12), "live", "live")        # the feed back on


class Diary:
    """ml_config_changes, with a switch to take the engine database down."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.down = False
        self.calls = 0  # every read or write tried, up or down

    def __getitem__(self, name: str) -> Diary:
        assert name == "ml_config_changes"
        return self

    def _check(self) -> None:
        self.calls += 1
        if self.down:
            raise ServerSelectionTimeoutError("engine database down")

    async def insert_one(self, document: dict) -> None:
        self._check()
        bson.encode(document)  # the driver's own encoding: a datetime.date is refused here
        if any(r["_id"] == document["_id"] for r in self.rows):
            raise DuplicateKeyError("E11000 duplicate key: _id")
        key = lambda r: (r.get("previous_version"), r["config_version"], r.get("follows"))  # noqa: E731
        if any(key(r) == key(document) for r in self.rows):
            raise DuplicateKeyError("E11000 duplicate key: uniq_transition")
        self.rows.append(copy.deepcopy(document))

    async def find_one(self, query: dict, sort=None) -> dict | None:
        self._check()
        return copy.deepcopy(max(self.rows, key=lambda r: r["changed_at"])) if self.rows else None

    def versions(self) -> list[tuple[str, str]]:
        return [(r["previous_version"], r["config_version"]) for r in self.rows]


@pytest.fixture
def diary(monkeypatch: pytest.MonkeyPatch) -> Diary:
    stand_in = Diary()
    monkeypatch.setattr(writers, "ml_db", lambda settings: stand_in)
    monkeypatch.setattr(sync, "_alerted", None)
    return stand_in


@pytest.fixture
def path(tmp_path: Path) -> Path:
    target = tmp_path / "release1" / "settings" / "engine.toml"
    target.parent.mkdir(parents=True)
    return target


def settings_for(path: Path, **extra) -> Settings:
    return Settings(settings_file=str(path), **extra)


def alerts(caplog, reason: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "reason", None) == reason]


def surface_modes() -> tuple[str, str]:
    serving = live.current().serving
    return serving.surface_mode_feed, serving.surface_mode_product


# --- 1. dates in the diary ---------------------------------------------------------


def test_a_date_is_what_the_driver_refused() -> None:
    """The fault check_m1 printed: BSON has no date type."""
    with pytest.raises(InvalidDocument, match="cannot encode"):
        bson.encode({"expiry": date(2026, 10, 26)})


async def test_a_change_with_a_test_account_expiry_is_written_and_reads_back(path: Path, diary: Diary) -> None:
    path.write_text(version(FILE, 10).replace("test_accounts = []", DATED), encoding="utf-8")
    await sync.load_at_start(settings_for(path))

    assert live.current().config_version == "10"
    [row] = diary.rows
    assert row["values"]["lists"]["test_accounts"][0]["expiry"] == "2026-12-31"
    [change] = [c for c in row["changes"] if c["key"] == "lists.test_accounts"]
    assert change["new"][0]["expiry"] == "2026-12-31" and change["old"] == []
    # Read back as the settings model: the date again.
    assert Tunables.model_validate(row["values"]).lists.test_accounts[0].expiry == date(2026, 12, 31)


def test_the_writer_turns_any_date_into_its_iso_text() -> None:
    when = datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc)
    plain = writers._diary_values({"changed_at": when, "values": {"a": [{"expiry": date(2026, 10, 26)}]}})
    assert plain == {"changed_at": when, "values": {"a": [{"expiry": "2026-10-26"}]}}  # a datetime stays one
    bson.encode(plain)


# --- 2. the rule ---------------------------------------------------------------------


async def test_a_change_that_cannot_be_written_is_not_applied(path: Path, diary: Diary, caplog) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    assert diary.versions() == [("0", "10")]

    diary.down = True
    changed = version(LIVE, 11).replace("stale_after_hours = 48", "stale_after_hours = 60")
    path.write_text(changed, encoding="utf-8")
    with caplog.at_level(logging.INFO):
        await sync.reload(settings)
        calls = diary.calls
        await sync.reload(settings)  # the file still differs: tried again
        assert diary.calls > calls
        await sync.reload(settings)

    assert live.current().config_version == "10" and live.current().interest.stale_after_hours == 48
    assert diary.versions() == [("0", "10")]
    assert len(alerts(caplog, "settings_change_not_recorded")) == 1  # one alert, not one per reload
    assert not any(r.getMessage() == "settings changed" and getattr(r, "config_version", None) == "11"
                   for r in caplog.records)  # nothing claims it was applied
    assert not state.pending(settings)  # not the exception: nothing kept on disk

    diary.down = False
    await sync.reload(settings)
    assert live.current().config_version == "11" and live.current().interest.stale_after_hours == 60
    assert diary.versions() == [("0", "10"), ("10", "11")]


async def test_at_start_a_file_that_cannot_be_written_waits_and_the_last_good_stays(
    path: Path, diary: Diary
) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)  # 10 recorded, and copied to the state directory

    diary.down = True
    path.write_text(version(LIVE, 11).replace("stale_after_hours = 48", "stale_after_hours = 60"), encoding="utf-8")
    await sync.load_at_start(settings)  # a restart, database down
    assert live.current().config_version == "10" and live.state().source == "state directory"

    diary.down = False
    await sync.reload(settings)
    assert live.current().config_version == "11"


async def test_a_change_that_turns_a_surface_off_and_changes_anything_else_follows_the_rule(
    path: Path, diary: Diary, caplog
) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)

    diary.down = True
    path.write_text(FEED_OFF.replace("stale_after_hours = 48", "stale_after_hours = 60"), encoding="utf-8")
    with caplog.at_level(logging.INFO):
        await sync.reload(settings)
    assert surface_modes() == ("live", "live") and live.current().config_version == "10"
    assert alerts(caplog, "settings_change_not_recorded") and not state.pending(settings)


def test_only_turning_surfaces_off_is_the_exception() -> None:
    off = {"key": "serving.surface_mode_feed", "old": "live", "new": "off"}
    assert sync.only_turns_surfaces_off([off])
    assert sync.only_turns_surfaces_off([off, {"key": "serving.surface_mode_product", "old": "internal", "new": "off"}])
    assert not sync.only_turns_surfaces_off([])
    assert not sync.only_turns_surfaces_off([{"key": "serving.surface_mode_feed", "old": "off", "new": "live"}])
    assert not sync.only_turns_surfaces_off([{"key": "serving.surface_mode_feed", "old": "live", "new": "internal"}])
    assert not sync.only_turns_surfaces_off([off, {"key": "interest.half_life_days", "old": 30, "new": 31}])


# --- 3. the exception ------------------------------------------------------------------


async def test_turning_a_surface_off_applies_at_once_and_is_written_once_when_the_database_is_back(
    path: Path, diary: Diary, caplog
) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)

    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    with caplog.at_level(logging.INFO):
        await sync.reload(settings)

    assert surface_modes() == ("off", "live") and live.current().config_version == "11"
    [waiting] = state.pending(settings)
    assert (waiting["previous_version"], waiting["config_version"]) == ("10", "11")
    assert waiting["changes"] == [{"key": "serving.surface_mode_feed", "old": "live", "new": "off"}]
    assert alerts(caplog, "settings_change_pending")
    assert diary.versions() == [("0", "10")]

    diary.down = False
    await sync.reload(settings)
    assert diary.versions() == [("0", "10"), ("10", "11")]
    row = diary.rows[-1]
    assert row["_id"] == waiting["_id"] and row["follows"] == diary.rows[0]["_id"]
    assert row["applied_before_recorded"] is True and row["changed_at"] == waiting["changed_at"]
    assert not state.pending(settings)


async def test_a_replay_writes_the_entry_once(path: Path, diary: Diary, monkeypatch) -> None:
    """A crash after the write and before the file is removed replays the entry: still one row."""
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings)
    [waiting] = state.pending(settings)

    diary.down = False
    keep = state.remove_pending
    monkeypatch.setattr(state, "remove_pending", lambda settings, entry_id: None)  # the crash
    for _ in range(5):
        await sync.reload(settings)
        await sync.load_at_start(settings)  # restarts, and the job process starting too
    assert [r["_id"] for r in diary.rows].count(waiting["_id"]) == 1
    assert diary.versions() == [("0", "10"), ("10", "11")]

    monkeypatch.setattr(state, "remove_pending", keep)
    await sync.reload(settings)
    assert not state.pending(settings) and len(diary.rows) == 2


async def test_a_restart_with_the_database_down_starts_with_the_surface_off(path: Path, diary: Diary) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings)

    live.reset()  # the process ends; nothing in memory survives
    assert surface_modes() == ("off", "off")  # (the defaults)
    await sync.load_at_start(settings)
    assert surface_modes() == ("off", "live") and live.current().config_version == "11"
    assert live.current() == Tunables.model_validate(state.pending(settings)[0]["values"])


async def test_a_redeploy_with_an_older_file_and_the_database_down_keeps_the_surface_off(
    tmp_path: Path, path: Path, diary: Diary, caplog
) -> None:
    """The new release carries the file from before the change (feed live): turning it
    back on is a change like any other, and waits for the diary."""
    path.write_text(LIVE, encoding="utf-8")
    await sync.load_at_start(settings_for(path))
    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings_for(path))

    release2 = tmp_path / "release2" / "settings" / "engine.toml"
    release2.parent.mkdir(parents=True)
    release2.write_text(LIVE, encoding="utf-8")
    live.reset()
    with caplog.at_level(logging.INFO):
        await sync.load_at_start(settings_for(release2))
    assert surface_modes() == ("off", "live") and live.current().config_version == "11"
    assert live.state().source == "state directory"
    assert alerts(caplog, "settings_change_not_recorded")

    diary.down = False
    await sync.reload(settings_for(release2))  # the off entry first, then the rollback to 10
    assert diary.versions() == [("0", "10"), ("10", "11"), ("11", "10")]
    assert surface_modes() == ("live", "live") and diary.rows[-1]["rollback"] is True


async def test_turning_a_surface_back_on_waits_for_its_diary_entry(path: Path, diary: Diary, caplog) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings)

    path.write_text(FEED_ON, encoding="utf-8")
    with caplog.at_level(logging.INFO):
        await sync.reload(settings)
        await sync.reload(settings)
    assert surface_modes() == ("off", "live") and live.current().config_version == "11"
    assert len(alerts(caplog, "settings_change_not_recorded")) == 1

    diary.down = False
    await sync.reload(settings)
    assert surface_modes() == ("live", "live") and live.current().config_version == "12"
    assert diary.versions() == [("0", "10"), ("10", "11"), ("11", "12")]
    assert diary.rows[2]["follows"] == diary.rows[1]["_id"]  # after the off entry, in order


async def test_a_surface_off_while_an_earlier_one_waits_is_kept_in_order(path: Path, diary: Diary) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings)
    path.write_text(surfaces(version(FILE, 12), "off", "off"), encoding="utf-8")
    await sync.reload(settings)
    assert surface_modes() == ("off", "off")
    assert [e["config_version"] for e in state.pending(settings)] == ["11", "12"]

    diary.down = False
    await sync.reload(settings)
    assert diary.versions() == [("0", "10"), ("10", "11"), ("11", "12")]
    assert diary.rows[2]["follows"] == diary.rows[1]["_id"]


async def test_with_neither_the_diary_nor_the_state_directory_the_surface_stays_as_it_is(
    path: Path, diary: Diary, monkeypatch, caplog
) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    diary.down = True

    def unwritable(settings, entry):
        raise PermissionError("read-only disk")

    monkeypatch.setattr(state, "add_pending", unwritable)
    path.write_text(FEED_OFF, encoding="utf-8")
    with caplog.at_level(logging.INFO):
        await sync.reload(settings)
    assert surface_modes() == ("live", "live")
    assert alerts(caplog, "settings_change_not_recorded")


# --- 4. the state directory ------------------------------------------------------------


def test_the_state_directory_is_outside_the_code_on_servers_and_one_per_database(monkeypatch) -> None:
    monkeypatch.undo()  # the real defaults, not the test folder
    assert state.SERVER_DIR == Path("/var/lib/reco")
    assert state.directory(Settings(engine_env="test", ml_mongo_db="soco_engine_test")) == Path(
        "/var/lib/reco/soco_engine_test")
    assert state.directory(Settings(ml_mongo_db="soco_engine_dev")) == ROOT / ".state" / "soco_engine_dev"
    assert state.directory(Settings(state_dir="/srv/x", ml_mongo_db="a/b")) == Path("/srv/x/a_b")


def test_the_state_dir_comes_from_reco_state_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RECO_STATE_DIR", str(tmp_path))
    assert Settings.from_env().state_dir == str(tmp_path)


async def test_a_pending_entry_file_is_whole_json_with_its_own_id(path: Path, diary: Diary) -> None:
    path.write_text(LIVE, encoding="utf-8")
    settings = settings_for(path)
    await sync.load_at_start(settings)
    diary.down = True
    path.write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings)

    folder = state.directory(settings) / state.PENDING
    [file] = list(folder.iterdir())  # no temporary file left behind
    content = json.loads(file.read_text(encoding="utf-8"))
    assert content["format"] == state.FORMAT and content["engine_database"] == settings.ml_mongo_db
    assert file.name.endswith(f"-{content['entry']['_id']}.json")
    assert content["entry"]["changed_at"]["$datetime"].startswith("20")
    assert (state.directory(settings) / state.LAST_RECORDED).exists()


# --- 5. a restart and a redeploy in new processes, the database really down ------------------


def _start_in_a_new_process(code_folder: Path, state_dir: Path) -> dict:
    """A new engine process from `code_folder`, with the engine database unreachable."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("ML_", "APP_", "SETTINGS_", "RECO_"))}
    environment.update({
        "ENGINE_ENV": "dev", "ML_MONGO_URI": "mongodb://127.0.0.1:1", "APP_MONGO_URI": "mongodb://127.0.0.1:2",
        "ML_MONGO_DB": "reco_diary_check", "MONGO_TIMEOUT_SECONDS": "1", "RECO_STATE_DIR": str(state_dir),
        "SETTINGS_FILE": str(code_folder / "settings" / "engine.toml"), "PYTHONPATH": str(code_folder),
    })
    script = (
        "import asyncio, json, logging\n"
        "logging.disable(logging.CRITICAL)\n"
        "from reco.config import get_settings, live, sync\n"
        "from reco.store import connection\n"
        "async def main():\n"
        "    s = get_settings(); connection.init_client(s)\n"
        "    await sync.load_at_start(s)\n"
        "    t = live.current()\n"
        "    print(json.dumps({'config_version': t.config_version, 'feed': t.serving.surface_mode_feed,\n"
        "                      'product': t.serving.surface_mode_product, 'source': live.state().source,\n"
        "                      'code': sync.__file__}))\n"
        "asyncio.run(main())\n"
    )
    done = subprocess.run([sys.executable, "-c", script], cwd=code_folder, env=environment,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _release(tmp_path: Path, name: str, settings_text: str) -> Path:
    folder = tmp_path / name
    shutil.copytree(ROOT / "reco", folder / "reco", ignore=shutil.ignore_patterns("__pycache__"))
    (folder / "settings").mkdir()
    (folder / "settings" / "engine.toml").write_text(settings_text, encoding="utf-8")
    return folder


async def test_a_restart_and_a_redeploy_in_new_processes_with_the_database_down(
    tmp_path: Path, diary: Diary
) -> None:
    state_dir = tmp_path / "var-lib-reco"
    release1 = _release(tmp_path, "release1", LIVE)
    settings = Settings(settings_file=str(release1 / "settings" / "engine.toml"), state_dir=str(state_dir),
                        ml_mongo_db="reco_diary_check")
    await sync.load_at_start(settings)  # 10 recorded
    diary.down = True
    (release1 / "settings" / "engine.toml").write_text(FEED_OFF, encoding="utf-8")
    await sync.reload(settings)  # feed off at once; its entry waits on disk
    assert surface_modes() == ("off", "live")

    restarted = _start_in_a_new_process(release1, state_dir)
    assert (restarted["config_version"], restarted["feed"], restarted["product"]) == ("11", "off", "live")

    release2 = _release(tmp_path, "release2", LIVE)  # a redeploy: new code folder, the older file
    redeployed = _start_in_a_new_process(release2, state_dir)
    assert redeployed["code"].startswith(str(release2))
    assert (redeployed["config_version"], redeployed["feed"], redeployed["product"]) == ("11", "off", "live")
    assert redeployed["source"] == "state directory"

    # The database is back: the one entry is written once.
    diary.down = False
    await sync.reload(settings)
    assert diary.versions() == [("0", "10"), ("10", "11")]
    assert not state.pending(settings)


# --- 6. on a real database ------------------------------------------------------------------


@pytest.mark.mongo
async def test_on_a_database_a_dated_change_lands_and_a_replay_adds_nothing(store: Settings, tmp_path: Path) -> None:
    from reco.store.connection import ml_db

    changes = ml_db(store)["ml_config_changes"]
    await changes.drop()
    await writers.ensure_engine_collections(store)
    try:
        path = tmp_path / "engine.toml"
        path.write_text(version(FILE, 10).replace("test_accounts = []", DATED), encoding="utf-8")
        dated = store.model_copy(update={"settings_file": str(path)})
        await sync.load_at_start(dated)
        assert live.current().config_version == "10"

        row = await changes.find_one({"config_version": "10"})
        assert row["values"]["lists"]["test_accounts"][0]["expiry"] == "2026-12-31"
        latest = await writers.read_latest_config_change(dated)
        assert Tunables.model_validate(latest["values"]).lists.test_accounts[0].expiry == date(2026, 12, 31)

        for _ in range(5):  # the same entry replayed
            assert await writers.record_config_change(dated, dict(row)) is False
        assert await changes.count_documents({}) == 1
    finally:
        await changes.drop()
