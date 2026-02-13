"""Menu ORM models."""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MenuItem(Base):
    """Legacy menu entry model kept for backwards compatibility."""

    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_standard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CatalogItem(Base):
    """Persistent dish available in the catalog."""

    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_standard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    daily_items: Mapped[list["DailyMenuItem"]] = relationship(back_populates="catalog_item")


class DailyMenuItem(Base):
    """Activation row that enables catalog items for a specific day."""

    __tablename__ = "daily_menu_items"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id",
            "menu_date",
            "catalog_item_id",
            name="uq_daily_menu_restaurant_date_catalog_item",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True, index=True)
    menu_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    catalog_item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    catalog_item: Mapped[CatalogItem] = relationship(back_populates="daily_items")
