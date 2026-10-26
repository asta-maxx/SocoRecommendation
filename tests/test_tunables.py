"""ENG-02 items 3 and 4: the settings file, its rules, and the change log. SD-07, SD-09."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from reco.config import Settings, live, sync
from reco.config.tunables import Tunables

FILE = Path(__file__).resolve().parents[1] / "settings" / "engine.toml"
#: The committed file's version, and the next one (tests must not pin a number).
V = tomllib.loads(FILE.read_text())["config_version"]
NEXT = str(int(V) + 1)


# --- the file holds the Settings sheet ----------------------------------------------


#: The lists Allen maintains (Settings sheet "Lists": category map, spellings, exemptions,
#: test accounts). Their entries are added over time; every other value is the sheet's.
MAINTAINED = ("lists.category_map.", "lists.status_spellings.", "lists.exemptions", "lists.test_accounts")


def _sheet_values(values: dict) -> dict:
    return {k: v for k, v in values.items() if not k.startswith(MAINTAINED)}


def test_the_file_holds_every_setting_and_nothing_else() -> None:
    from_file = Tunables.model_validate(tomllib.loads(FILE.read_text()))

    assert set(_sheet_values(from_file.values())) == set(_sheet_values(Tunables().values()))


def test_the_file_matches_the_settings_sheet() -> None:
    """The committed file holds the pack's values (the maintained lists aside); only the
    version header differs."""
    from_file = Tunables.model_validate(tomllib.loads(FILE.read_text()))

    assert _sheet_values(from_file.values()) == _sheet_values(Tunables().values())
    assert from_file.config_version != Tunables().config_version


@pytest.mark.parametrize(
    "key,value",
    [
        ("interest.half_life_days", 30),
        ("interest.stale_after_hours", 48),
        ("interest.popularity_window_days", 30),
        ("interest.declared_floor", 10),
        ("interest.weights.like", 3),
        ("interest.weights.not_interested_or_hide", -5),
        ("events.qualified_view_seconds", 3),
        ("slots.interest.split", 50),
        ("retrieval.pool_size", 300),
        ("ranking.weights.interest", 0.35),
        ("serving.exploration_percent", 5),
        ("fraud.r01_actions_per_minute", 30),
    ],
)
def test_launch_values_are_the_settings_sheet(key: str, value) -> None:
    assert Tunables().values()[key] == value


def test_surfaces_start_off_until_their_checks_pass() -> None:
    """The sheet says live only if the checks pass (ENG-24); none has passed yet."""
    serving = Tunables().serving
    assert (serving.surface_mode_feed, serving.surface_mode_product) == ("off", "off")


# --- ranges ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,bad",
    [
        ("interest.half_life_days", 6),  # 7-180
        ("interest.half_life_days", 181),
        ("interest.stale_after_hours", 73),  # 1-72
        ("interest.weights.like", 51),  # -20 to 50
        ("interest.weights.not_interested_or_hide", -21),
        ("events.qualified_view_seconds", 11),  # 1-10
        ("slots.interest.split", 51),  # 0-50
        ("serving.exploration_percent", 6),  # 3-5
        ("serving.soco_be_timeout_ms", 99),  # 100-400
        ("retrieval.pool_size", 2001),  # 100-2000
        ("fraud.r04_min_orders", 9),  # 10-100
        ("serving.service_p95_target_ms", 250),  # fixed at 200
        ("ranking.max_per_author_per_page", 4),  # fixed at 3
        ("interest.declared_floor_decays", True),  # fixed: never decays
        ("serving.surface_mode_feed", "shadow"),  # off | live only; no shadow mode
    ],
)
def test_a_value_outside_the_sheet_is_refused(key: str, bad) -> None:
    with pytest.raises(ValidationError):
        Tunables().with_changes({key: bad})


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        Tunables().with_changes({"interest.window_weights": [0.5, 0.3, 0.3]})


@pytest.mark.parametrize(
    "key,other",
    [
        ("ranking.weights.interest", 0.5),
        ("retrieval.source_shares.follows", 0.5),
        ("product.weights.category", 0.9),
        ("promoter.weights.reach", 0.9),
        ("opportunity.weights.fit", 0.2),
        ("serving.exploration_percent", 3),
        ("serving.sample_random_percent", 20),
        ("serving.circuit_breaker_failures", 7),
        ("serving.page_dedup_hours", 12),
        ("events.sync_interval_minutes", 10),
        ("filters.feedback_hide_days", 60),
        ("filters.eligibility_refresh_minutes", 30),
        ("interest.refresh_cadence", "weekly"),
        ("interest.refresh_time_ist", "03:00"),
        ("product.price_band_fraction", 0.2),
        ("opportunity.sell_through_window_days", 60),
    ],
)
def test_settings_fixed_for_wave_1a_cannot_change(key: str, other) -> None:
    """Settings sheet: "A value changes only where the 'When it changes' column says
    so" -- rows marked "Fixed for Wave 1A" (and exploration, "Stays at 5%")."""
    with pytest.raises(ValidationError):
        Tunables().with_changes({key: other})


