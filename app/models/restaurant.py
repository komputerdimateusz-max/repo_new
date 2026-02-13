"""Restaurant-related ORM models."""

from datetime import datetime, time, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Time, UniqueConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Restaurant(Base):
    """Represents a marketplace restaurant."""

    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    opening_hours: Mapped[list["RestaurantOpeningHours"]] = relationship(back_populates="restaurant")
    location_mappings: Mapped[list["RestaurantLocation"]] = relationship(back_populates="restaurant")


class RestaurantOpeningHours(Base):
    """Ordering opening hours for a restaurant."""

    __tablename__ = "restaurant_opening_hours"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    ordering_open_time: Mapped[time] = mapped_column(Time, nullable=False)
    ordering_close_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="opening_hours")


class RestaurantLocation(Base):
    """Delivery coverage mapping between a restaurant and location."""

    __tablename__ = "restaurant_locations"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "location_id", name="uq_restaurant_location"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cut_off_time_override: Mapped[time | None] = mapped_column(Time, nullable=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="location_mappings")
