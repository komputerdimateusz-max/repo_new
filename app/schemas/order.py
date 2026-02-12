"""Order API schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class OrderItemPayload(BaseModel):
    """Single order item payload."""

    menu_item_id: int
    quantity: int = Field(default=1, ge=1)


class OrderCreate(BaseModel):
    """Create or replace today's order items."""

    items: list[OrderItemPayload]
    location_id: int | None = None
    order_for_next_day: bool = False


class OrderItemResponse(BaseModel):
    """Serialized order item."""

    menu_item_id: int
    quantity: int


class OrderResponse(BaseModel):
    """Serialized order."""

    order_id: int
    order_date: date
    status: str
    items: list[OrderItemResponse]


class UserOrderItemResponse(BaseModel):
    """Serialized order item enriched with menu details."""

    menu_item_id: int
    name: str
    quantity: int
    price_cents: int


class UserOrderResponse(BaseModel):
    """Serialized user order enriched with totals."""

    id: int
    order_date: date
    status: str
    items: list[UserOrderItemResponse]
    total_cents: int

    model_config = ConfigDict(from_attributes=True)
