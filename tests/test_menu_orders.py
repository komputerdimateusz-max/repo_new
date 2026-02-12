"""Menu and order endpoint tests."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import session as db_session
from app.main import app


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


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


def test_create_menu_item_as_catering_works(tmp_path: Path, monkeypatch) -> None:
    """Catering role can create menu item."""
    engine = _build_test_engine(tmp_path / "test_menu_create_catering.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        headers = _auth_headers(client, "catering@example.com", "catering")
        response = client.post(
            "/api/v1/menu",
            json={
                "menu_date": date.today().isoformat(),
                "name": "Soup",
                "description": "Tomato",
                "price_cents": 1299,
                "is_active": True,
            },
            headers=headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Soup"


def test_create_menu_item_as_employee_is_forbidden(tmp_path: Path, monkeypatch) -> None:
    """Employee role cannot create menu item."""
    engine = _build_test_engine(tmp_path / "test_menu_create_employee.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        headers = _auth_headers(client, "employee@example.com", "employee")
        response = client.post(
            "/api/v1/menu",
            json={
                "menu_date": date.today().isoformat(),
                "name": "Soup",
                "description": "Tomato",
                "price_cents": 1299,
                "is_active": True,
            },
            headers=headers,
        )

    assert response.status_code == 403


def test_get_menu_today_returns_items(tmp_path: Path, monkeypatch) -> None:
    """Today endpoint should return active items for today."""
    engine = _build_test_engine(tmp_path / "test_menu_today.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        headers = _auth_headers(client, "admin@example.com", "admin")
        create_response = client.post(
            "/api/v1/menu",
            json={
                "menu_date": date.today().isoformat(),
                "name": "Pasta",
                "description": "Bolognese",
                "price_cents": 1999,
                "is_active": True,
            },
            headers=headers,
        )
        assert create_response.status_code == 201

        today_response = client.get("/api/v1/menu/today")

    assert today_response.status_code == 200
    assert len(today_response.json()) == 1


def test_post_orders_creates_order_and_get_me_returns_it(tmp_path: Path, monkeypatch) -> None:
    """Create order endpoint should persist items and user can read them."""
    engine = _build_test_engine(tmp_path / "test_orders.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        admin_headers = _auth_headers(client, "admin-order@example.com", "admin")
        menu_response = client.post(
            "/api/v1/menu",
            json={
                "menu_date": date.today().isoformat(),
                "name": "Salad",
                "description": "Fresh",
                "price_cents": 1099,
                "is_active": True,
            },
            headers=admin_headers,
        )
        assert menu_response.status_code == 201
        menu_id = menu_response.json()["id"]

        employee_headers = _auth_headers(client, "employee-order@example.com", "employee")
        order_response = client.post(
            "/api/v1/orders",
            json={"items": [{"menu_item_id": menu_id, "quantity": 2}]},
            headers=employee_headers,
        )
        me_response = client.get("/api/v1/orders/me", headers=employee_headers)

    assert order_response.status_code == 200
    assert order_response.json()["items"][0]["quantity"] == 2

    assert me_response.status_code == 200
    payload = me_response.json()
    assert len(payload) == 1
    assert payload[0]["items"][0]["menu_item_id"] == menu_id
