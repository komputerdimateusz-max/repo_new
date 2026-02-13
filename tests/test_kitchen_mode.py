"""Kitchen mode page tests."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.location import Location
from app.models.menu import CatalogItem
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def test_kitchen_mode_default_aggregate_shows_confirmed_and_prepared_only(tmp_path: Path, monkeypatch) -> None:
    """Kitchen mode aggregate view should show only confirmed/prepared rows for selected restaurant/date."""
    engine = _build_test_engine(tmp_path / "test_kitchen_aggregate.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    today = date.today()
    with testing_session_local() as db:
        restaurant = Restaurant(name="Kitchen Resto", is_active=True)
        other_restaurant = Restaurant(name="Other Resto", is_active=True)
        location = Location(company_name="Firma A", address="Main 1", is_active=True)
        db.add_all([restaurant, other_restaurant, location])
        db.flush()

        gulasz = CatalogItem(name="Gulasz", description="", price_cents=1000, is_active=True, restaurant_id=restaurant.id)
        salad = CatalogItem(name="Salatka", description="", price_cents=800, is_active=True, restaurant_id=restaurant.id)
        other_dish = CatalogItem(name="Other", description="", price_cents=500, is_active=True, restaurant_id=other_restaurant.id)
        db.add_all([gulasz, salad, other_dish])
        db.flush()

        db.add_all(
            [
                Order(order_date=today, user_id=1, location_id=location.id, restaurant_id=restaurant.id, status="confirmed"),
                Order(order_date=today, user_id=1, location_id=location.id, restaurant_id=restaurant.id, status="prepared"),
                Order(order_date=today, user_id=1, location_id=location.id, restaurant_id=restaurant.id, status="pending"),
                Order(order_date=today, user_id=1, location_id=location.id, restaurant_id=restaurant.id, status="delivered"),
                Order(order_date=today, user_id=1, location_id=location.id, restaurant_id=other_restaurant.id, status="confirmed"),
            ]
        )
        db.flush()
        orders = db.query(Order).order_by(Order.id.asc()).all()

        db.add_all(
            [
                OrderItem(order_id=orders[0].id, catalog_item_id=gulasz.id, quantity=3),
                OrderItem(order_id=orders[1].id, catalog_item_id=gulasz.id, quantity=2),
                OrderItem(order_id=orders[2].id, catalog_item_id=salad.id, quantity=100),
                OrderItem(order_id=orders[3].id, catalog_item_id=salad.id, quantity=100),
                OrderItem(order_id=orders[4].id, catalog_item_id=other_dish.id, quantity=100),
            ]
        )
        db.commit()
        restaurant_id = restaurant.id

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "kitchen@example.com", "password": "secret123", "role": "restaurant", "restaurant_id": str(restaurant_id)},
            follow_redirects=False,
        )
        client.post("/login", data={"email": "kitchen@example.com", "password": "secret123"}, follow_redirects=False)

        response = client.get("/restaurant/kitchen")

    assert response.status_code == 200
    assert "Kitchen Mode" in response.text
    assert "Gulasz" in response.text
    assert "5" in response.text
    assert "Salatka" not in response.text
    assert "Other" not in response.text


def test_kitchen_mode_detailed_supports_date_and_prepared_highlight(tmp_path: Path, monkeypatch) -> None:
    """Detailed kitchen mode should group by dish and location with prepared highlight."""
    engine = _build_test_engine(tmp_path / "test_kitchen_detailed.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    selected_date = date(2026, 1, 4)
    with testing_session_local() as db:
        restaurant = Restaurant(name="Kitchen Detailed", is_active=True)
        loc_a = Location(company_name="Firma A", address="A", is_active=True)
        loc_b = Location(company_name="Firma B", address="B", is_active=True)
        db.add_all([restaurant, loc_a, loc_b])
        db.flush()
        dish = CatalogItem(name="Schabowy", description="", price_cents=1000, is_active=True, restaurant_id=restaurant.id)
        db.add(dish)
        db.flush()

        confirmed = Order(order_date=selected_date, user_id=1, location_id=loc_b.id, restaurant_id=restaurant.id, status="confirmed")
        prepared = Order(order_date=selected_date, user_id=2, location_id=loc_a.id, restaurant_id=restaurant.id, status="prepared")
        db.add_all([confirmed, prepared])
        db.flush()
        db.add_all(
            [
                OrderItem(order_id=confirmed.id, catalog_item_id=dish.id, quantity=1),
                OrderItem(order_id=prepared.id, catalog_item_id=dish.id, quantity=2),
            ]
        )
        db.commit()
        restaurant_id = restaurant.id

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "kitchen2@example.com", "password": "secret123", "role": "restaurant", "restaurant_id": str(restaurant_id)},
            follow_redirects=False,
        )
        client.post("/login", data={"email": "kitchen2@example.com", "password": "secret123"}, follow_redirects=False)

        response = client.get(f"/restaurant/kitchen?date={selected_date.isoformat()}&mode=detailed&auto_refresh=1")

    assert response.status_code == 200
    assert "Schabowy" in response.text
    assert "Firma A" in response.text
    assert "Firma B" in response.text
    assert "class=\"kitchen-prepared\"" in response.text
    assert "setTimeout" in response.text


def test_kitchen_mode_requires_restaurant_role(tmp_path: Path, monkeypatch) -> None:
    """Non-restaurant users should not access kitchen mode."""
    engine = _build_test_engine(tmp_path / "test_kitchen_auth.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "customer@example.com", "password": "secret123", "role": "customer"},
            follow_redirects=False,
        )
        client.post("/login", data={"email": "customer@example.com", "password": "secret123"}, follow_redirects=False)

        response = client.get("/restaurant/kitchen", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app?message=")
