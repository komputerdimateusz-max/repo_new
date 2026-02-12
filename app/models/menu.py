"""Menu ORM model."""

from datetime import date

from sqlalchemy import Boolean, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MenuItem(Base):
    """Represents a single menu entry for a specific day."""

    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
