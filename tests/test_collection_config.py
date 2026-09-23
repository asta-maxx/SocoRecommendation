"""Source and target collections are configuration, not constants.

One config value moves the whole pipeline between generated demo data and live
data. That is what removes the need for a demo branch: the demonstration runs
the same code as production, reading and writing different collections.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from reco.config import PROFILE_COLLECTIONS, Settings
from reco.platform import connection as platform_conn, readers
from reco.store import writers


def test_live_profile_reads_postevents_and_writes_the_live_store() -> None:
    s = Settings(data_profile="live")

    assert s.events_collection == "postevents"
    assert s.scores_collection == "ml_user_interest_scores"


def test_demo_profile_reads_and_writes_the_demo_collections() -> None:
    s = Settings(data_profile="demo")

    assert s.events_collection == "ml_demo_events"
    assert s.scores_collection == "ml_user_interest_scores_demo"


def test_demo_events_are_in_the_ml_namespace() -> None:
    """The generator cannot write to an application collection, so the demo
    event source has to live under ml_ like everything else this service owns.
    """
    assert PROFILE_COLLECTIONS["demo"]["events"].startswith("ml_")


def test_every_profile_writes_into_the_ml_namespace() -> None:
    for profile, collections in PROFILE_COLLECTIONS.items():
        assert collections["scores"].startswith("ml_"), profile


def test_demo_and_live_targets_are_distinct() -> None:
    """Scoring generated data into the live store would corrupt it, and nothing
    downstream could tell the two apart afterwards.
    """
    assert (
        PROFILE_COLLECTIONS["demo"]["scores"] != PROFILE_COLLECTIONS["live"]["scores"]
    )


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValidationError, match="data_profile"):
        Settings(data_profile="staging")


def test_explicit_collection_overrides_the_profile() -> None:
    """A deliberate one-off is allowed -- but it has to be said out loud."""
    s = Settings(data_profile="demo", scores_collection="ml_scratch_scores")

    assert s.events_collection == "ml_demo_events"  # still from the profile
    assert s.scores_collection == "ml_scratch_scores"


def test_non_ml_score_target_is_refused_at_startup() -> None:
    """writers.py refuses this at the point of writing. Refusing it here too
    means a bad configuration fails when the process starts rather than partway
    through a refresh run, hours later.
    """
    with pytest.raises(ValidationError, match="ml_ namespace"):
        Settings(scores_collection="postevents")


def test_env_selects_the_profile(monkeypatch) -> None:
    monkeypatch.setenv("DATA_PROFILE", "demo")

    s = Settings.from_env()

    assert s.events_collection == "ml_demo_events"
    assert s.scores_collection == "ml_user_interest_scores_demo"


# --- routing ----------------------------------------------------------------


def test_ml_source_routes_to_the_ml_connection(monkeypatch) -> None:
    """Reading ml_demo_events through the read-only application credential would
    query a collection that is not there and return nothing, without raising.
    """
    monkeypatch.setattr(platform_conn, "app_db", lambda s: "APP")
    monkeypatch.setattr(platform_conn, "ml_db", lambda s: "ML")
    s = Settings(data_profile="demo")

    assert platform_conn.source_db(s, s.events_collection) == "ML"


def test_application_source_routes_to_the_app_connection(monkeypatch) -> None:
    monkeypatch.setattr(platform_conn, "app_db", lambda s: "APP")
    monkeypatch.setattr(platform_conn, "ml_db", lambda s: "ML")
    s = Settings(data_profile="live")

    assert platform_conn.source_db(s, s.events_collection) == "APP"


# --- no hardcoded names anywhere else ---------------------------------------

NAMES = [
    "postevents",
    "ml_user_interest_scores",
    "ml_demo_events",
    "ml_user_interest_scores_demo",
    "ml_demo_users",
    "ml_demo_orders",
    "ml_demo_posts",
]


def _string_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal in a module that is not a docstring.

    Docstrings and comments are excluded deliberately: naming a collection while
    explaining why it is configuration is documentation, not a hardcoded name.
    What matters is a literal reaching executable code.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(id(node.body[0].value))

    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("name", NAMES)
def test_collection_names_appear_only_in_config(name: str) -> None:
    """The names live in exactly one place.

    If a method, reader or writer is later given a literal collection name, the
    demo and live paths diverge and a demo branch quietly becomes necessary
    again. This is the test that stops that.
    """
    package = Path(inspect.getfile(writers)).parents[1]

    offenders = [
        f"{path.relative_to(package)}:{line}"
        for path in package.rglob("*.py")
        if path.relative_to(package).parts[0] != "config"
        for line, literal in _string_literals(path)
        if name in literal
    ]

    assert not offenders, (
        f"{name!r} is hardcoded outside reco/config at {offenders}. "
        f"Collection names are configuration -- read them from Settings."
    )


def test_readers_take_every_collection_from_settings() -> None:
    """Each reader must name its collection through Settings, not a literal."""
    for name in (
        "read_one_event",
        "count_events",
        "read_user_events",
        "read_declared_interests",
        "read_order_creation_times",
        "_resolve_post_categories",
    ):
        source = inspect.getsource(getattr(readers, name))
        assert "settings." in source and "_collection" in source, (
            f"readers.{name} must resolve its collection from Settings"
        )


# --- four sources, not two --------------------------------------------------


@pytest.mark.parametrize("source", ["events", "users", "orders"])
def test_every_source_moves_with_the_profile(source: str) -> None:
    """Method A reads the declared floor from the user record and ages a
    reversal from the order's creation. If those sources do not move with the
    profile, the demo cannot read the floor without a special case -- and a
    special case built to make a demonstration work is a finding, not a shortcut.
    """
    live = PROFILE_COLLECTIONS["live"][source]
    demo = PROFILE_COLLECTIONS["demo"][source]

    assert live != demo, f"{source} does not change between profiles"
    assert demo.startswith("ml_"), f"demo {source} must be generated into ml_"


def test_the_demo_profile_has_no_posts_collection() -> None:
    """The generator writes three collections, not four.

    A demo event carries its categories on the row, so nothing is ever joined.
    Naming a posts collection here would name one that does not exist, and a
    read of it would return nothing without raising.
    """
    assert PROFILE_COLLECTIONS["demo"]["posts"] == ""
    assert PROFILE_COLLECTIONS["live"]["posts"] == "posts"


def test_settings_expose_every_source_plus_the_target() -> None:
    s = Settings(data_profile="demo")

    assert s.events_collection == "ml_demo_events"
    assert s.posts_collection == ""
    assert s.users_collection == "ml_demo_users"
    assert s.orders_collection == "ml_demo_orders"
    assert s.scores_collection == "ml_user_interest_scores_demo"


# --- shape, not just name ---------------------------------------------------


def test_the_two_profiles_declare_different_event_shapes() -> None:
    """Swapping a collection name does not make two documents compatible.

    A demo row carries its categories array; a postevent carries a post_id and
    the category is a join away. Naming this on Settings is what stops a method
    quietly assuming one shape.
    """
    assert Settings(data_profile="demo").event_shape == "flat"
    assert Settings(data_profile="live").event_shape == "postevent"
