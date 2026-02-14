"""Location-related ORM models."""

from datetime import datetime, time, timezone

from sqlalchemy import Boolean, DateTime, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Location(Base):
    """Represents supported delivery location for a company."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(16), nullable=False, default="00-000")
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
