"""Order models for same-day customer orders."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Order(Base):
    """Customer order for today."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    """Snapshot of order line item."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_snapshot: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
