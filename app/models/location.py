"""Location-related ORM models."""

from datetime import datetime, time, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Location(Base):
    """Represents supported delivery location for a company."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delivery_time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    delivery_time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    cutoff_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="location")
    restaurant_mappings: Mapped[list["RestaurantLocation"]] = relationship()


class LocationRequest(Base):
    """Represents a restaurant request for a new location."""

    __tablename__ = "location_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
