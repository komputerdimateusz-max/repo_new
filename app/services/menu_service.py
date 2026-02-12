"""Menu service helpers shared by API and HTML routes."""

from datetime import date

from sqlalchemy.orm import Session

from app.models.menu import MenuItem



def list_menu_items_for_date(db: Session, menu_date: date) -> list[MenuItem]:
    """Return all menu items for a specific date ordered by id."""
    return (
        db.query(MenuItem)
        .filter(MenuItem.menu_date == menu_date)
        .order_by(MenuItem.id.asc())
        .all()
    )



def create_menu_item(
    db: Session,
    menu_date: date,
    name: str,
    description: str | None,
    price_cents: int,
    is_active: bool,
) -> MenuItem:
    """Create and persist a menu item."""
    menu_item = MenuItem(
        menu_date=menu_date,
        name=name,
        description=description,
        price_cents=price_cents,
        is_active=is_active,
    )
    db.add(menu_item)
    db.commit()
    db.refresh(menu_item)
    return menu_item



def toggle_menu_item_active(db: Session, menu_item: MenuItem) -> MenuItem:
    """Toggle active status for a menu item and persist the change."""
    menu_item.is_active = not menu_item.is_active
    db.add(menu_item)
    db.commit()
    db.refresh(menu_item)
    return menu_item
