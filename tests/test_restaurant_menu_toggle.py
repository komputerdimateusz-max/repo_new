"""Restaurant menu active-state toggle integration tests."""

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import get_password_hash
from app.db import session as db_session
from app.db.base import Base
from app.main import app
import app.main as main_module
from app.models import MenuItem, RestaurantSetting, User


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _login_restaurant_user(client: TestClient) -> None:
    login_response = client.post(
        "/login",
        data={"username": "restaurant-toggle@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303


def test_restaurant_can_toggle_item_visibility_and_customer_menu_filters_inactive(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_restaurant_menu_toggle.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        setup_session.add(
            RestaurantSetting(
                id=1,
                cut_off_time="11:00",
                delivery_fee=Decimal("7.00"),
                delivery_window_start="12:00",
                delivery_window_end="13:00",
            )
        )
        setup_session.add(
            User(
                username="restaurant-toggle@example.com",
                email="restaurant-toggle@example.com",
                password_hash=get_password_hash("secret123"),
                role="RESTAURANT",
                is_active=True,
            )
        )
        setup_session.add(
            MenuItem(
                name="Kotlet dnia",
                description="Test",
                price=Decimal("22.00"),
                category="Drugie",
                is_standard=True,
                is_active=True,
            )
        )
        setup_session.commit()

        menu_item = setup_session.query(MenuItem).filter(MenuItem.name == "Kotlet dnia").first()
        assert menu_item is not None
        menu_item_id = menu_item.id
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_restaurant_user(client)

        page_before = client.get("/restaurant/menu")
        assert page_before.status_code == 200
        assert "Wyłącz" in page_before.text

        customer_menu_before = client.get("/api/v1/menu/today")
        assert customer_menu_before.status_code == 200
        assert any(item["name"] == "Kotlet dnia" for item in customer_menu_before.json()["items"])

        toggle_off = client.post(f"/restaurant/menu/{menu_item_id}/toggle", follow_redirects=False)
        assert toggle_off.status_code == 303
        assert toggle_off.headers["location"] == "/restaurant/menu"

        page_after_off = client.get("/restaurant/menu")
        assert page_after_off.status_code == 200
        assert "Inactive" in page_after_off.text
        assert "Włącz" in page_after_off.text

        customer_menu_after_off = client.get("/api/v1/menu/today")
        assert customer_menu_after_off.status_code == 200
        assert all(item["name"] != "Kotlet dnia" for item in customer_menu_after_off.json()["items"])

        toggle_on = client.post(f"/restaurant/menu/{menu_item_id}/toggle", follow_redirects=False)
        assert toggle_on.status_code == 303

        customer_menu_after_on = client.get("/api/v1/menu/today")
        assert customer_menu_after_on.status_code == 200
        assert any(item["name"] == "Kotlet dnia" for item in customer_menu_after_on.json()["items"])


def test_restaurant_can_edit_menu_item_and_customer_menu_shows_updated_values(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_restaurant_menu_edit.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        setup_session.add(
            RestaurantSetting(
                id=1,
                cut_off_time="11:00",
                delivery_fee=Decimal("7.00"),
                delivery_window_start="12:00",
                delivery_window_end="13:00",
            )
        )
        setup_session.add(
            User(
                username="restaurant-toggle@example.com",
                email="restaurant-toggle@example.com",
                password_hash=get_password_hash("secret123"),
                role="RESTAURANT",
                is_active=True,
            )
        )
        setup_session.add(
            MenuItem(
                name="Stary zestaw",
                description="Stary opis",
                price=Decimal("18.00"),
                category="Drugie",
                is_standard=True,
                is_active=True,
            )
        )
        setup_session.commit()

        menu_item = setup_session.query(MenuItem).filter(MenuItem.name == "Stary zestaw").first()
        assert menu_item is not None
        menu_item_id = menu_item.id
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_restaurant_user(client)

        edit_page = client.get(f"/restaurant/menu/{menu_item_id}/edit")
        assert edit_page.status_code == 200
        assert "Edytuj pozycję menu" in edit_page.text

        update_response = client.post(
            f"/restaurant/menu/{menu_item_id}/edit",
            data={
                "name": "Nowy zestaw",
                "description": "Nowy opis",
                "price": "24.50",
                "category": "Zupa",
                "is_active": "true",
            },
            follow_redirects=False,
        )
        assert update_response.status_code == 303
        assert update_response.headers["location"] == "/restaurant/menu"

        restaurant_list = client.get("/restaurant/menu")
        assert restaurant_list.status_code == 200
        assert "Nowy zestaw" in restaurant_list.text
        assert "Nowy opis" in restaurant_list.text
        assert "24.50" in restaurant_list.text

        customer_menu = client.get("/api/v1/menu/today")
        assert customer_menu.status_code == 200
        item_payload = next((row for row in customer_menu.json()["items"] if row["id"] == menu_item_id), None)
        assert item_payload is not None
        assert item_payload["name"] == "Nowy zestaw"
        assert item_payload["description"] == "Nowy opis"
        assert item_payload["price"] == "24.50"


def test_restaurant_menu_edit_validation_errors_return_form(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_restaurant_menu_edit_validation.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        setup_session.add(
            RestaurantSetting(
                id=1,
                cut_off_time="11:00",
                delivery_fee=Decimal("7.00"),
                delivery_window_start="12:00",
                delivery_window_end="13:00",
            )
        )
        setup_session.add(
            User(
                username="restaurant-toggle@example.com",
                email="restaurant-toggle@example.com",
                password_hash=get_password_hash("secret123"),
                role="RESTAURANT",
                is_active=True,
            )
        )
        setup_session.add(
            MenuItem(
                name="Pozycja",
                description="Opis",
                price=Decimal("20.00"),
                category="Drugie",
                is_standard=True,
                is_active=True,
            )
        )
        setup_session.commit()

        menu_item = setup_session.query(MenuItem).filter(MenuItem.name == "Pozycja").first()
        assert menu_item is not None
        menu_item_id = menu_item.id
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_restaurant_user(client)

        invalid_response = client.post(
            f"/restaurant/menu/{menu_item_id}/edit",
            data={"name": "", "description": "", "price": "not-a-number", "category": "Drugie"},
        )
        assert invalid_response.status_code == 200
        assert "Name is required." in invalid_response.text

        negative_response = client.post(
            f"/restaurant/menu/{menu_item_id}/edit",
            data={"name": "Pozycja", "description": "", "price": "-2", "category": "Drugie"},
        )
        assert negative_response.status_code == 200
        assert "greater than or equal to 0" in negative_response.text
