"""Tests for lightweight SQLite schema migrations."""

from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.db.migrations import ensure_sqlite_schema
from app.main import app
from app.models.location import Location


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _drop_catalog_item_column_from_order_items(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text("ALTER TABLE order_items RENAME TO order_items_legacy"))
        connection.execute(
            text(
                """
                CREATE TABLE order_items (
                    id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL,
                    menu_item_id INTEGER,
                    quantity INTEGER NOT NULL,
                    PRIMARY KEY (id),
                    FOREIGN KEY(order_id) REFERENCES orders (id),
                    FOREIGN KEY(menu_item_id) REFERENCES menu_items (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO order_items (id, order_id, menu_item_id, quantity)
                SELECT id, order_id, menu_item_id, quantity
                FROM order_items_legacy
                """
            )
        )
        connection.execute(text("DROP TABLE order_items_legacy"))
        connection.execute(text("PRAGMA foreign_keys=ON"))


def _auth_headers(client: TestClient, email: str, role: str) -> dict[str, str]:
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "role": role},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secret123"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_ensure_sqlite_schema_adds_catalog_item_id_column(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_schema.db")
    Base.metadata.create_all(bind=engine)
    _drop_catalog_item_column_from_order_items(engine)

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(order_items);"))
        column_names = {str(row[1]) for row in rows}

    assert "catalog_item_id" in column_names


def test_startup_migration_prevents_order_items_crash(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "legacy_app.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    _drop_catalog_item_column_from_order_items(engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        admin_headers = _auth_headers(client, "admin-migrate@example.com", "admin")
        catalog_response = client.post(
            "/api/v1/menu/catalog",
            json={"name": "Pierogi", "description": "Cheese", "price_cents": 1500, "is_active": True},
            headers=admin_headers,
        )
        catalog_id = catalog_response.json()["id"]

        activate_response = client.post(
            "/api/v1/menu/activate",
            json={"catalog_item_id": catalog_id, "is_active": True},
            headers=admin_headers,
        )
        assert activate_response.status_code == 200

        with testing_session_local() as setup_session:
            location = Location(
                company_name="Migration Co",
                address="Migration Street",
                postal_code="22-222",
                is_active=True,
                cutoff_time=time(23, 59),
            )
            setup_session.add(location)
            setup_session.commit()
            setup_session.refresh(location)
            location_id = location.id

        employee_headers = _auth_headers(client, "employee-migrate@example.com", "customer")
        order_response = client.post(
            "/api/v1/orders",
            json={"location_id": location_id, "items": [{"catalog_item_id": catalog_id, "quantity": 1}]},
            headers=employee_headers,
        )

    assert catalog_response.status_code == 201
    assert order_response.status_code == 200


def test_ensure_sqlite_schema_normalizes_legacy_lowercase_roles(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_user_roles.db")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (username, password_hash, role, email, is_active, created_at)
                VALUES
                    ('legacy-admin', 'hash', 'admin', 'legacy-admin@example.com', 1, CURRENT_TIMESTAMP),
                    ('legacy-rest', 'hash', 'restaurant', 'legacy-rest@example.com', 1, CURRENT_TIMESTAMP),
                    ('legacy-customer', 'hash', 'customer', 'legacy-customer@example.com', 1, CURRENT_TIMESTAMP)
                """
            )
        )

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        roles = {
            str(row[0])
            for row in connection.execute(text("SELECT role FROM users"))
        }

    assert roles == {"ADMIN", "RESTAURANT", "CUSTOMER"}


def test_ensure_sqlite_schema_adds_customers_user_id_column(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_customers.db")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE customers RENAME TO customers_old"))
        connection.execute(
            text(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    company_id INTEGER NULL,
                    postal_code VARCHAR(16) NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO customers (id, name, email, company_id, postal_code, is_active)
                SELECT id, name, email, company_id, postal_code, is_active
                FROM customers_old
                """
            )
        )
        connection.execute(text("DROP TABLE customers_old"))

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        customer_columns = {str(row[1]) for row in connection.execute(text("PRAGMA table_info(customers);"))}

    assert "user_id" in customer_columns

