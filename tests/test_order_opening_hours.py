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
from app.models import AppSetting, CatalogItem, DailyMenuItem, Location, Order


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _seed_ordering_data(testing_session_local: sessionmaker) -> None:
    with testing_session_local() as db:
        location = Location(
            company_name="HQ",
            address="Main Street",
            is_active=True,
            cutoff_time=time(23, 59),
        )
        db.add(location)
        db.flush()

        dish = CatalogItem(name="Soup", description="Hot", price_cents=1200, is_active=True)
        db.add(dish)
        db.flush()

        db.add(DailyMenuItem(menu_date=date.today(), catalog_item_id=dish.id, is_active=True))
        db.commit()


def _register_and_login(client: TestClient, email: str, role: str = "employee") -> None:
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


def test_get_order_within_window_shows_form(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_within.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr("app.main._current_local_datetime", lambda: datetime(2025, 1, 1, 12, 0))

    _seed_ordering_data(testing_session_local)

    with TestClient(app) as client:
        _register_and_login(client, "within@example.com")
        response = client.get("/order")

    assert response.status_code == 200
    assert 'action="/app/order"' in response.text


def test_get_order_outside_window_shows_closed_message(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_outside_get.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr("app.main._current_local_datetime", lambda: datetime(2025, 1, 1, 1, 0))

    _seed_ordering_data(testing_session_local)

    with testing_session_local() as db:
        db.add(AppSetting(key="ordering_open_time", value="08:00"))
        db.add(AppSetting(key="ordering_close_time", value="16:00"))
        db.commit()

    with TestClient(app) as client:
        _register_and_login(client, "outsideget@example.com")
        response = client.get("/order")

    assert response.status_code == 200
    assert "Ordering is currently closed" in response.text
    assert "Order form is disabled outside ordering hours" in response.text


def test_post_order_outside_window_returns_403_and_does_not_create_order(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_outside_post.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr("app.main._current_local_datetime", lambda: datetime(2025, 1, 1, 1, 0))

    _seed_ordering_data(testing_session_local)

    with testing_session_local() as db:
        db.add(AppSetting(key="ordering_open_time", value="08:00"))
        db.add(AppSetting(key="ordering_close_time", value="16:00"))
        location_id = db.query(Location.id).first()[0]
        catalog_item_id = db.query(CatalogItem.id).first()[0]
        db.commit()

    with TestClient(app) as client:
        _register_and_login(client, "outsidepost@example.com")
        response = client.post(
            "/app/order",
            data={"location_id": str(location_id), f"qty_{catalog_item_id}": "1"},
        )

    assert response.status_code == 403
    with testing_session_local() as db:
        assert db.query(Order).count() == 0


def test_admin_can_save_opening_hours(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_opening_hours_admin_save.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _register_and_login(client, "admin-hours@example.com", role="admin")
        save_response = client.post(
            "/admin/opening-hours",
            data={"open_time": "07:15", "close_time": "18:30"},
            follow_redirects=False,
        )

    assert save_response.status_code == 303
    with testing_session_local() as db:
        settings_map = {row.key: row.value for row in db.query(AppSetting).all()}

    assert settings_map["ordering_open_time"] == "07:15"
    assert settings_map["ordering_close_time"] == "18:30"


def test_api_post_order_outside_window_returns_403(tmp_path: Path, monkeypatch) -> None:
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

    _seed_ordering_data(testing_session_local)

    with testing_session_local() as db:
        db.add(AppSetting(key="ordering_open_time", value="08:00"))
        db.add(AppSetting(key="ordering_close_time", value="16:00"))
        location_id = db.query(Location.id).first()[0]
        catalog_item_id = db.query(CatalogItem.id).first()[0]
        db.commit()

    with TestClient(app) as client:
        register_response = client.post(
            "/api/v1/auth/register",
            json={"email": "apioutside@example.com", "password": "secret123", "role": "employee"},
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "apioutside@example.com", "password": "secret123"},
        )
        token = login_response.json()["access_token"]
        response = client.post(
            "/api/v1/orders",
            json={"location_id": location_id, "items": [{"catalog_item_id": catalog_item_id, "quantity": 1}]},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
