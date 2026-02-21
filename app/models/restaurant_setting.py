"""Restaurant settings model for single-restaurant ordering."""

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RestaurantSetting(Base):
    """Singleton settings row (id=1)."""

    __tablename__ = "restaurant_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    cut_off_time: Mapped[str] = mapped_column(String(5), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cutlery_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    delivery_window_start: Mapped[str] = mapped_column(String(5), nullable=False)
    delivery_window_end: Mapped[str] = mapped_column(String(5), nullable=False)
