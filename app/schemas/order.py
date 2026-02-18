"""Order schemas for MVP API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(default=1, ge=1)


class OrderCreate(BaseModel):
    customer_id: int
    items: list[OrderItemCreate]


class OrderItemRead(BaseModel):
    id: int
    menu_item_id: int
    quantity: int
    price_snapshot: float

    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    id: int
    customer_id: int
    created_at: datetime
    total_amount: float
    status: str
    items: list[OrderItemRead]

    model_config = ConfigDict(from_attributes=True)
