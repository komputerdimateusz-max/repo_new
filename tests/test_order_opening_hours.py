"""Ordering opening hours feature tests."""

from datetime import date, datetime, time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models import (
    AppSetting,
    CatalogItem,
    DailyMenuItem,
    Location,
    Order,
    Restaurant,
    RestaurantLocation,
    RestaurantOpeningHours,
)


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _seed_ordering_data(testing_session_local: sessionmaker) -> dict[str, int]:
    with testing_session_local() as db:
        location = Location(
            company_name="HQ",
            address="Main Street",
            is_active=True,
            cutoff_time=time(23, 59),
        )
        db.add(location)

        restaurant = Restaurant(name="Soup House", is_active=True)
        db.add(restaurant)
        db.flush()

        db.add(RestaurantLocation(restaurant_id=restaurant.id, location_id=location.id, is_active=True))

        dish = CatalogItem(name="Soup", description="Hot", price_cents=1200, is_active=True, restaurant_id=restaurant.id)
        db.add(dish)
        db.flush()

        db.add(DailyMenuItem(menu_date=date.today(), catalog_item_id=dish.id, is_active=True, restaurant_id=restaurant.id))
        db.commit()
        return {"location_id": location.id, "restaurant_id": restaurant.id, "catalog_item_id": dish.id}


def _register_and_login(client: TestClient, email: str, role: str = "customer") -> None:
    client.post(
        "/register",
        data={"email": email, "password": "secret123", "role": role},
        follow_redirects=False,
    )
    client.post(
        "/login",
        data={"email": email, "password": "secret123"},
        follow_redirects=False,
    )


def test_opening_hours_message_is_hidden_until_restaurant_selected(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_selection_gate.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr("app.main._current_local_datetime", lambda: datetime(2025, 1, 1, 1, 0))

    ids = _seed_ordering_data(testing_session_local)
    with testing_session_local() as db:
        db.add(
            RestaurantOpeningHours(
                restaurant_id=ids["restaurant_id"],
                ordering_open_time=time(8, 0),
                ordering_close_time=time(16, 0),
                is_active=True,
            )
        )
        db.commit()

    with TestClient(app) as client:
        _register_and_login(client, "outsideget@example.com")
        pre_select_response = client.get(f"/order?location_id={ids['location_id']}")
        selected_response = client.get(
            f"/order?location_id={ids['location_id']}&restaurant_id={ids['restaurant_id']}"
        )

    assert pre_select_response.status_code == 200
    assert "Ta restauracja nie przyjmuje teraz zamówień" not in pre_select_response.text
    assert selected_response.status_code == 200
    assert "Ta restauracja nie przyjmuje teraz zamówień" in selected_response.text


def test_show_open_only_filter_hides_closed_restaurants(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_open_only_filter.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr("app.main._current_local_datetime", lambda: datetime(2025, 1, 1, 12, 0))

    with testing_session_local() as db:
        location = Location(company_name="HQ", address="Main Street", is_active=True, cutoff_time=time(23, 59))
        db.add(location)
        db.flush()

        open_restaurant = Restaurant(name="Open Place", is_active=True)
        closed_restaurant = Restaurant(name="Closed Place", is_active=True)
        db.add_all([open_restaurant, closed_restaurant])
        db.flush()

        db.add_all(
            [
                RestaurantLocation(restaurant_id=open_restaurant.id, location_id=location.id, is_active=True),
                RestaurantLocation(restaurant_id=closed_restaurant.id, location_id=location.id, is_active=True),
                RestaurantOpeningHours(
                    restaurant_id=open_restaurant.id,
                    ordering_open_time=time(8, 0),
                    ordering_close_time=time(18, 0),
                    is_active=True,
                ),
                RestaurantOpeningHours(
                    restaurant_id=closed_restaurant.id,
                    ordering_open_time=time(13, 0),
                    ordering_close_time=time(14, 0),
                    is_active=True,
                ),
            ]
        )
        db.commit()
        location_id = location.id

    with TestClient(app) as client:
        _register_and_login(client, "openonly@example.com")
        full_response = client.get(f"/order?location_id={location_id}")
        filtered_response = client.get(f"/order?location_id={location_id}&show_open_only=1")

    assert full_response.status_code == 200
    assert "Open Place" in full_response.text
    assert "Closed Place" in full_response.text
    assert "OTWARTE" in full_response.text
    assert "ZAMKNIĘTE" in full_response.text

    assert filtered_response.status_code == 200
    assert "Open Place" in filtered_response.text
    assert "Closed Place" not in filtered_response.text


def test_post_order_outside_window_returns_403_and_does_not_create_order(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_outside_post.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr("app.main._current_local_datetime", lambda: datetime(2025, 1, 1, 1, 0))

    ids = _seed_ordering_data(testing_session_local)

    with testing_session_local() as db:
        db.add(
            RestaurantOpeningHours(
                restaurant_id=ids["restaurant_id"],
                ordering_open_time=time(8, 0),
                ordering_close_time=time(16, 0),
                is_active=True,
            )
        )
        db.commit()

    with TestClient(app) as client:
        _register_and_login(client, "outsidepost@example.com")
        response = client.post(
            "/app/order",
            data={
                "location_id": str(ids["location_id"]),
                "restaurant_id": str(ids["restaurant_id"]),
                f"qty_{ids['catalog_item_id']}": "1",
            },
        )

    assert response.status_code == 200
    with testing_session_local() as db:
        assert db.query(Order).count() == 0


def test_admin_can_save_opening_hours_for_restaurant(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_admin_save.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with testing_session_local() as db:
        restaurant = Restaurant(name="Admin Resto", is_active=True)
        db.add(restaurant)
        db.commit()
        restaurant_id = restaurant.id

    with TestClient(app) as client:
        _register_and_login(client, "admin-hours@example.com", role="admin")
        save_response = client.post(
            "/admin/opening-hours",
            data={"restaurant_id": str(restaurant_id), "open_time": "07:15", "close_time": "18:30"},
            follow_redirects=False,
        )

    assert save_response.status_code == 303
    with testing_session_local() as db:
        saved = db.query(RestaurantOpeningHours).filter(RestaurantOpeningHours.restaurant_id == restaurant_id, RestaurantOpeningHours.is_active.is_(True)).first()

    assert saved is not None
    assert saved.ordering_open_time.strftime("%H:%M") == "07:15"
    assert saved.ordering_close_time.strftime("%H:%M") == "18:30"


def test_api_post_order_without_restaurant_returns_400(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_outside_api.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, 1, 1, 1, 0)

    monkeypatch.setattr("app.api.v1.endpoints.orders.datetime", _FrozenDateTime)

    ids = _seed_ordering_data(testing_session_local)

    with testing_session_local() as db:
        db.add(AppSetting(key="ordering_open_time", value="08:00"))
        db.add(AppSetting(key="ordering_close_time", value="16:00"))
        db.commit()

    with TestClient(app) as client:
        register_response = client.post(
            "/api/v1/auth/register",
            json={"email": "apioutside@example.com", "password": "secret123", "role": "customer"},
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "apioutside@example.com", "password": "secret123"},
        )
        token = login_response.json()["access_token"]
        response = client.post(
            "/api/v1/orders",
            json={"location_id": ids["location_id"], "items": [{"catalog_item_id": ids["catalog_item_id"], "quantity": 1}]},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
