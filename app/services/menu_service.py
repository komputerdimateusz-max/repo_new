"""Menu and catalog service helpers shared by API and HTML routes."""

from datetime import date

from sqlalchemy.orm import Session

from app.models.menu import CatalogItem, DailyMenuItem


def list_menu_items_for_date(db: Session, menu_date: date) -> list[DailyMenuItem]:
    """Return all daily activations for date with catalog details."""
    return (
        db.query(DailyMenuItem)
        .join(CatalogItem, DailyMenuItem.catalog_item_id == CatalogItem.id)
        .filter(DailyMenuItem.menu_date == menu_date)
        .order_by(DailyMenuItem.id.asc())
        .all()
    )


def get_menu_for_date(db: Session, target_date: date) -> list[DailyMenuItem]:
    """Return active daily menu rows for a given date."""
    return list_today_active_daily_items(db=db, menu_date=target_date)


def list_today_active_daily_items(db: Session, menu_date: date) -> list[DailyMenuItem]:
    """Return active daily menu for target date based on catalog + daily status."""
    return (
        db.query(DailyMenuItem)
        .join(CatalogItem, DailyMenuItem.catalog_item_id == CatalogItem.id)
        .filter(
            DailyMenuItem.menu_date == menu_date,
            DailyMenuItem.is_active.is_(True),
            CatalogItem.is_active.is_(True),
        )
        .order_by(DailyMenuItem.id.asc())
        .all()
    )


def list_catalog_items(db: Session) -> list[CatalogItem]:
    """Return complete catalog, active and inactive."""
    return db.query(CatalogItem).order_by(CatalogItem.id.asc()).all()


def create_catalog_item(
    db: Session,
    name: str,
    description: str | None,
    price_cents: int,
    is_active: bool,
    is_standard: bool = False,
) -> CatalogItem:
    """Create and persist a catalog item."""
    item = CatalogItem(
        name=name,
        description=description,
        price_cents=price_cents,
        is_active=is_active,
        is_standard=is_standard,
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
    is_active: bool,
) -> DailyMenuItem:
    """Create or update daily activation for a catalog item."""
    daily_item: DailyMenuItem | None = (
        db.query(DailyMenuItem)
        .filter(
            DailyMenuItem.catalog_item_id == catalog_item_id,
            DailyMenuItem.menu_date == menu_date,
        )
        .first()
    )
    if daily_item is None:
        daily_item = DailyMenuItem(
            catalog_item_id=catalog_item_id,
            menu_date=menu_date,
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


def enable_standard_for_date(db: Session, target_date: date) -> int:
    """Enable all standard catalog dishes for the provided date without duplicates."""
    standard_items: list[CatalogItem] = (
        db.query(CatalogItem)
        .filter(
            CatalogItem.is_standard.is_(True),
            CatalogItem.is_active.is_(True),
        )
        .all()
    )
    if not standard_items:
        return 0

    existing_ids: set[int] = {
        row.catalog_item_id
        for row in db.query(DailyMenuItem)
        .filter(DailyMenuItem.menu_date == target_date)
        .all()
    }

    created_count: int = 0
    for item in standard_items:
        if item.id in existing_ids:
            continue
        db.add(DailyMenuItem(menu_date=target_date, catalog_item_id=item.id, is_active=True))
        created_count += 1

    if created_count > 0:
        db.commit()
    return created_count


def copy_menu(db: Session, from_date: date, to_date: date) -> int:
    """Copy active menu rows from one date to another, skipping duplicates."""
    if from_date == to_date:
        return 0

    source_items: list[DailyMenuItem] = (
        db.query(DailyMenuItem)
        .join(CatalogItem, DailyMenuItem.catalog_item_id == CatalogItem.id)
        .filter(
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
        .filter(DailyMenuItem.menu_date == to_date)
        .all()
    }

    created_count: int = 0
    for row in source_items:
        if row.catalog_item_id in existing_target_ids:
            continue
        db.add(DailyMenuItem(menu_date=to_date, catalog_item_id=row.catalog_item_id, is_active=True))
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
) -> DailyMenuItem:
    """Backwards-compatible creator; creates catalog item and daily activation."""
    catalog_item = create_catalog_item(
        db=db,
        name=name,
        description=description,
        price_cents=price_cents,
        is_active=True,
    )
    return activate_catalog_item_for_date(
        db=db,
        catalog_item_id=catalog_item.id,
        menu_date=menu_date,
        is_active=is_active,
    )
