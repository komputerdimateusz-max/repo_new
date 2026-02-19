"""Schemas for MVP0 customer ordering API."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    cut_off_time: str
    delivery_fee: Decimal
    delivery_window_start: str
    delivery_window_end: str
    now_server: datetime


class CompanyRead(BaseModel):
    id: int
    name: str


class MenuItemTodayRead(BaseModel):
    id: int
    name: str
    description: str | None
    price: Decimal
    category: str
    badge: str | None = None
    image_url: str | None = None


class MenuTodayResponse(BaseModel):
    date: str
    cut_off_time: str
    categories: list[str]
    active_category: str | None
    items: list[MenuItemTodayRead]


class OrderItemCreate(BaseModel):
    menu_item_id: int
    qty: int = Field(ge=1)


class OrderCreateRequest(BaseModel):
    customer_email: str
    company_id: int
    notes: str | None = None
    payment_method: str
    items: list[OrderItemCreate]


class OrderCreateResponse(BaseModel):
    order_id: int
    status: str
    total_amount: Decimal
    created_at: datetime


class OrderTodayItemRead(BaseModel):
    menu_item_id: int
    qty: int
    price_snapshot: Decimal


class OrderTodayRead(BaseModel):
    order_id: int
    company_id: int
    customer_email: str
    status: str
    created_at: datetime
    total_amount: Decimal
    items: list[OrderTodayItemRead]
