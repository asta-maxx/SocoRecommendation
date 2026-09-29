"""Daily reconciliation of the new event log against the old collections. ENG-04 item 7.

For one UTC day, for each of the four pairs

    recommendation_request     vs  recommendationrequests
    recommendation_impression  vs  recommendationimpressions
    recommendation_click       vs  recommendationclicks
    content_feedback           vs  contentfeedbacks

three things must hold (Build List, ENG-04 item 7):

  1. counts match within 1%;
  2. the share of rows carrying a request_id, an item_id and a time matches
     within 1%;
  3. a sample of 100 events is matched one to one against the old rows on user,
     item and time to the second, and every matched pair agrees on request_id,
     position and item_type.

When all three hold for 7 days in a row, that day is recorded as the switch date
(read by the ENG-03 rule), and the log says to tell Aravinth to stop writing the
old collections. The old collections are kept.

Choices where the pack is silent, recorded here and in docs/engineering/ENG-04.md:
  - days are UTC calendar days, like the ENG-03 switch;
  - a pair with no rows on either side that day passes (there is nothing to
    disagree), but a day with no rows at all in any pair is not evidence: it
    does not count, and it breaks a run of matching days;
  - "within 1%" for counts means |new - old| <= 1% of the larger;
  - requests carry no item, so "item" is left out of a request's checks, and
    position and item_type are compared only where the records have them;
  - the sample is the first 100 new rows in a shuffle seeded by the day, so a
    re-run of the same day draws the same sample.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from reco.config import Settings
from reco.platform import records
from reco.platform.fetch import read_records
from reco.store import writers

logger = logging.getLogger("reco.events.reconcile")

#: kind -> (ml_events name, ENG-03 legacy record kind, the "item" field, parser)
PAIRS: dict[str, tuple[str, str, str | None]] = {
    "request": ("recommendation_request", "legacy_request", None),
    "impression": ("recommendation_impression", "legacy_impression", "item_id"),
    "click": ("recommendation_click", "legacy_click", "item_id"),
    "content_feedback": ("content_feedback", "legacy_content_feedback", "target_id"),
}
PARSERS = {
    "request": records.parse_legacy_request,
    "impression": records.parse_legacy_impression,
    "click": records.parse_legacy_click,
    "content_feedback": records.parse_legacy_content_feedback,
}
#: Fields compared on each matched pair, where the record has them.
AGREE_ON = ("request_id", "position", "item_type")

SAMPLE_SIZE = 100
TOLERANCE = 0.01
DAYS_IN_A_ROW = 7

#: The old collections to stop writing once the switch date is fixed (ENG-04).
OLD_COLLECTIONS = (
    "recommendationrequests", "recommendationimpressions", "recommendationclicks",
    "recommendationengagements", "contentfeedbacks",
)


@dataclass
class PairResult:
    kind: str
    new_rows: int
    old_rows: int
    counts_match: bool
    share_new: float
    share_old: float
    shares_match: bool
    sampled: int
    sample_matched: int
    sample_agrees: bool
    problems: list[str] = field(default_factory=list)

    @property
    def holds(self) -> bool:
        return self.counts_match and self.shares_match and self.sample_agrees

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "holds": self.holds}


def _item(record: Any, item_field: str | None) -> str | None:
    return getattr(record, item_field) if item_field else None


def _complete(record: Any, item_field: str | None) -> bool:
    """Carries a request_id, an item (where the kind has one) and a time."""
    return bool(record.request_id) and record.at is not None and (
        item_field is None or bool(_item(record, item_field))
    )


def _second(record: Any) -> datetime | None:
    return record.at.replace(microsecond=0) if record.at else None


def compare(kind: str, new: list[Any], old: list[Any], day: date) -> PairResult:
    """The three ENG-04 tests for one pair on one day. Pure: records in, result out."""
    item_field = PAIRS[kind][2]
    problems: list[str] = []

    # 1. counts within 1% (of the larger)
    larger = max(len(new), len(old))
    counts_match = abs(len(new) - len(old)) <= TOLERANCE * larger
    if not counts_match:
        problems.append(f"counts differ: new {len(new)}, old {len(old)}")

    # 2. share of complete rows within 1%
    share_new = sum(_complete(r, item_field) for r in new) / len(new) if new else 0.0
    share_old = sum(_complete(r, item_field) for r in old) / len(old) if old else 0.0
    shares_match = abs(share_new - share_old) <= TOLERANCE
    if not shares_match:
        problems.append(f"complete-row share differs: new {share_new:.3f}, old {share_old:.3f}")

    # 3. a sample of up to 100, matched one to one on user, item, time to the second
    shuffled = list(new)
    random.Random(day.isoformat() + kind).shuffle(shuffled)
    sample = shuffled[:SAMPLE_SIZE]
    unused: dict[tuple, list[Any]] = {}
    for row in old:
        unused.setdefault((row.user_id, _item(row, item_field), _second(row)), []).append(row)
    matched = 0
    agrees = True
    for row in sample:
        candidates = unused.get((row.user_id, _item(row, item_field), _second(row)))
        if not candidates:
            problems.append(f"no old row for user {row.user_id}, item {_item(row, item_field)}, at {_second(row)}")
            agrees = False
            continue
        partner = candidates.pop(0)
        matched += 1
        for name in AGREE_ON:
            if hasattr(row, name) and getattr(row, name) != getattr(partner, name):
                problems.append(f"{name} differs: new {getattr(row, name)!r}, old {getattr(partner, name)!r}")
                agrees = False

    return PairResult(
        kind=kind, new_rows=len(new), old_rows=len(old), counts_match=counts_match,
        share_new=round(share_new, 4), share_old=round(share_old, 4), shares_match=shares_match,
        sampled=len(sample), sample_matched=matched, sample_agrees=agrees, problems=problems[:10],
    )


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def reconcile_day(settings: Settings, day: date) -> dict[str, Any]:
    """Compare one day, store the result, and fix the switch date after 7 matching days."""
    start, end = day_window(day)
    pairs: list[PairResult] = []
    for kind, (event_name, legacy_kind, _) in PAIRS.items():
        parse = PARSERS[kind]
        new = [parse(doc) for doc in await writers.read_events(settings, event_name, start, end)]
        try:
            old = await read_records(settings, legacy_kind, {"server_ts": {"$gte": start, "$lt": end}})
        except Exception:
            logger.exception("could not read the old %s rows", kind)
            old = []
        pairs.append(compare(kind, new, old, day))

    counted = any(p.new_rows or p.old_rows for p in pairs)
    holds = counted and all(p.holds for p in pairs)
    result = {
        "day": day.isoformat(),
        "counted": counted,
        "holds": holds,
        "pairs": {p.kind: p.as_dict() for p in pairs},
        "computed_at": datetime.now(timezone.utc),
    }
    await writers.record_reconciliation(settings, result)
    logger.info(
        "event reconciliation",
        extra={"day": result["day"], "holds": holds, "counted": counted,
               "failing": [p.kind for p in pairs if not p.holds]},
    )
    await maybe_fix_switch_date(settings, day)
    return result


async def maybe_fix_switch_date(settings: Settings, day: date) -> str | None:
    """If `day` completes 7 matching days in a row, record it as the switch date."""
    if await writers.read_switch_date(settings):
        return None
    run = [(day - timedelta(days=offset)).isoformat() for offset in range(DAYS_IN_A_ROW)]
    results = await writers.read_reconciliations(settings, run)
    if not all(results.get(d, {}).get("holds") for d in run):
        return None
    if await writers.record_switch_date(settings, day.isoformat(), sorted(run)):
        logger.warning(
            "event source switch date fixed; tell Aravinth to stop writing the old collections",
            extra={"switch_date": day.isoformat(), "old_collections": list(OLD_COLLECTIONS)},
        )
        return day.isoformat()
    return None


async def switch_date(settings: Settings) -> date | None:
    """The ENG-03 switch date, or None while the old collections are still the source."""
    recorded = await writers.read_switch_date(settings)
    return date.fromisoformat(recorded) if recorded else None
