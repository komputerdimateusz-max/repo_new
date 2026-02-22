"""Schemas for MVP0 customer ordering API."""

from datetime import date as dt_date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    cut_off_time: str
    delivery_fee: Decimal
    cutlery_price: Decimal
    delivery_window_start: str
    delivery_window_end: str
    now_server: datetime


class CompanyRead(BaseModel):
    id: int
    name: str


class MeResponse(BaseModel):
    email: str
    name: str
    company_id: int | None
    postal_code: str | None


class MeUpdateRequest(BaseModel):
    company_id: int | None
    postal_code: str | None = None
    name: str = Field(min_length=1)


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
    order_date: dt_date | None = None
    notes: str | None = None
    payment_method: str
    cutlery: bool = False
    cutlery_price: Decimal = Decimal("0.00")
    items: list[OrderItemCreate]


class OrderCreateResponse(BaseModel):
    order_id: int
    status: str
    subtotal_amount: Decimal
    delivery_fee: Decimal
    cutlery: bool
    cutlery_price: Decimal
    extras_total: Decimal
    total_amount: Decimal
    delivery_window_start: str
    delivery_window_end: str
    payment_method: str
    created_at: datetime
    items: list["OrderTodayItemRead"]


class OrderTodayItemRead(BaseModel):
    menu_item_id: int | None
    qty: int
    price_snapshot: Decimal
    name: str | None = None


class OrderTodayRead(BaseModel):
    order_id: int
    company_id: int
    company_name: str | None = None
    customer_email: str
    status: str
    created_at: datetime
    subtotal_amount: Decimal
    delivery_fee: Decimal
    cutlery: bool
    cutlery_price: Decimal
    extras_total: Decimal
    total_amount: Decimal
    payment_method: str
    notes: str | None
    items: list[OrderTodayItemRead]


class AdminSettingsUpdateRequest(BaseModel):
    cut_off_time: str
    delivery_fee: Decimal
    cutlery_price: Decimal
    delivery_window_start: str
    delivery_window_end: str


class MenuItemAdminCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal
    category: str
    is_standard: bool = True
    is_active: bool = True
    image_url: str | None = None


class MenuItemAdminUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    category: str | None = None
    is_standard: bool | None = None
    is_active: bool | None = None
    image_url: str | None = None


class DailySpecialAdminCreate(BaseModel):
    menu_item_id: int
    date: dt_date | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    is_active: bool = True


class DailySpecialAdminUpdate(BaseModel):
    menu_item_id: int | None = None
    date: dt_date | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    is_active: bool | None = None


class OrderStatusUpdateRequest(BaseModel):
    status: str
