"""Dashboard card navigation tests."""

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


def test_dashboard_cards_include_expected_links(tmp_path: Path, monkeypatch) -> None:
    """GET /app should include user tiles links in dashboard."""
    engine = _build_test_engine(tmp_path / "test_dashboard_cards_links.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/register",
            data={"email": "cards@example.com", "password": "secret123", "role": "employee"},
            follow_redirects=False,
        )
        assert register_response.status_code == 303

        login_response = client.post(
            "/login",
            data={"email": "cards@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        response = client.get("/app")

    assert response.status_code == 200
    assert 'href="/order"' in response.text
    assert 'href="/menu"' in response.text
    assert 'href="/orders"' in response.text
    assert 'href="/catering/menu' not in response.text
    assert 'href="/admin/locations"' not in response.text
    assert 'href="/catering/orders"' not in response.text


def test_dashboard_shows_admin_links_for_admin_role(tmp_path: Path, monkeypatch) -> None:
    """Admin should see admin tool links on dashboard."""
    engine = _build_test_engine(tmp_path / "test_dashboard_cards_admin_links.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/register",
            data={"email": "admincards@example.com", "password": "secret123", "role": "admin"},
            follow_redirects=False,
        )
        assert register_response.status_code == 303

        login_response = client.post(
            "/login",
            data={"email": "admincards@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        response = client.get("/app")

    assert response.status_code == 200
    assert 'href="/catering/menu"' in response.text
    assert 'href="/admin/locations"' in response.text
    assert 'href="/catering/orders"' in response.text
    assert 'href="/admin/opening-hours"' in response.text


def test_menu_orders_billing_pages_load_for_authenticated_user(tmp_path: Path, monkeypatch) -> None:
    """Authenticated user can open /menu, /orders, and /billing pages."""
    engine = _build_test_engine(tmp_path / "test_dashboard_pages.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/register",
            data={"email": "pages@example.com", "password": "secret123", "role": "employee"},
            follow_redirects=False,
        )
        assert register_response.status_code == 303

        login_response = client.post(
            "/login",
            data={"email": "pages@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        menu_response = client.get("/menu")
        orders_response = client.get("/orders")
        billing_response = client.get("/billing")

    assert menu_response.status_code == 200
    assert orders_response.status_code == 200
    assert billing_response.status_code == 200
