"""Dashboard card navigation tests."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app


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


def test_dashboard_cards_include_expected_user_links(tmp_path: Path, monkeypatch) -> None:
    """GET /app should include the user card links for order/menu/orders."""
    engine = _build_test_engine(tmp_path / "test_dashboard_cards_links.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "cards@example.com", "employee")
        response = client.get("/app")

    assert response.status_code == 200
    assert 'href="/order"' in response.text
    assert 'href="/menu"' in response.text
    assert 'href="/orders"' in response.text


def test_dashboard_hides_admin_links_for_employee(tmp_path: Path, monkeypatch) -> None:
    """Employee should not see catering/admin dashboard links."""
    engine = _build_test_engine(tmp_path / "test_dashboard_cards_employee_links.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "employee-cards@example.com", "employee")
        response = client.get("/app")

    assert response.status_code == 200
    assert '/catering/menu?date=' not in response.text
    assert 'href="/catering/orders"' not in response.text


def test_dashboard_shows_admin_links_for_admin(tmp_path: Path, monkeypatch) -> None:
    """Admin should see catering/admin dashboard links."""
    engine = _build_test_engine(tmp_path / "test_dashboard_cards_admin_links.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "admin-cards@example.com", "admin")
        response = client.get("/app")

    assert response.status_code == 200
    assert '/catering/menu?date=' in response.text
    assert 'href="/catering/orders"' in response.text


def test_menu_orders_pages_load_for_authenticated_user(tmp_path: Path, monkeypatch) -> None:
    """Authenticated user can open /menu, /order and /orders pages."""
    engine = _build_test_engine(tmp_path / "test_dashboard_pages.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "pages@example.com", "employee")
        menu_response = client.get("/menu")
        order_response = client.get("/order")
        orders_response = client.get("/orders")

    assert menu_response.status_code == 200
    assert order_response.status_code == 200
    assert orders_response.status_code == 200
