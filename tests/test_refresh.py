"""The refresh, end to end, on the real generated dataset without a database.

The readers and the writer are stubbed, so this exercises everything between
them: grouping events by user, assembling each user's context, scoring,
normalising to shares, deciding who gets no score at all, and the shape of what
is handed to the store.

Proving it here rather than only against Mongo means the wiring is testable when
the cluster is down, which it has been.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from reco.config import Settings
from reco.slots.interest.events import ReadStats
from reco.store.scores import Method
from reco.jobs.refresh import refresh
from tests.test_method_a_expected import DEMO_DIR, adapt

TOLERANCE = 5e-6


def _load(name: str):
    path = DEMO_DIR / name
    if not path.exists():
        pytest.skip(f"demo dataset not found at {DEMO_DIR}; unpack reference/demo.zip")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dataset():
    meta = _load("ml_demo_meta.json")
    reference = datetime.fromisoformat(meta["reference_date"])

    grouped: dict[str, list] = {}
    for row in _load("ml_demo_events.json"):
        event = adapt(row, reference)
        if event is not None:
            grouped.setdefault(event.user_id, []).append(event)

    users = _load("ml_demo_users.json")
    orders = _load("ml_demo_orders.json")

    return {
        "meta": meta,
        "reference": reference,
        "events": grouped,
        "declared": {u["user_id"]: u.get("declared_interests", []) for u in users},
        "orders": {
            o["order_id"]: datetime.fromisoformat(o["placed_at"])
            for o in orders
            if o.get("placed_at")
        },
        "user_ids": sorted(
            {u["user_id"] for u in users} | set(grouped)
        ),
    }


@pytest.fixture
def wired(monkeypatch, dataset):
    """Readers answer from the JSON dataset; writes are captured, not sent."""
    from reco.platform import readers
    import reco.jobs.refresh as refresh_module

    written: dict[str, list] = {}

    async def fake_events(settings, reference_date=None):
        return dataset["events"], ReadStats(read=6361, unresolved_category=0)

    async def fake_declared(settings):
        return dataset["declared"]

    async def fake_orders(settings):
        return dataset["orders"]

    async def fake_user_ids(settings):
        return dataset["user_ids"]

    async def fake_upsert(settings, user_id, scores):
        written[user_id] = list(scores)
        return len(written[user_id])

    async def fake_sweep(settings, method, model_version, computed_at):
        # The real one deletes rows this run did not rewrite. Nothing is really
        # stored here, so there is nothing to sweep.
        return 0

    monkeypatch.setattr(readers, "read_events_by_user", fake_events)
    monkeypatch.setattr(readers, "read_all_declared_interests", fake_declared)
    monkeypatch.setattr(readers, "read_all_order_creation_times", fake_orders)
    monkeypatch.setattr(readers, "read_all_user_ids", fake_user_ids)
    monkeypatch.setattr(refresh_module, "upsert_user_scores", fake_upsert)
    monkeypatch.setattr(refresh_module, "remove_scores_older_than", fake_sweep)

    return written


@pytest.fixture
def settings() -> Settings:
    return Settings(data_profile="demo", model_version="test-1.0.0")


async def run(settings, dataset, method=Method.RECENCY_DECAY):
    return await refresh(settings, method=method, reference_date=dataset["reference"])


# --- the run record ---------------------------------------------------------


async def test_the_run_reports_what_it_did(wired, settings, dataset) -> None:
    """A refresh that fails silently is the commonest way a score stops being
    current. The run record is what makes that visible.
    """
    result = await run(settings, dataset)

    assert result.method == "recency_decay"
    assert result.model_version == "test-1.0.0"
    assert result.window == "all"
    assert result.users_seen == len(dataset["user_ids"])
    assert result.users_scored > 0
    assert result.scores_written > 0
    assert result.duration_seconds >= 0
    assert "scored" in result.summary()


async def test_every_user_is_either_scored_or_counted_as_unscored(
    wired, settings, dataset
) -> None:
    """No user may be silently skipped."""
    result = await run(settings, dataset)

    assert result.users_scored + result.users_with_no_score == result.users_seen


async def test_the_reversal_is_applied_and_aged(wired, settings, dataset) -> None:
    """205 orders exist, so the one reversal resolves to its order."""
    result = await run(settings, dataset)

    assert result.reversals_applied == 1
    assert result.reversals_unaged == 0


async def test_sub_threshold_views_are_counted_not_scored(
    wired, settings, dataset
) -> None:
    """U02 alone carries twelve. The counter is separate from the reader's."""
    result = await run(settings, dataset)

    assert result.sub_threshold_views >= 12


async def test_no_coherence_failures(wired, settings, dataset) -> None:
    """Under the corrected reversal a negative raw cannot occur."""
    result = await run(settings, dataset)

    assert result.coherence_failures == []


