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
            data={"email": "cards@example.com", "password": "secret123", "role": "customer"},
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


def test_dashboard_shows_only_settings_tile_for_admin_role(tmp_path: Path, monkeypatch) -> None:
    """Admin should only see settings tile in admin tools section."""
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
    assert 'href="/settings"' in response.text
    assert 'href="/catering/menu"' not in response.text
    assert 'href="/admin/locations"' not in response.text
    assert 'href="/catering/orders"' not in response.text
    assert 'href="/admin/opening-hours"' not in response.text


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
            data={"email": "pages@example.com", "password": "secret123", "role": "customer"},
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


def test_top_nav_hides_register_for_authenticated_user(tmp_path: Path, monkeypatch) -> None:
    """Authenticated users should not see register/login links in top nav."""
    engine = _build_test_engine(tmp_path / "test_dashboard_top_nav.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/register",
            data={"email": "nav@example.com", "password": "secret123", "role": "customer"},
            follow_redirects=False,
        )
        assert register_response.status_code == 303

        login_response = client.post(
            "/login",
            data={"email": "nav@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        response = client.get("/app")

    assert response.status_code == 200
    assert 'href="/register"' not in response.text
    assert 'href="/login"' not in response.text
    assert 'href="/logout"' in response.text


def test_restaurant_dashboard_hides_ordering_tiles_and_shows_restaurant_name(tmp_path: Path, monkeypatch) -> None:
    """Restaurant dashboard should render only restaurant management area."""
    engine = _build_test_engine(tmp_path / "test_dashboard_restaurant_links.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    from app.models.restaurant import Restaurant

    with testing_session_local() as db:
        restaurant = Restaurant(name="Bistro 77", is_active=True)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        restaurant_id = restaurant.id

    with TestClient(app) as client:
        register_response = client.post(
            "/register",
            data={"email": "restaurant@example.com", "password": "secret123", "role": "restaurant", "restaurant_id": str(restaurant_id)},
            follow_redirects=False,
        )
        assert register_response.status_code == 303

        login_response = client.post(
            "/login",
            data={"email": "restaurant@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        response = client.get("/app")

    assert response.status_code == 200
    assert "Dashboard – Bistro 77" in response.text
    assert 'href="/order"' not in response.text
    assert 'href="/menu"' not in response.text
    assert 'href="/orders"' not in response.text
    assert "Nie masz dostępu do menu cateringu." not in response.text
    assert 'href="/catering/menu"' in response.text
    assert 'href="/catering/orders"' in response.text
    assert 'href="/restaurant/opening-hours"' in response.text
    assert 'href="/restaurant/coverage"' in response.text


def test_dashboard_header_varies_by_role(tmp_path: Path, monkeypatch) -> None:
    """Dashboard header should include role-aware identity text."""
    engine = _build_test_engine(tmp_path / "test_dashboard_headers.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    from app.models.restaurant import Restaurant

    with testing_session_local() as db:
        restaurant = Restaurant(name="Header Place", is_active=True)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        restaurant_id = restaurant.id

    with TestClient(app) as client:
        client.post("/register", data={"email": "headcustomer@example.com", "password": "secret123", "role": "customer"}, follow_redirects=False)
        client.post("/login", data={"email": "headcustomer@example.com", "password": "secret123"}, follow_redirects=False)
        customer_response = client.get("/app")
        client.get("/logout", follow_redirects=False)

        client.post("/register", data={"email": "headrestaurant@example.com", "password": "secret123", "role": "restaurant", "restaurant_id": str(restaurant_id)}, follow_redirects=False)
        client.post("/login", data={"email": "headrestaurant@example.com", "password": "secret123"}, follow_redirects=False)
        restaurant_response = client.get("/app")
        client.get("/logout", follow_redirects=False)

        client.post("/register", data={"email": "headadmin@example.com", "password": "secret123", "role": "admin"}, follow_redirects=False)
        client.post("/login", data={"email": "headadmin@example.com", "password": "secret123"}, follow_redirects=False)
        admin_response = client.get("/app")

    assert "Dashboard – headcustomer" in customer_response.text
    assert "Dashboard – Header Place" in restaurant_response.text
    assert "Dashboard – Administrator" in admin_response.text