def test_window_bounds_must_ascend() -> None:
    with pytest.raises(ValidationError, match="ascending"):
        Tunables().with_changes({"interest.window_bounds_days": [30, 7, 90]})


def test_an_unknown_setting_is_refused() -> None:
    with pytest.raises(ValidationError):
        Tunables.model_validate({"serving": {"surface_mode_search": "live"}})


def test_no_connection_string_reaches_the_tunables() -> None:
    """SD-08: the file never holds a secret, so nothing in it looks like one."""
    assert "mongodb" not in str(Tunables().model_dump()).lower()


# --- what the M1 methods read ------------------------------------------------------


def test_m1_reads_the_settings_sheet_values() -> None:
    m1 = Tunables().m1()

    assert m1["P-04"] == 30
    assert m1["P-06"] == {"view": 2, "click": 5, "cart": 10, "purchase": 20, "search": 0.0,  # ENG-10 weights
                          "like": 3, "save": 4, "share": 4, "comment": 4, "business_follow": 5, "feedback": -5}
    assert m1["P-07"] == -5
    assert m1["P-08"] == 48
    assert m1["P-10"] == [7, 30, 90] and m1["P-11"] == [0.5, 0.3, 0.2]
    assert (m1["P-25"], m1["P-26"], m1["P-27"]) == (10, False, 30)


# --- reading the file ------------------------------------------------------------


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "engine.toml"
    path.write_text(text)
    return str(path)


def test_the_committed_file_reads_cleanly() -> None:
    read = live.read_file(str(FILE))
    assert read.fault is None and read.tunables is not None and read.fingerprint


def test_a_missing_file_is_a_fault_not_a_crash(tmp_path: Path) -> None:
    read = live.read_file(str(tmp_path / "nope.toml"))
    assert read.tunables is None and "cannot read" in read.fault


def test_broken_toml_is_a_fault(tmp_path: Path) -> None:
    read = live.read_file(_write(tmp_path, "config_version = \n[[["))
    assert read.tunables is None and "not valid TOML" in read.fault


def test_a_value_out_of_range_is_a_fault_naming_the_setting(tmp_path: Path) -> None:
    text = FILE.read_text().replace("half_life_days = 30", "half_life_days = 500")
    read = live.read_file(_write(tmp_path, text))
    assert read.tunables is None and "interest.half_life_days" in read.fault


# --- the decision rules ----------------------------------------------------------


def test_a_new_version_with_changes_is_accepted_and_diffed() -> None:
    before = Tunables()
    after = before.with_changes({"interest.half_life_days": 45}).model_copy(
        update={"config_version": "2", "changed_by": "Allen"}
    )

    decision = live.decide(before, after)

    assert decision.accept
    assert decision.changes == [{"key": "interest.half_life_days", "old": 30, "new": 45}]


