"""Menu and catalog service helpers shared by API and HTML routes."""

from datetime import date

from sqlalchemy.orm import Session

from app.models.menu import CatalogItem, DailyMenuItem


def list_menu_items_for_date(db: Session, menu_date: date, restaurant_id: int) -> list[DailyMenuItem]:
    """Return all daily activations for date with catalog details."""
    return (
        db.query(DailyMenuItem)
        .join(CatalogItem, DailyMenuItem.catalog_item_id == CatalogItem.id)
        .filter(DailyMenuItem.menu_date == menu_date, DailyMenuItem.restaurant_id == restaurant_id)
        .order_by(DailyMenuItem.id.asc())
        .all()
    )


def get_menu_for_date(db: Session, target_date: date, restaurant_id: int) -> list[DailyMenuItem]:
    """Return active daily menu rows for a given date."""
    return list_today_active_daily_items(db=db, menu_date=target_date, restaurant_id=restaurant_id)


def list_today_active_daily_items(db: Session, menu_date: date, restaurant_id: int) -> list[DailyMenuItem]:
    """Return active daily menu rows for non-standard dishes."""
    return (
        db.query(DailyMenuItem)
        .join(CatalogItem, DailyMenuItem.catalog_item_id == CatalogItem.id)
        .filter(
            DailyMenuItem.menu_date == menu_date,
            DailyMenuItem.restaurant_id == restaurant_id,
            DailyMenuItem.is_active.is_(True),
            CatalogItem.is_active.is_(True),
            CatalogItem.is_standard.is_(False),
        )
        .order_by(DailyMenuItem.id.asc())
        .all()
    )


def list_standard_catalog_items(db: Session, restaurant_id: int) -> list[CatalogItem]:
    """Return active standard catalog dishes for one restaurant."""
    return (
        db.query(CatalogItem)
        .filter(
            CatalogItem.restaurant_id == restaurant_id,
            CatalogItem.is_standard.is_(True),
            CatalogItem.is_active.is_(True),
        )
        .order_by(CatalogItem.id.asc())
        .all()
    )


def list_available_catalog_items_for_date(db: Session, menu_date: date, restaurant_id: int) -> list[CatalogItem]:
    """Return unique customer-visible menu items: active standard + active non-standard daily rows."""
    standard_items: list[CatalogItem] = list_standard_catalog_items(db=db, restaurant_id=restaurant_id)
    daily_rows: list[DailyMenuItem] = list_today_active_daily_items(db=db, menu_date=menu_date, restaurant_id=restaurant_id)

    catalog_items: list[CatalogItem] = list(standard_items)
    seen_ids: set[int] = {item.id for item in standard_items}
    for row in daily_rows:
        if row.catalog_item_id in seen_ids:
            continue
        catalog_items.append(row.catalog_item)
        seen_ids.add(row.catalog_item_id)
    return catalog_items


def list_catalog_items(db: Session, restaurant_id: int) -> list[CatalogItem]:
    """Return complete catalog for one restaurant, active and inactive."""
    return db.query(CatalogItem).filter(CatalogItem.restaurant_id == restaurant_id).order_by(CatalogItem.id.asc()).all()


def create_catalog_item(
    db: Session,
    name: str,
    description: str | None,
    price_cents: int,
    is_active: bool,
    restaurant_id: int,
    is_standard: bool = False,
) -> CatalogItem:
    """Create and persist a catalog item."""
    item = CatalogItem(
        name=name,
        description=description,
        price_cents=price_cents,
        is_active=is_active,
        is_standard=is_standard,
        restaurant_id=restaurant_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def activate_catalog_item_for_date(
    db: Session,
    *,
    catalog_item_id: int,
    menu_date: date,
    restaurant_id: int,
    is_active: bool,
) -> DailyMenuItem:
    """Create or update daily activation for a catalog item."""
    daily_item: DailyMenuItem | None = (
        db.query(DailyMenuItem)
        .filter(
            DailyMenuItem.catalog_item_id == catalog_item_id,
            DailyMenuItem.menu_date == menu_date,
            DailyMenuItem.restaurant_id == restaurant_id,
        )
        .first()
    )
    if daily_item is None:
        daily_item = DailyMenuItem(
            catalog_item_id=catalog_item_id,
            menu_date=menu_date,
            restaurant_id=restaurant_id,
            is_active=is_active,
        )
        db.add(daily_item)
    else:
        daily_item.is_active = is_active
        db.add(daily_item)

    db.commit()
    db.refresh(daily_item)
    return daily_item


def toggle_menu_item_active(db: Session, menu_item: DailyMenuItem) -> DailyMenuItem:
    """Toggle active status for a daily menu item and persist the change."""
    menu_item.is_active = not menu_item.is_active
    db.add(menu_item)
    db.commit()
    db.refresh(menu_item)
    return menu_item


def copy_menu(db: Session, from_date: date, to_date: date, restaurant_id: int) -> int:
    """Copy active menu rows from one date to another, skipping duplicates."""
    if from_date == to_date:
        return 0

    source_items: list[DailyMenuItem] = (
        db.query(DailyMenuItem)
        .join(CatalogItem, DailyMenuItem.catalog_item_id == CatalogItem.id)
        .filter(
            DailyMenuItem.restaurant_id == restaurant_id,
            DailyMenuItem.menu_date == from_date,
            DailyMenuItem.is_active.is_(True),
            CatalogItem.is_active.is_(True),
        )
        .all()
    )
    if not source_items:
        return 0

    existing_target_ids: set[int] = {
        row.catalog_item_id
        for row in db.query(DailyMenuItem)
        .filter(DailyMenuItem.menu_date == to_date, DailyMenuItem.restaurant_id == restaurant_id)
        .all()
    }

    created_count: int = 0
    for row in source_items:
        if row.catalog_item_id in existing_target_ids:
            continue
        db.add(DailyMenuItem(menu_date=to_date, catalog_item_id=row.catalog_item_id, restaurant_id=restaurant_id, is_active=True))
        created_count += 1

    if created_count > 0:
        db.commit()
    return created_count


def create_menu_item(
    db: Session,
    menu_date: date,
    name: str,
    description: str | None,
    price_cents: int,
    is_active: bool,
    restaurant_id: int,
) -> DailyMenuItem:
    """Backwards-compatible creator; creates catalog item and daily activation."""
    catalog_item = create_catalog_item(
        db=db,
        name=name,
        description=description,
        price_cents=price_cents,
        is_active=True,
        restaurant_id=restaurant_id,
    )
    return activate_catalog_item_for_date(
        db=db,
        catalog_item_id=catalog_item.id,
        menu_date=menu_date,
        restaurant_id=restaurant_id,
        is_active=is_active,
    )
