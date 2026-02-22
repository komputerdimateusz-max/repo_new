"""Order models for same-day customer orders."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Order(Base):
    """Customer order for today."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    order_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    customer_edit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    cutlery: Mapped[bool] = mapped_column(nullable=False, default=False)
    cutlery_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    extras_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    company: Mapped["Company"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("uq_orders_customer_date_fingerprint", "customer_id", "order_date", "order_fingerprint", unique=True),
        Index("uq_orders_order_number", "order_number", unique=True),
        Index("uq_orders_order_date_seq", "order_date", "order_seq", unique=True),
    )


class OrderItem(Base):
    """Snapshot of order line item."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    menu_item_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship(back_populates="order_items")