def test_changed_values_without_a_new_version_are_refused() -> None:
    before = Tunables()
    after = before.with_changes({"interest.half_life_days": 45})

    decision = live.decide(before, after)

    assert not decision.accept and "raise config_version" in decision.fault


def test_the_same_file_again_changes_nothing() -> None:
    decision = live.decide(Tunables(), Tunables())
    assert not decision.accept and decision.fault is None


# --- load and reload, with the change log faked -------------------------------------


class FakeLog:
    """Stands in for ml_config_changes."""

    def __init__(self, latest=None) -> None:
        self.records: list[dict] = []
        self.latest = latest

    async def record(self, settings, record) -> bool:
        key = (record.get("previous_version"), record["config_version"], record.get("follows"))
        if any((r.get("previous_version"), r["config_version"], r.get("follows")) == key for r in self.records):
            return False
        record = {**record, "_id": f"entry{len(self.records) + 1}"}
        self.records.append(record)
        self.latest = record
        return True

    async def read_latest(self, settings):
        return self.latest


@pytest.fixture
def change_log(monkeypatch: pytest.MonkeyPatch) -> FakeLog:
    log = FakeLog()
    monkeypatch.setattr(sync.writers, "record_config_change", log.record)
    monkeypatch.setattr(sync.writers, "read_latest_config_change", log.read_latest)
    live.reset()
    yield log
    live.reset()


def _settings(path: str) -> Settings:
    return Settings(settings_file=path)


async def test_start_puts_the_file_in_force_and_records_it(tmp_path: Path, change_log: FakeLog) -> None:
    await sync.load_at_start(_settings(_write(tmp_path, FILE.read_text())))

    assert live.current().config_version == V
    assert live.state().source == "file"
    [record] = change_log.records
    assert (record["config_version"], record["previous_version"], record["changed_by"]) == (V, "0", "Allen")


async def test_a_change_is_picked_up_on_reload_and_logged(tmp_path: Path, change_log: FakeLog) -> None:
    path = _write(tmp_path, FILE.read_text())
    await sync.load_at_start(_settings(path))

    Path(path).write_text(
        FILE.read_text()
        .replace(f'config_version = "{V}"', f'config_version = "{NEXT}"')
        .replace('changed_by = "Allen"', 'changed_by = "Kala"')
        .replace("stale_after_hours = 48", "stale_after_hours = 60")
    )
    await sync.reload(_settings(path))

    assert live.current().interest.stale_after_hours == 60
    record = change_log.records[-1]
    assert record["changed_by"] == "Kala" and record["previous_version"] == V
    assert record["changes"] == [{"key": "interest.stale_after_hours", "old": 48, "new": 60}]
    assert record["values"]["interest"]["stale_after_hours"] == 60


async def test_a_broken_file_keeps_the_last_good_version(tmp_path: Path, change_log: FakeLog) -> None:
    path = _write(tmp_path, FILE.read_text())
    await sync.load_at_start(_settings(path))

    Path(path).write_text("this is = not [valid")
    await sync.reload(_settings(path))

    assert live.current().config_version == V  # still in force
    assert len(change_log.records) == 1  # nothing recorded for the broken file


async def test_a_change_without_a_new_version_is_refused_on_reload(tmp_path: Path, change_log: FakeLog) -> None:
    path = _write(tmp_path, FILE.read_text())
    await sync.load_at_start(_settings(path))

    Path(path).write_text(FILE.read_text().replace("half_life_days = 30", "half_life_days = 45"))
    await sync.reload(_settings(path))

    assert live.current().interest.half_life_days == 30


async def test_no_good_version_ever_means_the_defaults(tmp_path: Path, change_log: FakeLog) -> None:
    await sync.load_at_start(_settings(_write(tmp_path, "broken = [")))

    assert live.current() == Tunables()
    assert live.state().source == "defaults"


