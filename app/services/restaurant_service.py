"""Restaurant helpers for ordering flow and validation."""

from datetime import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.location import Location
from app.models.restaurant import Restaurant, RestaurantLocation, RestaurantOpeningHours


def get_active_restaurants_for_location(db: Session, location_id: int) -> list[Restaurant]:
    """Return active restaurants that actively deliver to location."""
    return (
        db.query(Restaurant)
        .join(RestaurantLocation, RestaurantLocation.restaurant_id == Restaurant.id)
        .filter(
            Restaurant.is_active.is_(True),
            RestaurantLocation.location_id == location_id,
            RestaurantLocation.is_active.is_(True),
        )
        .order_by(Restaurant.name.asc())
        .all()
    )


def get_opening_hours_for_restaurant(db: Session, restaurant_id: int) -> RestaurantOpeningHours | None:
    """Return currently active opening-hours row for restaurant."""
    return (
        db.query(RestaurantOpeningHours)
        .filter(
            RestaurantOpeningHours.restaurant_id == restaurant_id,
            RestaurantOpeningHours.is_active.is_(True),
        )
        .order_by(RestaurantOpeningHours.id.desc())
        .first()
    )


def is_ordering_open(db: Session, restaurant_id: int, now_value: time) -> tuple[bool, time, time]:
    """Check whether ordering is open for restaurant now."""
    opening = get_opening_hours_for_restaurant(db, restaurant_id)
    if opening is None:
        open_time = settings.app_order_open_time
        close_time = settings.app_order_close_time
    else:
        open_time = opening.ordering_open_time
        close_time = opening.ordering_close_time
    return open_time <= now_value < close_time, open_time, close_time


def get_effective_cutoff(db: Session, restaurant_id: int, location_id: int, location: Location | None = None) -> time:
    """Return per-restaurant/location cutoff override or fallback location/default cutoff."""
    mapping = (
        db.query(RestaurantLocation)
        .filter(
            RestaurantLocation.restaurant_id == restaurant_id,
            RestaurantLocation.location_id == location_id,
            RestaurantLocation.is_active.is_(True),
        )
        .first()
    )
    if mapping is not None and mapping.cut_off_time_override is not None:
        return mapping.cut_off_time_override

    if location is None:
        location = db.query(Location).filter(Location.id == location_id).first()

    if location is not None and location.cutoff_time is not None:
        return location.cutoff_time
    return settings.app_default_cutoff_time


def validate_restaurant_delivers_to_location(db: Session, restaurant_id: int, location_id: int) -> bool:
    """Validate that active restaurant can deliver to active location mapping."""
    mapping = (
        db.query(RestaurantLocation)
        .join(Restaurant, Restaurant.id == RestaurantLocation.restaurant_id)
        .filter(
            RestaurantLocation.restaurant_id == restaurant_id,
            RestaurantLocation.location_id == location_id,
            RestaurantLocation.is_active.is_(True),
            Restaurant.is_active.is_(True),
        )
        .first()
    )
    return mapping is not None