# --- what lands in the store ------------------------------------------------


async def test_shares_sum_to_one_for_every_scored_user(
    wired, settings, dataset
) -> None:
    await run(settings, dataset)

    for user_id, scores in wired.items():
        total = sum(s.share for s in scores)
        assert total == pytest.approx(1.0, abs=1e-9), f"{user_id} sums to {total}"


async def test_every_row_carries_the_four_metadata_fields(
    wired, settings, dataset
) -> None:
    await run(settings, dataset)

    for scores in wired.values():
        for score in scores:
            document = score.to_document()
            for field in ("method", "model_version", "window", "computed_at"):
                assert document[field] is not None


async def test_raw_includes_the_declared_floor(wired, settings, dataset) -> None:
    """DS-008 section 4.2: raw = floor + events.

    NOTE: the data checks compare the stored raw against `expected_raw`, which is
    the EVENT COMPONENT ONLY. Check 8 predicts this exact difference in its own
    failure message. Flagged as a contradiction to settle with Kala, not worked
    around here -- the specification is followed and the mismatch is left visible.
    """
    await run(settings, dataset)

    u20 = {s.category: s.raw for s in wired["U20"]}
    expected_events_only = dataset["meta"]["expected_raw"]["U20"]["Shoes & Footwear"]

    assert u20["Shoes & Footwear"] == pytest.approx(
        expected_events_only + 10.0, abs=TOLERANCE
    )


async def test_a_user_with_declared_interests_and_no_events_is_scored(
    wired, settings, dataset
) -> None:
    """Rung 2, and the common case at launch -- everyone who signed up on day one
    has picked interests and done nothing. U07 must reach the store.
    """
    assert "U07" not in dataset["events"]

    await run(settings, dataset)

    scores = {s.category: s.share for s in wired["U07"]}
    assert len(scores) == 6
    assert sum(scores.values()) == pytest.approx(1.0)


async def test_a_user_with_nothing_at_all_is_not_stored(
    wired, settings, dataset
) -> None:
    """Rung 3. Storing a uniform share would be indistinguishable from a genuine
    even spread and would hide that the user is unknown.
    """
    result = await run(settings, dataset)

    assert "U11" not in wired
    assert result.users_with_no_score >= 1


async def test_event_count_is_per_category(wired, settings, dataset) -> None:
    """U03's three categories each came from the same events, so each carries the
    full count rather than a third of it.
    """
    await run(settings, dataset)

    counts = {s.category: s.event_count for s in wired["U03"]}
    assert len(set(counts.values())) == 1
    assert all(c > 0 for c in counts.values())


# --- the decay-off run ------------------------------------------------------


async def test_decay_off_is_stored_under_its_own_method(
    wired, settings, dataset
) -> None:
    """Both runs are in the store at once for step 4's side-by-side.

    They must not share a method value: the checks compare every row under
    `recency_decay` against the decay-on expectations, so decay-off rows written
    under that name read as wrong answers rather than as a different question.
    """
    result = await run(settings, dataset, method=Method.RECENCY_DECAY_NO_DECAY)

    assert result.method == "recency_decay_h_inf"
    assert all(
        s.method == Method.RECENCY_DECAY_NO_DECAY
        for scores in wired.values()
        for s in scores
    )


async def test_decay_off_reorders_u04(wired, settings, dataset) -> None:
    """The whole argument for decay, shown by removing it.

    U04 browsed Electronics heavily three months ago and Home & Living heavily in
    the last fortnight. With decay on, Home & Living leads. With it off, the
    older and larger Electronics history leads instead.
    """
    await run(settings, dataset, method=Method.RECENCY_DECAY)
    with_decay = {s.category: s.raw for s in wired["U04"]}

    wired.clear()
    await run(settings, dataset, method=Method.RECENCY_DECAY_NO_DECAY)
    without_decay = {s.category: s.raw for s in wired["U04"]}

    assert with_decay["Home & Living"] > with_decay["Electronics"]
    assert without_decay["Electronics"] > without_decay["Home & Living"]


async def test_decay_off_is_a_plain_weighted_sum(wired, settings, dataset) -> None:
    """Every factor is exactly 1, so nothing is aged at all -- which is why the
    scores come out larger than the decayed ones for every category.
    """
    await run(settings, dataset, method=Method.RECENCY_DECAY)
    decayed = {s.category: s.raw for s in wired["U01"]}

    wired.clear()
    await run(settings, dataset, method=Method.RECENCY_DECAY_NO_DECAY)
    flat = {s.category: s.raw for s in wired["U01"]}

    for category, value in decayed.items():
        assert flat[category] >= value - TOLERANCE
