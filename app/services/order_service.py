"""Order domain logic for cut-off validation and date resolution."""

from datetime import date, datetime, timedelta, time


class CutoffPassedError(Exception):
    """Raised when trying to place an order for today after the cut-off time."""


def resolve_target_order_date(
    *,
    now: datetime,
    cutoff_time: time,
    order_for_next_day: bool,
) -> date:
    """Resolve order target date and enforce cut-off for same-day orders."""
    today: date = now.date()
    if order_for_next_day:
        return today + timedelta(days=1)

    if now.time() > cutoff_time:
        raise CutoffPassedError
    return today
