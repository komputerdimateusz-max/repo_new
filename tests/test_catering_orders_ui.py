"""Catering orders page access tests."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models import MenuItem, Order, OrderItem, User
from app.core.security import get_password_hash


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _login_with_role(client: TestClient, email: str, role: str) -> None:
    register_response = client.post(
        "/register",
        data={"email": email, "password": "secret123", "role": role},
        follow_redirects=False,
    )
    assert register_response.status_code == 303

    login_response = client.post(
        "/login",
        data={"email": email, "password": "secret123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303


def _seed_order(testing_session_local: sessionmaker) -> None:
    session: Session = testing_session_local()
    try:
        user = User(email="seeded@example.com", hashed_password=get_password_hash("seed"), role="employee")
        session.add(user)
        session.flush()

        menu_item = MenuItem(
            menu_date=date.today(),
            name="Zupa",
            description="Pomidorowa",
            price_cents=1500,
            is_active=True,
        )
        session.add(menu_item)
        session.flush()

        order = Order(user_id=user.id, order_date=date.today(), status="created")
        session.add(order)
        session.flush()

        order_item = OrderItem(order_id=order.id, menu_item_id=menu_item.id, quantity=2)
        session.add(order_item)
        session.commit()
    finally:
        session.close()


def test_catering_orders_forbidden_for_employee(tmp_path: Path, monkeypatch) -> None:
    """Employee should be redirected when opening /catering/orders."""
    engine = _build_test_engine(tmp_path / "test_catering_orders_employee.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "employee-orders@example.com", "employee")
        response = client.get("/catering/orders", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app")


def test_catering_orders_returns_ok_for_admin(tmp_path: Path, monkeypatch) -> None:
    """Admin should access /catering/orders successfully."""
    engine = _build_test_engine(tmp_path / "test_catering_orders_admin.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    _seed_order(testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "admin-orders@example.com", "admin")
        response = client.get("/catering/orders")

    assert response.status_code == 200
    assert "seeded@example.com" in response.text


def test_catering_orders_returns_ok_for_catering(tmp_path: Path, monkeypatch) -> None:
    """Catering should access /catering/orders successfully."""
    engine = _build_test_engine(tmp_path / "test_catering_orders_catering.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    _seed_order(testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "catering-orders@example.com", "catering")
        response = client.get("/catering/orders")

    assert response.status_code == 200
    assert "seeded@example.com" in response.text
