"""Commission settings, merged per product. ENG-30 point 4 (for ENG-18, M6).

    rules = await load_commission(settings)        # raises CommissionUnreadable
    merged, sources = rules.for_product(product_id, seller_id)
    merged -> {"enabled": True, "poolPercent": 15.0, "minOrderAmount": 0.0, "holdDays": 7.0}

Build List v1.4 ENG-30 point 4: read commissionconfigs in full when the M6 job runs.
For each product, merge field by field: the built-in defaults on the Settings sheet,
then the platform row (scope platform, scopeId null), then the store row (scope
seller, scopeId = products.createdBy), then the product row (scope product, scopeId
= the product's id). Only fields present in a row overwrite. A field outside its
allowed range (poolPercent outside 0 to 50, a negative minOrderAmount, an enabled
value that is not true or false) is ignored and logged, and the level below
applies. scope and scopeId are unique together on the platform; if two rows ever
share them, the one with the later updatedAt wins and the duplicate is logged. If
commissionconfigs cannot be read, the M6 job does not run and the service owner is
alerted: the built-in defaults never stand in for rows that could not be read.
Collaboration rates are not used. influencerearnings is never read.

Settings "Commission rate": built-in defaults enabled true, poolPercent 10,
minOrderAmount 0, holdDays 7 (opportunity.commission_defaults).
Where the pack is silent (decided 19 Oct 2026): holdDays must be a number of 0 or
more, else it is ignored and logged like the others; a row with a scope other than
platform, seller or product is ignored and logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from reco.config import Settings, live
from reco.platform import fetch

logger = logging.getLogger("reco.commission")

FIELDS = ("enabled", "poolPercent", "minOrderAmount", "holdDays")
LEVELS = ("platform", "seller", "product")


class CommissionUnreadable(RuntimeError):
    """commissionconfigs could not be read: M6 does not run (the defaults never stand in)."""


def valid(field_name: str, value: Any) -> bool:
    if field_name == "enabled":
        return isinstance(value, bool)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if field_name == "poolPercent":
        return 0 <= value <= 50
    return value >= 0  # minOrderAmount and holdDays


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class CommissionRules:
    defaults: dict[str, Any]
    rows: dict[tuple[str, str | None], dict[str, Any]] = field(default_factory=dict)  # (scope, scopeId) -> row
    duplicates: int = 0
    unknown_scope: int = 0

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]], defaults: Mapping[str, Any]) -> CommissionRules:
        rules = cls(dict(defaults))
        for row in rows:
            scope = str(row.get("scope") or "").strip().lower()
            if scope not in LEVELS:
                rules.unknown_scope += 1
                logger.warning("commission row with an unknown scope ignored", extra={"scope": row.get("scope")})
                continue
            scope_id = None if scope == "platform" else (str(row["scopeId"]) if row.get("scopeId") is not None else None)
            key = (scope, scope_id)
            held = rules.rows.get(key)
            if held is not None:
                rules.duplicates += 1
                keep = row if _time(row.get("updatedAt")) > _time(held.get("updatedAt")) else held
                logger.warning("two commission rows share scope and scopeId; the later updatedAt wins",
                               extra={"scope": scope, "scope_id": scope_id})
                rules.rows[key] = dict(keep)
            else:
                rules.rows[key] = dict(row)
        return rules

    def for_product(self, product_id: str, seller_id: str | None) -> tuple[dict[str, Any], dict[str, str]]:
        """The merged settings for one product, and where each field came from
        (default, platform, seller or product)."""
        merged = dict(self.defaults)
        sources = {f: "default" for f in FIELDS}
        for level, scope_id in (("platform", None), ("seller", seller_id), ("product", product_id)):
            row = self.rows.get((level, str(scope_id) if scope_id is not None else None)) if (
                level == "platform" or scope_id) else None
            if not row:
                continue
            for name in FIELDS:
                if name not in row:
                    continue  # only fields present overwrite
                if valid(name, row[name]):
                    merged[name] = row[name]
                    sources[name] = level
                else:
                    logger.warning("commission field out of range ignored; the level below applies",
                                   extra={"scope": level, "scope_id": scope_id, "field": name, "value": row[name]})
        return merged, sources


def defaults_in_force() -> dict[str, Any]:
    d = live.current().opportunity.commission_defaults
    return {"enabled": d.enabled, "poolPercent": d.pool_percent, "minOrderAmount": d.min_order_amount,
            "holdDays": d.hold_days}


async def load_commission(settings: Settings) -> CommissionRules:
    """Every commissionconfigs row, read in full. Raises CommissionUnreadable when it
    cannot be read; the caller (the M6 job) then does not run and alerts."""
    try:
        rows = await fetch.read_commission_configs(settings)
    except Exception as exc:  # noqa: BLE001 - any read failure means the rows are unknown
        raise CommissionUnreadable(repr(exc)[:300]) from exc
    return CommissionRules.from_rows(rows, defaults_in_force())
