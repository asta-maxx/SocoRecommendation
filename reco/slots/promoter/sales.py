"""What became of an order, for M8. ENG-16 with ENG-30 points 5 to 8. Pure: no database.

    window, fallback = return_window_days(product, fallback_days)
    outcome = sale_outcome(order, now=..., window_days=window, rules=rules, open_requests=...)

A completed sale (Build List v1.4 ENG-16; Settings "Completed sale") is an order
that is Delivered (order_status); whose product's return window plus 2 days has
passed since the Delivered time (the first Delivered history event, ENG-30 point
5); that has no open return request (ENG-30 point 7); and that is not Returned,
Cancelled or Rejected. A Pending order older than 14 days counts as not completed.
A history that contradicts itself is left out of completed sales until resolved.

The outcomes:

    completed            a completed sale
    returned             order_status Returned (a return counts in full: partial
                         refunds are not modelled)
    cancelled, rejected  order_status Cancelled / Rejected
    open_return_request  Delivered, with a return request still open: not yet a
                         completed sale; it becomes one when the request ends
                         without a return and the window has passed
    in_return_window     Delivered, the window plus the buffer not yet passed
    history_conflict     the history contradicts itself (ENG-30 point 5): left out
    in_progress          not yet delivered, and not older than 14 days
    not_completed        not yet delivered and older than 14 days (a Pending order
                         older than commerce.pending_open_days)

FINAL outcomes (completed, cancelled, rejected, returned) are the orders that have
"reached a final state" for sales quality; the others count on neither side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from reco.platform.ids import as_utc
from reco.platform.records import status_is

COMPLETED = "completed"
FINAL = frozenset({COMPLETED, "cancelled", "rejected", "returned"})
BAD = frozenset({"cancelled", "rejected", "returned"})


@dataclass(frozen=True)
class SaleRules:
    delivered: str = "Delivered"
    cancelled: str = "Cancelled"
    rejected: str = "Rejected"
    returned: str = "Returned"
    buffer_days: float = 2
    pending_open_days: float = 14

    @classmethod
    def from_tunables(cls, tunables: Any) -> SaleRules:
        statuses = tunables.lists.order_status
        return cls(statuses.delivered, statuses.cancelled, statuses.rejected, statuses.returned,
                   tunables.commerce.return_buffer_days, tunables.commerce.pending_open_days)


def return_window_days(product: Any | None, fallback_days: float) -> tuple[float, bool]:
    """ENG-30 point 8: (the window in days, whether the fallback was used). The
    product's deliveryConfig.returnWindow; 0 when isReturnApplicable is false; the
    settings' fallback when the field is missing (or the product is not found)."""
    if product is not None and product.return_applicable is False:
        return 0.0, False
    if product is not None and product.return_window_days is not None and product.return_window_days >= 0:
        return float(product.return_window_days), False
    return float(fallback_days), True


def sale_outcome(
    order: Mapping[str, Any],
    *,
    now: datetime,
    window_days: float,
    rules: SaleRules,
    open_requests: set[str] | frozenset[str] = frozenset(),
) -> str:
    status = order.get("status")
    if order.get("is_returned") or status_is(status, rules.returned):
        return "returned"
    if status_is(status, rules.cancelled):
        return "cancelled"
    if status_is(status, rules.rejected):
        return "rejected"
    if order.get("history_conflict"):
        return "history_conflict"
    order_id = str(order.get("order_id") or order.get("_id") or "")
    if status_is(status, rules.delivered):
        if order_id in open_requests:
            return "open_return_request"
        delivered_at = as_utc(order.get("delivered_at"))
        if delivered_at is None:  # Delivered with no Delivered event: a conflict (ENG-30 point 5)
            return "history_conflict"
        if now >= delivered_at + timedelta(days=window_days + rules.buffer_days):
            return COMPLETED
        return "in_return_window"
    created = as_utc(order.get("created_at"))
    if created is not None and now - created > timedelta(days=rules.pending_open_days):
        return "not_completed"
    return "in_progress"
