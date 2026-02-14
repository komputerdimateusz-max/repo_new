"""Tests for restaurant delivery coverage cut-off UI workflow."""

from datetime import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models import Location, Restaurant, RestaurantLocation


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _register_and_login_restaurant_user(client: TestClient, restaurant_id: int) -> None:
    register_response = client.post(
        "/register",
        data={
            "email": "restaurant-coverage@example.com",
            "password": "secret123",
            "role": "restaurant",
            "restaurant_id": str(restaurant_id),
        },
        follow_redirects=False,
    )
    assert register_response.status_code == 303

    login_response = client.post(
        "/login",
        data={"email": "restaurant-coverage@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303


def test_coverage_page_renders_table_and_single_update_form(tmp_path: Path, monkeypatch) -> None:
    """Coverage page should display consolidated table and one update form."""
    engine = _build_test_engine(tmp_path / "test_restaurant_coverage_page.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        restaurant = Restaurant(name="Resto", is_active=True)
        location = Location(company_name="Acme", address="Main 1", is_active=True, cutoff_time=time(11, 0))
        setup_session.add_all([restaurant, location])
        setup_session.commit()
        setup_session.refresh(restaurant)
        setup_session.refresh(location)
        setup_session.add(
            RestaurantLocation(
                restaurant_id=restaurant.id,
                location_id=location.id,
                is_active=True,
                cut_off_time_override=time(10, 30),
            )
        )
        setup_session.commit()
        restaurant_id = restaurant.id
        location_id = location.id
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _register_and_login_restaurant_user(client, restaurant_id)
        response = client.get(f"/restaurant/coverage?location_id={location_id}")

    assert response.status_code == 200
    assert "Aktualny cut-off dla lokalizacji" in response.text
    assert "Aktualizuj cut-off" in response.text
    assert response.text.count('name="location_id"') == 1
    assert "10:30" in response.text
    assert "Edytuj" in response.text


def test_coverage_post_can_clear_override_without_disabling_mapping(tmp_path: Path, monkeypatch) -> None:
    """Clear override action should null override while preserving explicit active flag."""
    engine = _build_test_engine(tmp_path / "test_restaurant_coverage_clear.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        restaurant = Restaurant(name="Resto", is_active=True)
        location = Location(company_name="Beta", address="Street 2", is_active=True, cutoff_time=time(11, 0))
        setup_session.add_all([restaurant, location])
        setup_session.commit()
        setup_session.add(
            RestaurantLocation(
                restaurant_id=restaurant.id,
                location_id=location.id,
                is_active=False,
                cut_off_time_override=time(9, 45),
            )
        )
        setup_session.commit()
        restaurant_id = restaurant.id
        location_id = location.id
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _register_and_login_restaurant_user(client, restaurant_id)
        response = client.post(
            "/restaurant/coverage",
            data={
                "location_id": str(location_id),
                "mapping_active_present": "1",
                "action": "clear_override",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == f"/restaurant/coverage?location_id={location_id}"

    verify_session: Session = testing_session_local()
    try:
        updated = (
            verify_session.query(RestaurantLocation)
            .filter(
                RestaurantLocation.restaurant_id == restaurant_id,
                RestaurantLocation.location_id == location_id,
            )
            .first()
        )
        assert updated is not None
        assert updated.cut_off_time_override is None
        assert updated.is_active is False
    finally:
        verify_session.close()
