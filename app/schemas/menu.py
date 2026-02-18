"""Menu schemas for MVP API."""

from datetime import date as dt_date

from pydantic import BaseModel, ConfigDict, Field


class MenuItemCreate(BaseModel):
    name: str
    description: str | None = None
    price: int = Field(ge=0)
    is_standard: bool = True
    is_active: bool = True


class MenuItemRead(BaseModel):
    id: int
    name: str
    description: str | None
    price: int
    is_standard: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class DailySpecialCreate(BaseModel):
    menu_item_id: int
    date: dt_date | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    is_active: bool = True


class DailySpecialRead(BaseModel):
    id: int
    menu_item_id: int
    date: dt_date | None
    weekday: int | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TodayMenuResponse(BaseModel):
    standard_items: list[MenuItemRead]
    specials: list[MenuItemRead]
