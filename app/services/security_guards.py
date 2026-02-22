"""Centralized RBAC, cutoff and access guards for order operations."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Customer, Order, RestaurantSetting, User


def ensure_role(user: User, allowed_roles: set[str]) -> None:
    """Ensure user role is one of allowed roles."""
    if user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Forbidden")


def ensure_before_cutoff(order_date: date, now: datetime, cut_off_time: str) -> None:
    """Forbid creating/updating/cancelling today's orders after cutoff."""
    cut_h, cut_m = map(int, cut_off_time.split(":"))
    cutoff_dt = now.replace(hour=cut_h, minute=cut_m, second=0, microsecond=0)
    if order_date == now.date() and now > cutoff_dt:
        raise HTTPException(status_code=403, detail="Ordering window for today is closed.")
    if order_date < now.date():
        raise HTTPException(status_code=403, detail="Past order date is not allowed.")


def ensure_allowed_order_date(order_date: date, now: datetime, cut_off_time: str) -> None:
    """Enforce today-before-cutoff or tomorrow-after-cutoff date rule."""
    cut_h, cut_m = map(int, cut_off_time.split(":"))
    cutoff_dt = now.replace(hour=cut_h, minute=cut_m, second=0, microsecond=0)
    if now <= cutoff_dt and order_date != now.date():
        raise HTTPException(status_code=403, detail="Before cutoff you can place orders only for today.")
    if now > cutoff_dt and order_date != now.date() + timedelta(days=1):
        raise HTTPException(status_code=403, detail="After cutoff you can place orders only for tomorrow.")


def ensure_can_access_order(user: User, order: Order, db: Session) -> None:
    """Apply IDOR-safe ownership/role checks; return 404 to avoid leaking."""
    if user.role == "ADMIN":
        return
    if user.role == "RESTAURANT":
        return
    customer = db.query(Customer).filter(Customer.user_id == user.id).first()
    if customer is None or order.customer_id != customer.id:
        raise HTTPException(status_code=404, detail="Order not found")


def get_cutoff_time(db: Session) -> str:
    settings = db.get(RestaurantSetting, 1)
    if settings is None:
        raise HTTPException(status_code=500, detail="Restaurant settings are missing.")
    return settings.cut_off_time
