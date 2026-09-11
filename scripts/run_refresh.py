"""Run a refresh and write the scores.

    python scripts/run_refresh.py                      # age from now
    python scripts/run_refresh.py --as-of-dataset      # age from the dataset's
                                                       # own reference date

`--as-of-dataset` reads `reference_date` out of ml_demo_meta.json and decays from
that instant instead of from the clock. It is what reproduces the generator's
expected values exactly. Without it, a dataset built on Monday and scored on
Thursday ages every event three days further, and U18's ninety-day cliff moves.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.data import mongo  # noqa: E402
from reco.data.writers import ensure_indexes  # noqa: E402
from reco.domain.scores import Method  # noqa: E402
from reco.refresh import refresh  # noqa: E402

META = ROOT / "reference" / "demo" / "ml_demo_meta.json"


def dataset_reference_date() -> datetime:
    if not META.exists():
        raise SystemExit(f"{META} not found; cannot read the reference date.")
    meta = json.loads(META.read_text(encoding="utf-8"))
    return datetime.fromisoformat(meta["reference_date"])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--as-of-dataset",
        action="store_true",
        help="decay from ml_demo_meta.reference_date rather than from now",
    )
    parser.add_argument(
        "--method",
        default=Method.RECENCY_DECAY.value,
        help="which method to run: recency_decay or recency_decay_h_inf",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level="INFO", format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )

    settings = get_settings()
    reference = dataset_reference_date() if args.as_of_dataset else None

    print(f"profile          {settings.data_profile}")
    print(f"reading          {settings.events_collection}")
    print(f"writing          {settings.scores_collection}")
    print(f"model_version    {settings.model_version}")
    print(f"half life        {settings.decay_half_life_days} days (P-04)")
    print(f"anchored at      {reference or 'now'}")
    print()

    mongo.init_clients(settings)
    try:
        await ensure_indexes(settings)
        run = await refresh(
            settings,
            method=Method(args.method),
            reference_date=reference,
        )
    finally:
        await mongo.close_clients()

    print()
    print(run.summary())


if __name__ == "__main__":
    asyncio.run(main())
