"""Daily menu endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.menu import MenuItem
from app.models.user import User
from app.schemas.menu import MenuItemCreate, MenuItemResponse
from app.services.menu_service import create_menu_item as create_menu_item_record, list_menu_items_for_date

router: APIRouter = APIRouter()
ALLOWED_MENU_ROLES: set[str] = {"catering", "admin"}


@router.get("/today", response_model=list[MenuItemResponse])
def get_today_menu(db: Session = Depends(get_db)) -> list[MenuItem]:
    """Return active menu items for today."""
    today: date = date.today()
    return (
        db.query(MenuItem)
        .filter(MenuItem.menu_date == today, MenuItem.is_active.is_(True))
        .order_by(MenuItem.id.asc())
        .all()
    )


@router.post("", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
def create_menu_item(
    payload: MenuItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MenuItem:
    """Create menu item for selected date."""
    if current_user.role not in ALLOWED_MENU_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    return create_menu_item_record(
        db=db,
        menu_date=payload.menu_date,
        name=payload.name,
        description=payload.description,
        price_cents=payload.price_cents,
        is_active=payload.is_active,
    )


@router.get("", response_model=list[MenuItemResponse])
def get_menu_for_date(
    date_value: date = Query(alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MenuItem]:
    """Return all menu items for selected date for catering/admin users."""
    if current_user.role not in ALLOWED_MENU_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    return list_menu_items_for_date(db=db, menu_date=date_value)
