"""Time window helpers used for 'today' queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def today_window_local() -> tuple[datetime, datetime]:
    """Return today's UTC window boundaries.

    Orders are stored with UTC timestamps, so all "today" filtering must use UTC
    boundaries as well.
    """
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end

