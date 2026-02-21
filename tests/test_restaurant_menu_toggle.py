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
