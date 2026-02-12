"""Menu API schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class MenuItemCreate(BaseModel):
    """Payload for creating menu item."""

    menu_date: date
    name: str
    description: str | None = None
    price_cents: int = Field(ge=0)
    is_active: bool = True


class MenuItemResponse(BaseModel):
    """Serialized menu item."""

    id: int
    menu_date: date
    name: str
    description: str | None
    price_cents: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
