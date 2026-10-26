"""The ml_ namespace guard. ST6.

The fourth of the five things not to do, and the only one a test can catch.
Needs no database: the guard runs before any connection is used.
"""

from __future__ import annotations

import pytest

from reco.store import writers
from reco.store.writers import NamespaceViolation, _collection


class _FakeDatabase(dict):
    """Stands in for an AsyncDatabase. Records what was asked for."""

    def __getitem__(self, name: str) -> str:
        return f"collection:{name}"


@pytest.mark.parametrize(
    "forbidden",
    [
        "users",
        "posts",
        "postevents",
        "registers",
        "orders",
        "interestScores",
        "trackings",
        "userevents",
        "ML_user_interest_scores",  # case matters -- the prefix is lowercase ml_
        "xml_user_scores",  # contains ml_ but is not prefixed with it
        "",
    ],
)
def test_write_to_non_ml_collection_raises(forbidden: str) -> None:
    with pytest.raises(NamespaceViolation):
        _collection(_FakeDatabase(), forbidden)


@pytest.mark.parametrize(
    "allowed",
    ["ml_user_interest_scores", "ml_post_scores", "ml_refresh_runs", "ml_"],
)
def test_write_to_ml_collection_allowed(allowed: str) -> None:
    assert _collection(_FakeDatabase(), allowed) == f"collection:{allowed}"


def test_non_string_collection_name_raises() -> None:
    """A None slipping through must not become the database's default handle."""
    with pytest.raises(NamespaceViolation):
        _collection(_FakeDatabase(), None)  # type: ignore[arg-type]


def test_guard_is_not_a_value_error() -> None:
    """A contract breach, not bad input.

    Writes are often wrapped in `except ValueError`. If the guard were a
    ValueError it would be swallowed there and the violation would go unseen --
    which is the same silent-failure shape as the empty catch in
    updateUserInterests.
    """
    with pytest.raises(NamespaceViolation) as exc:
        _collection(_FakeDatabase(), "users")

    assert not isinstance(exc.value, ValueError)


def test_every_write_path_goes_through_the_guard() -> None:
    """The rule is enforceable only if there is one door.

    Reads may address the collection directly; writes may not. If a new write
    function is added that calls ml_db(...)[name] itself, this fails.
    """
    import inspect

    for name in (
        "upsert_score",
        "upsert_user_scores",
        "delete_user_scores",
        "ensure_indexes",
        "ensure_engine_collections",
    ):
        function_source = inspect.getsource(getattr(writers, name))
        assert "_collection(" in function_source, (
            f"{name} must obtain its collection through _collection(), "
            f"otherwise the ml_ guard does not cover it"
        )
