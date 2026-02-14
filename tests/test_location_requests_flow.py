"""Tests for location request workflow and coverage filtering."""

from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models import Location, LocationRequest, Restaurant, RestaurantLocation


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})


def _register_and_login(client: TestClient, *, email: str, role: str, restaurant_id: int | None = None) -> None:
    payload = {"email": email, "password": "secret123", "role": role}
    if restaurant_id is not None:
        payload["restaurant_id"] = str(restaurant_id)
    assert client.post("/register", data=payload, follow_redirects=False).status_code == 303
    assert client.post("/login", data={"email": email, "password": "secret123"}, follow_redirects=False).status_code == 303


def test_restaurant_location_request_submit_and_review(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_location_request_review.db")
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
    finally:
        setup.close()

    with TestClient(app) as client:
        _register_and_login(client, email="rest-request@example.com", role="restaurant", restaurant_id=restaurant_id)
        create_response = client.post(
            "/restaurant/locations/request",
            data={"company_name": "New Co", "address": "Road 9", "postal_code": "12-345", "notes": "new warehouse"},
            follow_redirects=False,
        )
        assert create_response.status_code == 303

        client.get("/logout", follow_redirects=False)
        _register_and_login(client, email="admin-review@example.com", role="admin")
        page = client.get("/admin/location-requests")
        assert "New Co" in page.text

        verify: Session = testing_session_local()
        try:
            request_row = verify.query(LocationRequest).filter(LocationRequest.company_name == "New Co").first()
            assert request_row is not None
            request_id = request_row.id
        finally:
            verify.close()

        approve_response = client.post(
            f"/admin/location-requests/{request_id}/review",
            data={"action": "approve"},
            follow_redirects=False,
        )
        assert approve_response.status_code == 303

    verify: Session = testing_session_local()
    try:
        approved_request = verify.query(LocationRequest).filter(LocationRequest.id == request_id).first()
        assert approved_request is not None
        assert approved_request.status == "approved"
        assert approved_request.postal_code == "12-345"
        created_location = verify.query(Location).filter(Location.company_name == "New Co").first()
        assert created_location is not None
        assert created_location.postal_code == "12-345"
        mapping = (
            verify.query(RestaurantLocation)
            .filter(
                RestaurantLocation.restaurant_id == restaurant_id,
                RestaurantLocation.location_id == created_location.id,
            )
            .first()
        )
        assert mapping is not None
        assert mapping.is_active is True
    finally:
        verify.close()


def test_restaurant_coverage_filters_hide_legacy_until_inactive_enabled(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_restaurant_coverage_filters.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup: Session = testing_session_local()
    try:
        restaurant = Restaurant(name="R2", is_active=True)
        active_location = Location(company_name="Active Co", address="Main 1", postal_code="00-101", is_active=True, cutoff_time=time(10, 0))
        legacy_location = Location(company_name="Legacy Location", address="Unknown Address", postal_code="00-000", is_active=False, cutoff_time=time(9, 0))
        setup.add_all([restaurant, active_location, legacy_location])
        setup.commit()
        setup.refresh(restaurant)
        restaurant_id = restaurant.id
        setup.add(
            RestaurantLocation(
                restaurant_id=restaurant.id,
                location_id=active_location.id,
                is_active=True,
            )
        )
        setup.commit()
    finally:
        setup.close()

    with TestClient(app) as client:
        _register_and_login(client, email="rest-filters@example.com", role="restaurant", restaurant_id=restaurant_id)
        default_page = client.get("/restaurant/coverage")
        assert "Active Co" in default_page.text
        assert "Legacy Location" not in default_page.text

        inactive_page = client.get("/restaurant/coverage?show_inactive=1")
        assert "Legacy Location" in inactive_page.text


def test_location_request_rejects_invalid_postal_code(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_location_request_invalid_postal.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup: Session = testing_session_local()
    try:
        restaurant = Restaurant(name="R3", is_active=True)
        setup.add(restaurant)
        setup.commit()
        setup.refresh(restaurant)
    finally:
        setup.close()

    with TestClient(app) as client:
        _register_and_login(client, email="rest-invalid-postal@example.com", role="restaurant", restaurant_id=restaurant.id)
        response = client.post(
            "/restaurant/locations/request",
            data={"company_name": "New Co", "address": "Road 9", "postal_code": "12345"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "message=" in response.headers["location"]

    verify: Session = testing_session_local()
    try:
        request_row = verify.query(LocationRequest).filter(LocationRequest.company_name == "New Co").first()
        assert request_row is None
    finally:
        verify.close()
