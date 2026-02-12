"""Order domain logic for cut-off validation and date resolution."""

from datetime import date, datetime, timedelta, time

from app.core.config import settings
from app.models.location import Location


class CutoffPassedError(Exception):
    """Raised when trying to place an order for today after the cut-off time."""


def resolve_location_cutoff_time(location: Location) -> time:
    """Return location-specific cut-off time or configured global default."""
    if location.cutoff_time is not None:
        return location.cutoff_time
    return settings.app_default_cutoff_time


def resolve_target_order_date(
    *,
    now: datetime,
    location: Location,
    order_for_next_day: bool,
) -> date:
    """Resolve order target date and enforce cut-off for same-day orders."""
    today: date = now.date()
    if order_for_next_day:
        return today + timedelta(days=1)

    cutoff_time: time = resolve_location_cutoff_time(location)
    if now.time() > cutoff_time:
        raise CutoffPassedError
    return today
