"""Show how users are split between the two methods of each slot (ENG-05). No database.

    .venv/bin/python scripts/show_assignment.py                      # 10,000 made-up ids
    .venv/bin/python scripts/show_assignment.py 64f1c0ffee0000000000abcd
    SETTINGS_FILE=/tmp/copy.toml .venv/bin/python scripts/show_assignment.py

Reads the settings file (SETTINGS_FILE, else settings/engine.toml) exactly as the
service does. With user ids, prints each one's bucket, method and policy_id per
slot; without, prints the share of 10,000 test ids on method two per slot next to
the split. The test ids are fixed, so two runs print the same numbers.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import live  # noqa: E402
from reco.slots.assignment import SLOT_NAMES, assign, policy_id  # noqa: E402


def main(user_ids: list[str]) -> int:
    path = os.environ.get("SETTINGS_FILE", "settings/engine.toml")
    read = live.read_file(path)
    if read.tunables is None:
        print(f"settings file rejected: {read.fault}")
        return 1
    tunables = read.tunables
    print(f"settings {path}: config_version {tunables.config_version}")
    if user_ids:
        for user_id in user_ids:
            for slot in SLOT_NAMES:
                a = assign(slot, user_id, tunables)
                print(f"  {user_id}  {slot:16} bucket {a.bucket:2}  {a.which:10} {a.method:22} {policy_id(a)}")
        return 0
    ids = [hashlib.sha1(f"test-user-{n}".encode()).hexdigest()[:24] for n in range(10_000)]
    for slot in SLOT_NAMES:
        split = getattr(tunables.slots, slot).split
        share = 100 * sum(assign(slot, i, tunables).which == "method_two" for i in ids) / len(ids)
        verdict = "within 2 points" if abs(share - split) <= 2 else "OUTSIDE 2 points"
        print(f"  {slot:16} split {split:2}  method two {share:5.2f}%  ({verdict})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
