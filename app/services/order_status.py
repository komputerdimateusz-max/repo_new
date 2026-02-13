"""Order status transition helpers."""

from __future__ import annotations

from datetime import datetime

from app.models.order import Order

ORDER_STATUSES: list[str] = ["pending", "confirmed", "prepared", "delivered", "cancelled"]

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"prepared", "cancelled"},
    "prepared": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


def can_transition(current: str, new: str) -> bool:
    """Return whether order can move from current to new status."""
    return new in ALLOWED_TRANSITIONS.get(current, set())


def set_status(order: Order, new_status: str, now: datetime) -> None:
    """Set status and update corresponding timestamps."""
    order.status = new_status
    order.status_updated_at = now

    if new_status == "confirmed":
        order.confirmed_at = now
    elif new_status == "prepared":
        order.prepared_at = now
    elif new_status == "delivered":
        order.delivered_at = now
    elif new_status == "cancelled":
        order.cancelled_at = now
