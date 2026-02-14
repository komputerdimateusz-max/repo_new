"""Tests for restaurant postal-code scoped coverage workflow."""

from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models import Location, Restaurant, RestaurantLocation, RestaurantPostalCode


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})


def _register_and_login(client: TestClient, *, email: str, role: str, restaurant_id: int | None = None) -> None:
    payload = {"email": email, "password": "secret123", "role": role}
    if restaurant_id is not None:
        payload["restaurant_id"] = str(restaurant_id)
    assert client.post("/register", data=payload, follow_redirects=False).status_code == 303
    assert client.post("/login", data={"email": email, "password": "secret123"}, follow_redirects=False).status_code == 303


def test_restaurant_can_add_location_only_for_active_served_postal_codes(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_coverage_postal_scope.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup: Session = testing_session_local()
    try:
        restaurant = Restaurant(name="R1", is_active=True)
        setup.add(restaurant)
        setup.commit()
        setup.refresh(restaurant)
        restaurant_id = restaurant.id
        setup.add(RestaurantPostalCode(restaurant_id=restaurant_id, postal_code="12-345", is_active=True))
        setup.commit()
    finally:
        setup.close()

    with TestClient(app) as client:
        _register_and_login(client, email="rest-postal@example.com", role="restaurant", restaurant_id=restaurant_id)
        forbidden_postal = client.post(
            "/restaurant/coverage",
            data={"action": "add_location", "company_name": "Bad Co", "address": "Street 1", "postal_code": "99-999"},
            follow_redirects=False,
        )
        assert forbidden_postal.status_code == 303

        allowed_postal = client.post(
            "/restaurant/coverage",
            data={"action": "add_location", "company_name": "Good Co", "address": "Street 2", "postal_code": "12-345"},
            follow_redirects=False,
        )
        assert allowed_postal.status_code == 303

    verify: Session = testing_session_local()
    try:
        bad_location = verify.query(Location).filter(Location.company_name == "Bad Co").first()
        assert bad_location is None

        good_location = verify.query(Location).filter(Location.company_name == "Good Co").first()
        assert good_location is not None
        assert good_location.postal_code == "12-345"
        mapping = verify.query(RestaurantLocation).filter(
            RestaurantLocation.restaurant_id == restaurant_id,
            RestaurantLocation.location_id == good_location.id,
        ).first()
        assert mapping is not None
        assert mapping.is_active is True
    finally:
        verify.close()


def test_restaurant_coverage_shows_only_mapped_locations(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_restaurant_coverage_mapped_only.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup: Session = testing_session_local()
    try:
        restaurant = Restaurant(name="R2", is_active=True)
        mapped_location = Location(company_name="Mapped Co", address="Main 1", postal_code="11-111", is_active=True, cutoff_time=time(10, 0))
        foreign_location = Location(company_name="Foreign Co", address="Main 2", postal_code="22-222", is_active=True, cutoff_time=time(9, 0))
        setup.add_all([restaurant, mapped_location, foreign_location])
        setup.commit()
        setup.refresh(restaurant)
        setup.add(RestaurantLocation(restaurant_id=restaurant.id, location_id=mapped_location.id, is_active=True))
        setup.add(RestaurantPostalCode(restaurant_id=restaurant.id, postal_code="11-111", is_active=True))
        setup.commit()
        restaurant_id = restaurant.id
    finally:
        setup.close()

    with TestClient(app) as client:
        _register_and_login(client, email="rest-coverage@example.com", role="restaurant", restaurant_id=restaurant_id)
        page = client.get("/restaurant/coverage")

    assert page.status_code == 200
    assert "Mapped Co" in page.text
    assert "Foreign Co" not in page.text
    assert "Poproś o nową lokalizację" not in page.text
