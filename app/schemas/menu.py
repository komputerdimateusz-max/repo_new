"""Menu and catalog API schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CatalogItemCreate(BaseModel):
    """Payload for creating catalog item."""

    name: str
    description: str | None = None
    price_cents: int = Field(ge=0)
    is_active: bool = True


class CatalogItemResponse(BaseModel):
    """Serialized catalog item."""

    id: int
    name: str
    description: str | None
    price_cents: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class DailyMenuActivationRequest(BaseModel):
    """Payload to activate/deactivate catalog item for day."""

    catalog_item_id: int
    menu_date: date | None = None
    is_active: bool = True


class DailyMenuItemResponse(BaseModel):
    """Serialized daily menu activation row with dish details."""

    daily_id: int
    catalog_item_id: int
    menu_date: date
    is_active: bool
    name: str
    description: str | None
    price_cents: int


class MenuItemCreate(BaseModel):
    """Backward-compatible payload, now creates catalog + activation."""

    menu_date: date
    name: str
    description: str | None = None
    price_cents: int = Field(ge=0)
    is_active: bool = True