def test_ensure_sqlite_schema_adds_order_status_columns(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_orders_status.db")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text("UPDATE orders SET status = 'created'"))

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(orders);"))
        columns = {str(row[1]) for row in rows}
        migrated_statuses = {
            str(row[0])
            for row in connection.execute(text("SELECT DISTINCT status FROM orders"))
            if row[0] is not None
        }

    assert "status" in columns
    assert "status_updated_at" in columns
    assert "confirmed_at" in columns
    assert "prepared_at" in columns
    assert "delivered_at" in columns
    assert "cancelled_at" in columns
    assert "created" not in migrated_statuses


def test_ensure_sqlite_schema_adds_postal_code_columns(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_postal_columns.db")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE locations RENAME TO locations_old"))
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
        connection.execute(
            text(
                """
                INSERT INTO locations (id, company_name, address, delivery_time_start, delivery_time_end, is_active, created_at)
                SELECT id, company_name, address, delivery_time_start, delivery_time_end, is_active, created_at
                FROM locations_old
                """
            )
        )
        connection.execute(text("DROP TABLE locations_old"))

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        location_columns = {str(row[1]) for row in connection.execute(text("PRAGMA table_info(locations);"))}
        postal_tables = {str(row[0]) for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}

    assert "postal_code" in location_columns
    assert "restaurant_postal_codes" in postal_tables


def test_ensure_sqlite_schema_makes_customers_company_id_nullable(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_customers_company_not_null.db")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE customers RENAME TO customers_old"))
        connection.execute(
            text(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NULL,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    company_id INTEGER NOT NULL,
                    postal_code VARCHAR(16) NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO customers (id, user_id, name, email, company_id, postal_code, is_active)
                SELECT id, user_id, name, email,
                       CASE WHEN company_id IS NULL THEN 1 ELSE company_id END,
                       postal_code, is_active
                FROM customers_old
                """
            )
        )
        connection.execute(text("DROP TABLE customers_old"))

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        columns = {
            str(row[1]): int(row[3])
            for row in connection.execute(text("PRAGMA table_info(customers);"))
        }

    assert columns["company_id"] == 0


def test_ensure_sqlite_schema_adds_cutlery_columns(tmp_path: Path) -> None:
    engine = _build_test_engine(tmp_path / "legacy_cutlery_columns.db")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE restaurant_settings RENAME TO restaurant_settings_old"))
        connection.execute(
            text(
                """
                CREATE TABLE restaurant_settings (
                    id INTEGER PRIMARY KEY,
                    cut_off_time VARCHAR(5) NOT NULL,
                    delivery_fee NUMERIC(10, 2) NOT NULL,
                    delivery_window_start VARCHAR(5) NOT NULL,
                    delivery_window_end VARCHAR(5) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO restaurant_settings (id, cut_off_time, delivery_fee, delivery_window_start, delivery_window_end)
                SELECT id, cut_off_time, delivery_fee, delivery_window_start, delivery_window_end
                FROM restaurant_settings_old
                """
            )
        )
        connection.execute(text("DROP TABLE restaurant_settings_old"))

        connection.execute(text("ALTER TABLE orders RENAME TO orders_old"))
        connection.execute(
            text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    company_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    notes TEXT,
                    subtotal_amount NUMERIC(10, 2) NOT NULL,
                    delivery_fee NUMERIC(10, 2) NOT NULL,
                    total_amount NUMERIC(10, 2) NOT NULL,
                    payment_method VARCHAR(16) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO orders (id, customer_id, company_id, created_at, status, notes, subtotal_amount, delivery_fee, total_amount, payment_method)
                SELECT id, customer_id, company_id, created_at, status, notes, subtotal_amount, delivery_fee, total_amount, payment_method
                FROM orders_old
                """
            )
        )
        connection.execute(text("DROP TABLE orders_old"))

    ensure_sqlite_schema(engine)

    with engine.begin() as connection:
        settings_columns = {str(row[1]) for row in connection.execute(text("PRAGMA table_info(restaurant_settings);"))}
        order_columns = {str(row[1]) for row in connection.execute(text("PRAGMA table_info(orders);"))}

    assert "cutlery_price" in settings_columns
    assert "cutlery" in order_columns
    assert "cutlery_price" in order_columns
    assert "extras_total" in order_columns
