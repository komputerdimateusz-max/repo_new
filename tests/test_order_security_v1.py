from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as main_module
from app.core.security import get_password_hash
from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models import Company, Customer, MenuItem, Order, OrderItem, RestaurantSetting, User


def _prepare_db(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'security_v1.db'}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", testing_session_local)
    return testing_session_local


def _seed_core(session_local):
    with session_local() as db:
        db.add(
            RestaurantSetting(
                id=1,
                cut_off_time="00:00",
                delivery_fee=Decimal("10.00"),
                cutlery_price=Decimal("1.00"),
                delivery_window_start="10:00",
                delivery_window_end="12:00",
            )
        )
        company = Company(name="Factory", is_active=True)
        db.add(company)
        db.flush()

        c1_user = User(username="customer1", password_hash=get_password_hash("pass"), role="CUSTOMER", is_active=True)
        c2_user = User(username="customer2", password_hash=get_password_hash("pass"), role="CUSTOMER", is_active=True)
        rest_user = User(username="restaurant", password_hash=get_password_hash("pass"), role="RESTAURANT", is_active=True)
        db.add_all([c1_user, c2_user, rest_user])
        db.flush()

        c1 = Customer(user_id=c1_user.id, name="C1", email="c1@example.com", company_id=company.id)
        c2 = Customer(user_id=c2_user.id, name="C2", email="c2@example.com", company_id=company.id)
        db.add_all([c1, c2])
        db.flush()

        menu_item = MenuItem(name="Soup", description="", price=Decimal("20.00"), category="Zupy", is_standard=True, is_active=True)
        db.add(menu_item)
        db.flush()

        order = Order(
            customer_id=c1.id,
            company_id=company.id,
            status="NEW",
            notes="test",
            payment_method="BLIK",
            subtotal_amount=Decimal("20.00"),
            delivery_fee=Decimal("10.00"),
            cutlery=False,
            cutlery_price=Decimal("0.00"),
            extras_total=Decimal("0.00"),
            total_amount=Decimal("30.00"),
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(order_id=order.id, menu_item_id=menu_item.id, name="Soup", unit_price=Decimal("20.00"), qty=1, price_snapshot=Decimal("20.00")))
        db.commit()
        return order.id


def test_customer_cannot_cancel_after_cutoff(tmp_path: Path, monkeypatch) -> None:
    session_local = _prepare_db(tmp_path, monkeypatch)
    order_id = _seed_core(session_local)

    with TestClient(app) as client:
        client.post("/login", data={"username": "customer1", "password": "pass"}, follow_redirects=False)
        response = client.delete(f"/api/v1/orders/{order_id}")

    assert response.status_code == 403


def test_customer_cannot_access_other_customer_order(tmp_path: Path, monkeypatch) -> None:
    session_local = _prepare_db(tmp_path, monkeypatch)
    order_id = _seed_core(session_local)

    with TestClient(app) as client:
        client.post("/login", data={"username": "customer2", "password": "pass"}, follow_redirects=False)
        response = client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 404


def test_restaurant_can_export_after_cutoff(tmp_path: Path, monkeypatch) -> None:
    session_local = _prepare_db(tmp_path, monkeypatch)
    _seed_core(session_local)

    with TestClient(app) as client:
        client.post("/login", data={"username": "restaurant", "password": "pass"}, follow_redirects=False)
        response = client.get("/api/v1/admin/orders/today.csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
