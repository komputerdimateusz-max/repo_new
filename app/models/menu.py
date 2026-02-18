"""Menu models for standard and daily-special dishes."""

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MenuItem(Base):
    """Menu item maintained by restaurant."""

    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    is_standard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    specials: Mapped[list["DailySpecial"]] = relationship(back_populates="menu_item")


class DailySpecial(Base):
    """Date-based or weekday-based special assignment."""

    __tablename__ = "daily_specials"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weekday: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    menu_item: Mapped[MenuItem] = relationship(back_populates="specials")
