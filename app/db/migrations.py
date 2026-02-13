"""Lightweight schema migrations for SQLite databases."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


DEFAULT_RESTAURANT_NAME: str = "Default Restaurant"


def _sqlite_column_names(connection: Connection, table_name: str) -> set[str]:
    """Return column names for a SQLite table using PRAGMA table_info."""
    rows = connection.execute(text(f"PRAGMA table_info({table_name});")).mappings().all()
    return {str(row["name"]) for row in rows}


def _sqlite_index_names(connection: Connection, table_name: str) -> set[str]:
    """Return index names for a SQLite table using PRAGMA index_list."""
    rows = connection.execute(text(f"PRAGMA index_list({table_name});")).mappings().all()
    return {str(row["name"]) for row in rows}


def _ensure_default_restaurant(connection: Connection) -> int:
    """Return the default restaurant id, creating the row if needed."""
    restaurant_id = connection.execute(
        text("SELECT id FROM restaurants WHERE name = :name ORDER BY id ASC LIMIT 1"),
        {"name": DEFAULT_RESTAURANT_NAME},
    ).scalar_one_or_none()
    if restaurant_id is not None:
        return int(restaurant_id)

    now_iso: str = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    connection.execute(
        text(
            """
            INSERT INTO restaurants (name, is_active, created_at)
            VALUES (:name, :is_active, :created_at)
            """
        ),
        {"name": DEFAULT_RESTAURANT_NAME, "is_active": True, "created_at": now_iso},
    )
    created_id = connection.execute(
        text("SELECT id FROM restaurants WHERE name = :name ORDER BY id DESC LIMIT 1"),
        {"name": DEFAULT_RESTAURANT_NAME},
    ).scalar_one()
    return int(created_id)


def ensure_sqlite_schema(engine: Engine) -> None:
    """Apply lightweight schema updates for legacy SQLite databases."""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        table_rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).all()
        table_names: set[str] = {str(row[0]) for row in table_rows}

        if "locations" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE locations (
                        id INTEGER PRIMARY KEY,
                        company_name VARCHAR(255) NOT NULL,
                        address VARCHAR(255) NOT NULL,
                        delivery_time_start TIME NULL,
                        delivery_time_end TIME NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )
            table_names.add("locations")

        if "restaurants" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE restaurants (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )
            table_names.add("restaurants")

        if "restaurant_opening_hours" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE restaurant_opening_hours (
                        id INTEGER PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        ordering_open_time TIME NOT NULL,
                        ordering_close_time TIME NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1
                    )
                    """
                )
            )
            table_names.add("restaurant_opening_hours")

        if "restaurant_locations" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE restaurant_locations (
                        id INTEGER PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        location_id INTEGER NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        cut_off_time_override TIME NULL
                    )
                    """
                )
            )
            table_names.add("restaurant_locations")

        if "locations" in table_names:
            location_columns: set[str] = _sqlite_column_names(connection, "locations")
            if "created_at" not in location_columns:
                now_iso: str = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
                connection.execute(
                    text(
                        "ALTER TABLE locations ADD COLUMN created_at DATETIME NOT NULL "
                        f"DEFAULT '{now_iso}'"
                    )
                )
            if "cutoff_time" not in location_columns:
                connection.execute(text("ALTER TABLE locations ADD COLUMN cutoff_time TIME"))

        default_restaurant_id = _ensure_default_restaurant(connection)

        if "users" in table_names:
            user_columns = _sqlite_column_names(connection, "users")
            if "restaurant_id" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN restaurant_id INTEGER"))

        if "catalog_items" in table_names:
            catalog_columns: set[str] = _sqlite_column_names(connection, "catalog_items")
            if "is_standard" not in catalog_columns:
                connection.execute(
                    text("ALTER TABLE catalog_items ADD COLUMN is_standard BOOLEAN NOT NULL DEFAULT 0")
                )
            if "restaurant_id" not in catalog_columns:
                connection.execute(
                    text(f"ALTER TABLE catalog_items ADD COLUMN restaurant_id INTEGER NOT NULL DEFAULT {default_restaurant_id}")
                )
            connection.execute(
                text(
                    "UPDATE catalog_items SET restaurant_id = :restaurant_id WHERE restaurant_id IS NULL"
                ),
                {"restaurant_id": default_restaurant_id},
            )

        if "daily_menu_items" in table_names:
            daily_columns: set[str] = _sqlite_column_names(connection, "daily_menu_items")
            if "menu_date" not in daily_columns:
                today_iso: str = date.today().isoformat()
                connection.execute(
                    text(f"ALTER TABLE daily_menu_items ADD COLUMN menu_date DATE NOT NULL DEFAULT '{today_iso}'")
                )
            if "restaurant_id" not in daily_columns:
                connection.execute(
                    text(f"ALTER TABLE daily_menu_items ADD COLUMN restaurant_id INTEGER NOT NULL DEFAULT {default_restaurant_id}")
                )
            connection.execute(
                text(
                    "UPDATE daily_menu_items SET restaurant_id = :restaurant_id WHERE restaurant_id IS NULL"
                ),
                {"restaurant_id": default_restaurant_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM daily_menu_items
                    WHERE id NOT IN (
                        SELECT MIN(id)
                        FROM daily_menu_items
                        GROUP BY restaurant_id, menu_date, catalog_item_id
                    )
                    """
                )
            )
            index_names = _sqlite_index_names(connection, "daily_menu_items")
            if "uq_daily_menu_restaurant_date_catalog_item" not in index_names:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_menu_restaurant_date_catalog_item "
                        "ON daily_menu_items(restaurant_id, menu_date, catalog_item_id)"
                    )
                )

        if "orders" in table_names:
            orders_columns = _sqlite_column_names(connection, "orders")
            if "location_id" not in orders_columns:
                default_location = connection.execute(
                    text("SELECT id FROM locations ORDER BY id ASC LIMIT 1")
                ).scalar_one_or_none()
                if default_location is None:
                    now_iso = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
                    connection.execute(
                        text(
                            """
                            INSERT INTO locations (company_name, address, is_active, created_at)
                            VALUES (:company_name, :address, :is_active, :created_at)
                            """
                        ),
                        {
                            "company_name": "Legacy Location",
                            "address": "Unknown Address",
                            "is_active": True,
                            "created_at": now_iso,
                        },
                    )
                    default_location = connection.execute(
                        text("SELECT id FROM locations ORDER BY id ASC LIMIT 1")
                    ).scalar_one()

                connection.execute(
                    text(
                        "ALTER TABLE orders ADD COLUMN location_id INTEGER "
                        f"NOT NULL DEFAULT {int(default_location)}"
                    )
                )

            if "restaurant_id" not in orders_columns:
                connection.execute(
                    text(f"ALTER TABLE orders ADD COLUMN restaurant_id INTEGER NOT NULL DEFAULT {default_restaurant_id}")
                )
            connection.execute(
                text("UPDATE orders SET restaurant_id = :restaurant_id WHERE restaurant_id IS NULL"),
                {"restaurant_id": default_restaurant_id},
            )

        if "order_items" in table_names:
            order_items_columns = _sqlite_column_names(connection, "order_items")
            if "catalog_item_id" not in order_items_columns:
                connection.execute(text("ALTER TABLE order_items ADD COLUMN catalog_item_id INTEGER"))

        restaurant_location_indexes = _sqlite_index_names(connection, "restaurant_locations")
        if "uq_restaurant_location" not in restaurant_location_indexes:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_restaurant_location "
                    "ON restaurant_locations(restaurant_id, location_id)"
                )
            )

        existing_links = connection.execute(text("SELECT COUNT(1) FROM restaurant_locations")).scalar_one()
        if int(existing_links) == 0:
            location_ids = connection.execute(text("SELECT id FROM locations WHERE is_active = 1")).all()
            for (location_id,) in location_ids:
                connection.execute(
                    text(
                        """
                        INSERT INTO restaurant_locations (restaurant_id, location_id, is_active)
                        VALUES (:restaurant_id, :location_id, :is_active)
                        """
                    ),
                    {"restaurant_id": default_restaurant_id, "location_id": int(location_id), "is_active": True},
                )
