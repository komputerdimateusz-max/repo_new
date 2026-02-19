"""Daily menu and catalog endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.menu import CatalogItem, DailyMenuItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.menu import (
    CatalogItemCreate,
    CatalogItemResponse,
    DailyMenuActivationRequest,
    DailyMenuItemResponse,
    MenuItemCreate,
)
from app.services.menu_service import (
    activate_catalog_item_for_date,
    create_catalog_item,
    create_menu_item,
    list_available_catalog_items_for_date,
    list_catalog_items,
    list_menu_items_for_date,
)

router: APIRouter = APIRouter()
ALLOWED_MENU_ROLES: set[str] = {"RESTAURANT", "ADMIN"}


def _require_menu_role(current_user: User) -> None:
    if current_user.role not in ALLOWED_MENU_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _resolve_restaurant_id(db: Session, current_user: User) -> int:
    if current_user.role == "RESTAURANT":
        if current_user.restaurant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant user requires restaurant_id")
        return current_user.restaurant_id
    restaurant = db.query(Restaurant).order_by(Restaurant.id.asc()).first()
    if restaurant is None:
        restaurant = Restaurant(name="Default Restaurant", is_active=True)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
    return restaurant.id


def _serialize_daily_item(daily_item: DailyMenuItem) -> DailyMenuItemResponse:
    catalog_item = daily_item.catalog_item
    return DailyMenuItemResponse(
        daily_id=daily_item.id,
        catalog_item_id=daily_item.catalog_item_id,
        menu_date=daily_item.menu_date,
        is_active=daily_item.is_active,
        name=catalog_item.name,
        description=catalog_item.description,
        price_cents=catalog_item.price_cents,
    )


def _serialize_catalog_item_for_date(catalog_item: CatalogItem, menu_date: date) -> DailyMenuItemResponse:
    return DailyMenuItemResponse(
        daily_id=-catalog_item.id,
        catalog_item_id=catalog_item.id,
        menu_date=menu_date,
        is_active=True,
        name=catalog_item.name,
        description=catalog_item.description,
        price_cents=catalog_item.price_cents,
    )

@router.get("/today", response_model=list[DailyMenuItemResponse])
def get_today_menu(db: Session = Depends(get_db)) -> list[DailyMenuItemResponse]:
    """Return active menu items for today."""
    today: date = date.today()
    restaurant_id = db.query(Restaurant.id).order_by(Restaurant.id.asc()).first()
    if restaurant_id is None:
        return []
    catalog_items = list_available_catalog_items_for_date(db=db, menu_date=today, restaurant_id=restaurant_id[0])
    return [_serialize_catalog_item_for_date(item, today) for item in catalog_items]


@router.post("/activate", response_model=DailyMenuItemResponse)
def activate_menu_item(
    payload: DailyMenuActivationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyMenuItemResponse:
    """Create or update daily activation for a catalog item."""
    _require_menu_role(current_user)
    target_date: date = payload.menu_date or date.today()
    catalog_item: CatalogItem | None = db.get(CatalogItem, payload.catalog_item_id)
    if catalog_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog item not found")

    restaurant_id = _resolve_restaurant_id(db, current_user)
    daily_item = activate_catalog_item_for_date(
        db=db,
        catalog_item_id=payload.catalog_item_id,
        menu_date=target_date,
        restaurant_id=restaurant_id,
        is_active=payload.is_active,
    )
    return _serialize_daily_item(daily_item)


@router.post("/catalog", response_model=CatalogItemResponse, status_code=status.HTTP_201_CREATED)
def create_catalog(
    payload: CatalogItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CatalogItem:
    """Create catalog item."""
    _require_menu_role(current_user)
    restaurant_id = _resolve_restaurant_id(db, current_user)
    return create_catalog_item(
        db=db,
        name=payload.name,
        description=payload.description,
        price_cents=payload.price_cents,
        is_active=payload.is_active,
        restaurant_id=_resolve_restaurant_id(db, current_user),
    )


@router.get("/catalog", response_model=list[CatalogItemResponse])
def get_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CatalogItem]:
    """List catalog items for restaurant/admin."""
    _require_menu_role(current_user)
    return list_catalog_items(db=db, restaurant_id=_resolve_restaurant_id(db, current_user))


@router.post("", response_model=DailyMenuItemResponse, status_code=status.HTTP_201_CREATED)
def create_menu_item_compat(
    payload: MenuItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyMenuItemResponse:
    """Backward-compatible endpoint creating catalog item + daily activation."""
    _require_menu_role(current_user)
    item = create_menu_item(
        db=db,
        menu_date=payload.menu_date,
        name=payload.name,
        description=payload.description,
        price_cents=payload.price_cents,
        is_active=payload.is_active,
        restaurant_id=_resolve_restaurant_id(db, current_user),
    )
    return _serialize_daily_item(item)


@router.get("", response_model=list[DailyMenuItemResponse])
def get_menu_for_date(
    date_value: date = Query(alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DailyMenuItemResponse]:
    """Return all daily menu rows for selected date."""
    _require_menu_role(current_user)
    rows = list_menu_items_for_date(db=db, menu_date=date_value, restaurant_id=_resolve_restaurant_id(db, current_user))
    return [_serialize_daily_item(row) for row in rows]
