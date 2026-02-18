"""Business services for single-restaurant catering MVP."""

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DailySpecial, MenuItem, Restaurant


def get_or_create_restaurant(db: Session) -> Restaurant:
    """Return the single restaurant row, creating one when missing."""
    restaurant = db.scalar(select(Restaurant).limit(1))
    if restaurant is None:
        restaurant = Restaurant(name="Main Restaurant", cut_off_time=settings.app_default_cutoff_time)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
    return restaurant


def ordering_open(db: Session, now: datetime | None = None) -> bool:
    """Check whether current server time is before global cut-off."""
    current = now or datetime.now()
    restaurant = get_or_create_restaurant(db)
    return current.time().replace(second=0, microsecond=0) <= restaurant.cut_off_time


def todays_menu(db: Session, target_date: date | None = None) -> tuple[list[MenuItem], list[MenuItem]]:
    """Return standard menu and today's active specials.

    Specific date specials override weekday specials for the same menu item.
    """
    menu_date = target_date or date.today()
    weekday = menu_date.weekday()

    standard_items = db.scalars(
        select(MenuItem).where(MenuItem.is_standard.is_(True), MenuItem.is_active.is_(True)).order_by(MenuItem.id)
    ).all()

    date_specials = db.scalars(
        select(DailySpecial).where(DailySpecial.date == menu_date, DailySpecial.is_active.is_(True))
    ).all()
    weekday_specials = db.scalars(
        select(DailySpecial).where(
            DailySpecial.date.is_(None),
            DailySpecial.weekday == weekday,
            DailySpecial.is_active.is_(True),
        )
    ).all()

    date_menu_ids = {special.menu_item_id for special in date_specials}
    merged_special_ids = date_menu_ids | {special.menu_item_id for special in weekday_specials if special.menu_item_id not in date_menu_ids}

    if not merged_special_ids:
        return standard_items, []

    special_items = db.scalars(
        select(MenuItem).where(MenuItem.id.in_(merged_special_ids), MenuItem.is_active.is_(True)).order_by(MenuItem.id)
    ).all()
    return standard_items, special_items


def parse_cutoff(value: str) -> time:
    """Parse HH:MM input to time."""
    return time.fromisoformat(value)
