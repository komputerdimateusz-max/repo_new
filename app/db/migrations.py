"""Lightweight schema migrations for SQLite databases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


def _sqlite_column_names(connection: Connection, table_name: str) -> set[str]:
    """Return column names for a SQLite table using PRAGMA table_info."""
    rows = connection.execute(text(f"PRAGMA table_info({table_name});")).mappings().all()
    return {str(row["name"]) for row in rows}


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

        if "order_items" in table_names:
            order_items_columns = _sqlite_column_names(connection, "order_items")
            if "catalog_item_id" not in order_items_columns:
                connection.execute(text("ALTER TABLE order_items ADD COLUMN catalog_item_id INTEGER"))