async def test_a_broken_file_at_start_falls_back_to_the_last_recorded_version(
    tmp_path: Path, change_log: FakeLog
) -> None:
    earlier = Tunables().with_changes({"interest.half_life_days": 40}).model_copy(
        update={"config_version": "7", "changed_by": "Allen"}
    )
    change_log.latest = {"config_version": "7", "values": earlier.model_dump()}

    await sync.load_at_start(_settings(_write(tmp_path, "broken = [")))

    assert live.current().config_version == "7"
    assert live.current().interest.half_life_days == 40
    assert live.state().source == "engine database"


async def test_a_recorded_version_in_an_older_shape_does_not_stop_the_start(
    tmp_path: Path, change_log: FakeLog
) -> None:
    """v1.4 changed the order-history map's values. A settings copy recorded before
    that no longer reads: the engine starts on the file, and that copy is no fallback."""
    old = Tunables().model_dump()
    old["lists"]["tracking_stages"]["payment completed"] = "paid"  # a v1.3 value
    change_log.latest = {"config_version": "3", "values": old}

    await sync.load_at_start(_settings(_write(tmp_path, FILE.read_text())))
    assert live.current().config_version == V and live.state().source == "file"

    change_log.latest = {"config_version": "3", "values": old}  # the old copy is the latest again
    await sync.load_at_start(_settings(_write(tmp_path, "broken = [")))
    assert live.state().source == "defaults"  # not the unreadable copy


async def test_a_rollback_is_recorded_too(tmp_path: Path, change_log: FakeLog) -> None:
    """Kala F5 (16 Oct): every version put in force is in the diary, a return to a
    lower version too, marked as a rollback."""
    path = _write(tmp_path, FILE.read_text())
    await sync.load_at_start(_settings(path))
    changed = (FILE.read_text().replace(f'config_version = "{V}"', f'config_version = "{NEXT}"')
               .replace("popularity_window_days = 30", "popularity_window_days = 45"))
    Path(path).write_text(changed)
    await sync.reload(_settings(path))
    Path(path).write_text(FILE.read_text())  # back to V
    await sync.reload(_settings(path))

    assert live.current().config_version == V
    assert [(r["previous_version"], r["config_version"], r["rollback"]) for r in change_log.records] == [
        ("0", V, False), (V, NEXT, False), (NEXT, V, True)]
    back = change_log.records[-1]
    assert back["changes"] == [{"key": "interest.popularity_window_days", "old": 45, "new": 30}]

    # And the same forward change again is a new entry, not a duplicate.
    Path(path).write_text(changed)
    await sync.reload(_settings(path))
    assert len(change_log.records) == 4


async def test_the_same_version_as_recorded_is_not_recorded_twice(tmp_path: Path, change_log: FakeLog) -> None:
    """The API and a job both start on version 1: only one record."""
    path = _write(tmp_path, FILE.read_text())
    await sync.load_at_start(_settings(path))
    await sync.load_at_start(_settings(path))

    assert [r["config_version"] for r in change_log.records] == [V]


# --- the change log in a real database -------------------------------------------


@pytest.mark.mongo
async def test_the_change_log_keeps_one_record_per_version(store: Settings) -> None:
    from reco.store import writers
    from reco.store.connection import ml_db
    from reco.store.scores import utc_now

    await ml_db(store)["ml_config_changes"].drop()
    await writers.ensure_engine_collections(store)
    try:
        first = {"config_version": "1", "changed_at": utc_now(), "values": Tunables().model_dump()}
        assert await writers.record_config_change(store, first) is True
        assert await writers.record_config_change(store, first) is False  # another process got there first

        latest = await writers.read_latest_config_change(store)
        assert latest["config_version"] == "1"
        assert Tunables.model_validate(latest["values"]) == Tunables()
    finally:
        await ml_db(store)["ml_config_changes"].drop()
