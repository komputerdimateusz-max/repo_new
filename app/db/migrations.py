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


def _sqlite_table_info(connection: Connection, table_name: str) -> list[dict[str, object]]:
    """Return raw table info rows for SQLite table."""
    return [dict(row) for row in connection.execute(text(f"PRAGMA table_info({table_name});")).mappings().all()]


def _sqlite_index_names(connection: Connection, table_name: str) -> set[str]:
    """Return index names for a SQLite table using PRAGMA index_list."""
    rows = connection.execute(text(f"PRAGMA index_list({table_name});")).mappings().all()
    return {str(row["name"]) for row in rows}


def _ensure_customers_company_nullable(connection: Connection) -> None:
    """Rebuild customers table when legacy schema enforces NOT NULL on company_id."""
    customer_info = _sqlite_table_info(connection, "customers")
    company_info = next((row for row in customer_info if str(row.get("name")) == "company_id"), None)
    if company_info is None or int(company_info.get("notnull") or 0) == 0:
        return

    connection.execute(text("ALTER TABLE customers RENAME TO customers_old"))
    connection.execute(
        text(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NULL,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                company_id INTEGER NULL,
                postal_code VARCHAR(16) NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                FOREIGN KEY(company_id) REFERENCES companies(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO customers (id, user_id, name, email, company_id, postal_code, is_active)
            SELECT id, user_id, name, email, company_id, postal_code, is_active
            FROM customers_old
            """
        )
    )
    connection.execute(text("DROP TABLE customers_old"))
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_email ON customers(email)"))


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




def _normalize_legacy_user_roles(connection: Connection) -> None:
    """Normalize legacy lowercase role values to canonical enum strings."""
    lower_roles = connection.execute(
        text(
            """
            SELECT COUNT(1)
            FROM users
            WHERE role IN ('admin', 'restaurant', 'customer', 'catering', 'employee', 'company', 'user')
            """
        )
    ).scalar_one()
    if int(lower_roles or 0) == 0:
        return

    connection.execute(text("UPDATE users SET role = 'ADMIN' WHERE role = 'admin'"))
    connection.execute(text("UPDATE users SET role = 'RESTAURANT' WHERE role IN ('restaurant', 'catering')"))
    connection.execute(text("UPDATE users SET role = 'CUSTOMER' WHERE role IN ('customer', 'employee', 'company', 'user')"))
    connection.execute(text("UPDATE users SET role = 'CUSTOMER' WHERE role NOT IN ('ADMIN', 'CUSTOMER', 'RESTAURANT')"))

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
                        postal_code VARCHAR(16) NOT NULL DEFAULT '00-000',
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

        if "restaurant_postal_codes" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE restaurant_postal_codes (
                        id INTEGER PRIMARY KEY,
                        restaurant_id INTEGER NOT NULL,
                        postal_code VARCHAR(16) NOT NULL DEFAULT '00-000',
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )
            table_names.add("restaurant_postal_codes")

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
            if "postal_code" not in location_columns:
                connection.execute(text("ALTER TABLE locations ADD COLUMN postal_code VARCHAR(16) DEFAULT '00-000'"))
                connection.execute(
                    text(
                        "UPDATE locations SET postal_code = '00-000' "
                        "WHERE postal_code IS NULL OR TRIM(postal_code) = ''"
                    )
                )

        default_restaurant_id = _ensure_default_restaurant(connection)

        if "users" in table_names:
            user_columns = _sqlite_column_names(connection, "users")
            if "restaurant_id" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN restaurant_id INTEGER"))
            _normalize_legacy_user_roles(connection)
            connection.execute(
                text("UPDATE users SET restaurant_id = :restaurant_id WHERE role = 'RESTAURANT' AND restaurant_id IS NULL"),
                {"restaurant_id": default_restaurant_id},
            )
            connection.execute(text("UPDATE users SET restaurant_id = NULL WHERE role = 'CUSTOMER'"))

        if "customers" in table_names:
            _ensure_customers_company_nullable(connection)
            customer_columns = _sqlite_column_names(connection, "customers")
            if "user_id" not in customer_columns:
                connection.execute(text("ALTER TABLE customers ADD COLUMN user_id INTEGER"))

            if "users" in table_names and "email" in customer_columns:
                # Backfill links for legacy rows based on matching unique email.
                connection.execute(
                    text(
                        """
                        UPDATE customers
                        SET user_id = (
                            SELECT users.id
                            FROM users
                            WHERE users.email = customers.email
                            LIMIT 1
                        )
                        WHERE user_id IS NULL
                          AND email IS NOT NULL
                          AND TRIM(email) != ''
                        """
                    )
                )

            # Keep the latest row linked if duplicates were produced historically.
            connection.execute(
                text(
                    """
                    UPDATE customers
                    SET user_id = NULL
                    WHERE user_id IS NOT NULL
                      AND id NOT IN (
                          SELECT MAX(id)
                          FROM customers
                          WHERE user_id IS NOT NULL
                          GROUP BY user_id
                      )
                    """
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_user_id "
                    "ON customers(user_id) WHERE user_id IS NOT NULL"
                )
            )

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
            if "cutlery" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN cutlery BOOLEAN NOT NULL DEFAULT 0"))
            if "cutlery_price" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN cutlery_price NUMERIC(10, 2) NOT NULL DEFAULT 0"))
            if "extras_total" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN extras_total NUMERIC(10, 2) NOT NULL DEFAULT 0"))
            if "location_id" not in orders_columns:
                default_location = connection.execute(
                    text("SELECT id FROM locations ORDER BY id ASC LIMIT 1")
                ).scalar_one_or_none()
                if default_location is None:
                    now_iso = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
                    connection.execute(
                        text(
                            """
                            INSERT INTO locations (company_name, address, postal_code, is_active, created_at)
                            VALUES (:company_name, :address, :postal_code, :is_active, :created_at)
                            """
                        ),
                        {
                            "company_name": "Legacy Location",
                            "address": "Unknown Address",
                            "postal_code": "00-000",
                            "is_active": False,
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
            if "status" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending'"))
            connection.execute(text("UPDATE orders SET status = 'pending' WHERE status IS NULL OR status = 'created'"))
            if "status_updated_at" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN status_updated_at DATETIME"))
            if "confirmed_at" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN confirmed_at DATETIME"))
            if "prepared_at" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN prepared_at DATETIME"))
            if "delivered_at" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN delivered_at DATETIME"))
            if "cancelled_at" not in orders_columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN cancelled_at DATETIME"))

        if "order_items" in table_names:
            order_items_columns = _sqlite_column_names(connection, "order_items")
            if "catalog_item_id" not in order_items_columns:
                connection.execute(text("ALTER TABLE order_items ADD COLUMN catalog_item_id INTEGER"))
            if "name" not in order_items_columns:
                connection.execute(text("ALTER TABLE order_items ADD COLUMN name VARCHAR(255)"))
                connection.execute(
                    text(
                        """
                        UPDATE order_items
                        SET name = COALESCE(
                            (SELECT menu_items.name FROM menu_items WHERE menu_items.id = order_items.menu_item_id),
                            'Pozycja'
                        )
                        WHERE name IS NULL
                        """
                    )
                )
            if "unit_price" not in order_items_columns:
                connection.execute(text("ALTER TABLE order_items ADD COLUMN unit_price NUMERIC(10, 2)"))
                connection.execute(text("UPDATE order_items SET unit_price = COALESCE(price_snapshot, 0) WHERE unit_price IS NULL"))

        if "restaurant_settings" in table_names:
            settings_columns = _sqlite_column_names(connection, "restaurant_settings")
            if "cutlery_price" not in settings_columns:
                connection.execute(text("ALTER TABLE restaurant_settings ADD COLUMN cutlery_price NUMERIC(10, 2) NOT NULL DEFAULT 0"))

        restaurant_location_indexes = _sqlite_index_names(connection, "restaurant_locations")
        if "uq_restaurant_location" not in restaurant_location_indexes:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_restaurant_location "
                    "ON restaurant_locations(restaurant_id, location_id)"
                )
            )

        if "restaurant_postal_codes" in table_names:
            restaurant_postal_indexes = _sqlite_index_names(connection, "restaurant_postal_codes")
            if "uq_restaurant_postal_code" not in restaurant_postal_indexes:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_restaurant_postal_code "
                        "ON restaurant_postal_codes(restaurant_id, postal_code)"
                    )
                )


        if "locations" in table_names:
            connection.execute(
                text(
                    """
                    UPDATE locations
                    SET is_active = 0
                    WHERE lower(company_name) LIKE '%legacy%'
                       OR lower(address) LIKE '%unknown%'
                    """
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
