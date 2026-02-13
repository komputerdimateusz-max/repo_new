"""Application settings helpers."""

from datetime import time

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

ORDERING_OPEN_TIME_KEY: str = "ordering_open_time"
ORDERING_CLOSE_TIME_KEY: str = "ordering_close_time"


def parse_hhmm_time(value: str) -> time:
    """Parse time from HH:MM format string."""
    parsed: time = time.fromisoformat(value)
    return time(hour=parsed.hour, minute=parsed.minute)


def is_within_order_window(now_time: time, open_time: time, close_time: time) -> bool:
    """Return True when now is inside same-day ordering window."""
    return open_time <= now_time < close_time


def get_order_window_times(
    db: Session,
    *,
    default_open_time: time,
    default_close_time: time,
) -> tuple[time, time]:
    """Read order window times from DB with fallback defaults."""
    rows: list[AppSetting] = (
        db.query(AppSetting)
        .filter(AppSetting.key.in_([ORDERING_OPEN_TIME_KEY, ORDERING_CLOSE_TIME_KEY]))
        .all()
    )
    values: dict[str, str] = {row.key: row.value for row in rows}

    try:
        open_time: time = parse_hhmm_time(values.get(ORDERING_OPEN_TIME_KEY, ""))
    except ValueError:
        open_time = default_open_time

    try:
        close_time: time = parse_hhmm_time(values.get(ORDERING_CLOSE_TIME_KEY, ""))
    except ValueError:
        close_time = default_close_time

    return open_time, close_time


def save_order_window_times(db: Session, *, open_time: time, close_time: time) -> None:
    """Persist order window settings in app settings table."""
    open_value: str = open_time.strftime("%H:%M")
    close_value: str = close_time.strftime("%H:%M")

    for key, value in (
        (ORDERING_OPEN_TIME_KEY, open_value),
        (ORDERING_CLOSE_TIME_KEY, close_value),
    ):
        setting: AppSetting | None = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting is None:
            setting = AppSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value

    db.commit()
