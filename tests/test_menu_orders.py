"""Menu and order API integration tests."""

from datetime import date, time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import session as db_session
from app.main import app
from app.models.location import Location
from app.models.menu import CatalogItem, DailyMenuItem
from app.models.restaurant import Restaurant
from app.models.app_setting import AppSetting


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


def test_catalog_item_creation_persists(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_catalog_create.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        headers = _auth_headers(client, "catering@example.com", "admin")
        response = client.post(
            "/api/v1/menu/catalog",
            json={"name": "Soup", "description": "Tomato", "price_cents": 1299, "is_active": True},
            headers=headers,
        )
        catalog_response = client.get("/api/v1/menu/catalog", headers=headers)

    assert response.status_code == 201
    assert catalog_response.status_code == 200
    assert any(item["name"] == "Soup" for item in catalog_response.json())


def test_activate_and_disable_today_menu(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_menu_activate.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        headers = _auth_headers(client, "admin@example.com", "admin")
        catalog_create = client.post(
            "/api/v1/menu/catalog",
            json={"name": "Pasta", "description": "Bolognese", "price_cents": 1999, "is_active": True},
            headers=headers,
        )
        catalog_id = catalog_create.json()["id"]

        activate_response = client.post(
            "/api/v1/menu/activate",
            json={"catalog_item_id": catalog_id, "is_active": True},
            headers=headers,
        )
        today_response = client.get("/api/v1/menu/today")

        disable_response = client.post(
            "/api/v1/menu/activate",
            json={"catalog_item_id": catalog_id, "is_active": False},
            headers=headers,
        )
        today_after_disable = client.get("/api/v1/menu/today")

    assert activate_response.status_code == 200
    assert today_response.status_code == 200
    assert len(today_response.json()) == 1
    assert disable_response.status_code == 200
    assert today_after_disable.status_code == 200
    assert today_after_disable.json() == []


def test_catalog_item_can_be_enabled_next_day_without_recreate(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_menu_next_day.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        headers = _auth_headers(client, "catering-next@example.com", "admin")
        catalog_create = client.post(
            "/api/v1/menu/catalog",
            json={"name": "Salad", "description": "Fresh", "price_cents": 1099, "is_active": True},
            headers=headers,
        )
        catalog_id = catalog_create.json()["id"]

        tomorrow = date.fromordinal(date.today().toordinal() + 1)
        activate_tomorrow = client.post(
            "/api/v1/menu/activate",
            json={"catalog_item_id": catalog_id, "menu_date": tomorrow.isoformat(), "is_active": True},
            headers=headers,
        )
        catalog_list = client.get("/api/v1/menu/catalog", headers=headers)

    assert activate_tomorrow.status_code == 200
    assert catalog_list.status_code == 200
    assert len(catalog_list.json()) == 1
    assert catalog_list.json()[0]["name"] == "Salad"



def test_today_menu_includes_standard_without_daily_activation_and_ignores_duplicate(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_today_standard_menu.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with testing_session_local() as setup_session:
        restaurant = Restaurant(name="R1", is_active=True)
        setup_session.add(restaurant)
        setup_session.flush()

        standard = CatalogItem(
            restaurant_id=restaurant.id,
            name="Rosół",
            description="",
            price_cents=1500,
            is_active=True,
            is_standard=True,
        )
        extra = CatalogItem(
            restaurant_id=restaurant.id,
            name="Burger",
            description="",
            price_cents=2500,
            is_active=True,
            is_standard=False,
        )
        setup_session.add_all([standard, extra])
        setup_session.flush()
        setup_session.add_all(
            [
                DailyMenuItem(
                    restaurant_id=restaurant.id,
                    menu_date=date.today(),
                    catalog_item_id=standard.id,
                    is_active=True,
                ),
                DailyMenuItem(
                    restaurant_id=restaurant.id,
                    menu_date=date.today(),
                    catalog_item_id=extra.id,
                    is_active=True,
                ),
            ]
        )
        setup_session.commit()

    with TestClient(app) as client:
        today_response = client.get("/api/v1/menu/today")

    assert today_response.status_code == 200
    names = [item["name"] for item in today_response.json()]
    assert names.count("Rosół") == 1
    assert "Burger" in names

    with testing_session_local() as setup_session:
        standard_item = setup_session.query(CatalogItem).filter(CatalogItem.name == "Rosół").first()
        assert standard_item is not None
        standard_item.is_active = False
        setup_session.add(standard_item)
        setup_session.commit()

    with TestClient(app) as client:
        after_deactivate = client.get("/api/v1/menu/today")

    assert after_deactivate.status_code == 200
    assert "Rosół" not in [item["name"] for item in after_deactivate.json()]

def test_post_orders_creates_order_and_get_me_returns_it(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_orders.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        admin_headers = _auth_headers(client, "admin-order@example.com", "admin")
        catalog = client.post(
            "/api/v1/menu/catalog",
            json={"name": "Bowl", "description": "Fresh", "price_cents": 1099, "is_active": True},
            headers=admin_headers,
        )
        catalog_id = catalog.json()["id"]
        activate = client.post(
            "/api/v1/menu/activate",
            json={"catalog_item_id": catalog_id, "is_active": True},
            headers=admin_headers,
        )
        assert activate.status_code == 200

        with testing_session_local() as setup_session:
            location = Location(company_name="Api Co", address="Api Street", is_active=True, cutoff_time=time(23, 59))
            setup_session.add(location)
            setup_session.add(AppSetting(key="ordering_open_time", value="00:00"))
            setup_session.add(AppSetting(key="ordering_close_time", value="23:59"))
            setup_session.commit()
            setup_session.refresh(location)
            location_id = location.id

        employee_headers = _auth_headers(client, "employee-order@example.com", "customer")
        order_response = client.post(
            "/api/v1/orders",
            json={"location_id": location_id, "items": [{"catalog_item_id": catalog_id, "quantity": 2}]},
            headers=employee_headers,
        )
        me_response = client.get("/api/v1/orders/me", headers=employee_headers)

    assert order_response.status_code == 200
    assert order_response.json()["items"][0]["quantity"] == 2

    assert me_response.status_code == 200
    payload = me_response.json()
    assert len(payload) == 1
    assert payload[0]["items"][0]["catalog_item_id"] == catalog_id
