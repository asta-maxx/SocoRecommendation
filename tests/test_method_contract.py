"""The shared method contract. One test, every method on this surface.

MA2 says this is "enforced by the shared contract test, not by discipline". So
the rules live here rather than in a comment on each method:

  * no database access, no I/O of any kind
  * no mutation of its inputs
  * the same two arguments and the same return shape as every other method
  * every tunable read through the context, never as a module constant

Method B joins this list by being added to METHODS; nothing else changes.
"""

from __future__ import annotations

import ast
import inspect
from datetime import timedelta

import pytest

from reco.config import Settings
from reco.slots.interest.events import Event, EventType
from reco.slots.interest import interest_decay, interest_windows
from reco.slots.interest.context import ScoringContext
from reco.store.scores import utc_now
from tests.conftest import m1_tunables

#: Every scoring method. Method B is appended here when it exists.
METHODS = [interest_decay, interest_windows]

FORBIDDEN_IMPORTS = {
    "pymongo", "bson", "requests", "httpx", "urllib", "socket",
    "reco.platform", "reco.platform.connection", "reco.platform.readers",
    "reco.store", "reco.store.connection", "reco.store.writers",
    "open", "pathlib",
}


def make_ctx(**overrides) -> ScoringContext:
    fields = {
        "tunables": m1_tunables(),
        "declared_interests": ["Fashion & Apparel"],
        "order_created_at": {},
        "now": utc_now(),
    }
    fields.update(overrides)
    return ScoringContext(**fields)


def make_events(ctx: ScoringContext) -> list[Event]:
    return [
        Event(
            user_id="u1",
            event_type=EventType.VIEW,
            categories=["Fashion & Apparel"],
            timestamp=ctx.now - timedelta(days=3),
            view_duration_seconds=6.0,
        ),
        Event(
            user_id="u1",
            event_type=EventType.CLICK,
            categories=["Electronics", "Technology"],
            timestamp=ctx.now - timedelta(days=40),
        ),
    ]


# --- shape ------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_signature_is_events_and_ctx(method) -> None:
    parameters = list(inspect.signature(method.score).parameters)

    assert parameters == ["events", "ctx"], (
        f"{method.__name__}.score must take exactly (events, ctx) so the two "
        f"methods are interchangeable at the call site"
    )


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_returns_a_category_to_raw_map(method) -> None:
    ctx = make_ctx()
    raws, _ = method.score(make_events(ctx), ctx)

    assert isinstance(raws, dict)
    assert all(isinstance(k, str) for k in raws)
    assert all(isinstance(v, float) for v in raws.values())


# --- purity -----------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_no_io_imports(method) -> None:
    """A method that can reach a database cannot be replayed, cannot be compared
    against another method on identical inputs, and behaves differently
    depending on where it runs.
    """
    tree = ast.parse(inspect.getsource(method))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = {
        name
        for name in imported
        for bad in FORBIDDEN_IMPORTS
        if name == bad or name.startswith(bad + ".")
    }
    assert not offenders, f"{method.__name__} imports {offenders}"


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_does_not_read_the_clock(method) -> None:
    """The reference instant arrives as ctx.now.

    A method that called datetime.now() would produce a different score every
    run, could not reproduce the generated dataset's expected values, and would
    silently start counting U10's future events if it ran a day late.
    """
    source = inspect.getsource(method)

    assert "datetime.now(" not in source
    assert "utcnow(" not in source
    assert "time.time(" not in source


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_does_not_mutate_its_inputs(method) -> None:
    ctx = make_ctx()
    events = make_events(ctx)
    before = [e.model_dump() for e in events]

    method.score(events, ctx)

    assert [e.model_dump() for e in events] == before
    assert len(events) == 2


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_is_deterministic(method) -> None:
    ctx = make_ctx()
    events = make_events(ctx)

    first, _ = method.score(events, ctx)
    second, _ = method.score(events, ctx)

    assert first == second


# --- tunables reach it through the context ----------------------------------


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_no_hardcoded_parameter_values(method) -> None:
    """A method that hard-codes a tunable fails the contract.

    The launch values -- 30, 10, 3, and the P-06 weights -- must not appear as
    literals. If one does, changing configuration changes no score, and nothing
    fails loudly to say so.
    """
    tree = ast.parse(inspect.getsource(method))
    launch_values = {30, 30.0, 10, 10.0, 3, 3.0, 2, 2.0, 5, 5.0, 20, 20.0}

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value in launch_values and node.value not in (2, 2.0):
                offenders.append((node.lineno, node.value))

    assert not offenders, (
        f"{method.__name__} carries launch values as literals at {offenders}. "
        f"Read them from ctx.tunables. (Base 2 in the decay term is exempt: it "
        f"is the definition of a half-life, not a tunable.)"
    )


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_retuning_a_parameter_changes_the_score(method) -> None:
    """The proof that configuration is real rather than decorative."""
    base = make_ctx(declared_interests=[])
    events = make_events(base)

    default, _ = method.score(events, base)
    retuned, _ = method.score(
        events,
        make_ctx(
            declared_interests=[],
            tunables=m1_tunables({"interest.weights.qualified_view": 40.0}),
        ),
    )

    assert default["Fashion & Apparel"] != retuned["Fashion & Apparel"]


@pytest.mark.parametrize("method", METHODS, ids=lambda m: m.__name__)
def test_context_is_frozen(method) -> None:
    """So one method cannot change the inputs of the next on the same data."""
    ctx = make_ctx()

    with pytest.raises(Exception):
        ctx.tunables = {}
