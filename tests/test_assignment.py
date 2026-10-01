"""ENG-05: each user's method, the same way every time.

The Build List's check:
    - the same user gets the same method across two restarts   test_same_method_across_restarts
    - changing a split changes assignment with no deploy       test_a_split_change_moves_users_with_no_deploy
    - over 10,000 test ids, the split is within 2 points       test_ten_thousand_ids_land_within_two_points
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys

import pytest
from bson import ObjectId

from reco.config import live
from reco.config.tunables import Tunables
from reco.slots.assignment import SLOT_NAMES, assign, assign_all, bucket, policy_id
from tests.conftest import put_in_force

USER = "64f1c0ffee0000000000abcd"


def test_the_bucket_is_sha256_of_slot_and_user_first_8_hex_mod_100() -> None:
    expected = int(hashlib.sha256(f"interest:{USER}".encode()).hexdigest()[:8], 16) % 100
    assert bucket("interest", USER) == expected
    assert 0 <= expected <= 99


def test_each_slot_hashes_separately() -> None:
    """The slot name is in the hash, so the three slots don't move together."""
    ids = [str(ObjectId()) for _ in range(500)]
    same = sum(bucket("interest", i) == bucket("product_ranking", i) for i in ids)
    assert same < 50


def test_below_the_split_is_method_two() -> None:
    put_in_force({"slots.interest.split": 50})
    for i in (str(ObjectId()) for _ in range(200)):
        a = assign("interest", i)
        assert (a.which == "method_two") == (a.bucket < 50)
        assert a.method == ("time_windows" if a.which == "method_two" else "recency_decay")


def test_same_method_across_restarts() -> None:
    """A fresh Python process (a restart, with a new hash() salt) gives the same answers."""
    ids = [str(ObjectId()) for _ in range(50)]
    here = [assign_all(i)[s].method for i in ids for s in SLOT_NAMES]
    script = (
        "import sys, json; from reco.slots.assignment import assign_all, SLOT_NAMES;"
        "ids = json.loads(sys.argv[1]);"
        "print(json.dumps([assign_all(i)[s].method for i in ids for s in SLOT_NAMES]))"
    )
    import json

    runs = [
        json.loads(subprocess.run([sys.executable, "-c", script, json.dumps(ids)], capture_output=True, text=True, check=True).stdout)
        for _ in range(2)
    ]
    assert runs[0] == runs[1] == here


def test_a_split_change_moves_users_with_no_deploy() -> None:
    ids = [str(ObjectId()) for _ in range(2000)]
    put_in_force({"slots.interest.split": 50})
    before = sum(assign("interest", i).which == "method_two" for i in ids)
    put_in_force({"slots.interest.split": 10, "config_version": "next"})
    after = [assign("interest", i) for i in ids]
    assert sum(a.which == "method_two" for a in after) < before
    assert all(a.config_version == "next" for a in after)


@pytest.mark.parametrize("split", [50, 25, 10, 0])
def test_ten_thousand_ids_land_within_two_points(split: int) -> None:
    put_in_force({f"slots.{slot}.split": split for slot in SLOT_NAMES})
    ids = [str(ObjectId()) for _ in range(10_000)]
    for slot in SLOT_NAMES:
        share = 100 * sum(assign(slot, i).which == "method_two" for i in ids) / len(ids)
        assert abs(share - split) <= 2, (slot, share)


def test_missing_settings_give_everyone_the_default_and_log_it(caplog) -> None:
    class NoSlots:
        config_version = "2"
        slots = None

    with caplog.at_level(logging.ERROR, logger="reco.slots"):
        a = assign("interest", USER, NoSlots())  # type: ignore[arg-type]
    assert a.from_default and a.which == "method_one" and a.method == "recency_decay"
    assert any("slot settings missing" in r.message for r in caplog.records)


def test_policy_id_records_the_method() -> None:
    put_in_force({"slots.product_ranking.split": 0})
    a = assign("product_ranking", USER)
    assert policy_id(a) == f"cfg{live.current().config_version}.product_ranking-attribute_similarity"


def test_an_unknown_slot_is_refused() -> None:
    with pytest.raises(ValueError):
        assign("feed", USER)


def test_the_defaults_start_at_fifty_with_method_one_default() -> None:
    for slot in SLOT_NAMES:
        settings = getattr(Tunables().slots, slot)
        assert settings.split == 50 and settings.default_method == "method_one"
