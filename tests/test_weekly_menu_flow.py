"""Weekly menu smoke flow tests."""

from datetime import date, time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.app_setting import AppSetting
from app.models.location import Location


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _register_and_login(client: TestClient, email: str, role: str) -> None:
    register_response = client.post(
        "/register",
        data={"email": email, "password": "secret123", "role": role},
        follow_redirects=False,
    )
    assert register_response.status_code == 303

    login_response = client.post(
        "/login",
        data={"email": email, "password": "secret123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303


def test_weekly_menu_enable_standard_and_ordering_flow(tmp_path: Path, monkeypatch) -> None:
    """Admin can schedule future menu and employee can order it with date filter."""
    engine = _build_test_engine(tmp_path / "test_weekly_menu_flow.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    target_date: date = date.fromordinal(date.today().toordinal() + 1)

    with testing_session_local() as setup_session:
        location = Location(
            company_name="Weekly Co",
            address="Weekly Street",
            is_active=True,
            cutoff_time=time(23, 59),
        )
        setup_session.add(location)
        setup_session.add(AppSetting(key="ordering_open_time", value="00:00"))
        setup_session.add(AppSetting(key="ordering_close_time", value="23:59"))
        setup_session.commit()
        setup_session.refresh(location)
        location_id = location.id

    with TestClient(app) as admin_client:
        _register_and_login(admin_client, "weekly-admin@example.com", "admin")

        create_catalog = admin_client.post(
            "/catering/menu",
            data={
                "name": "Standard Soup",
                "description": "Tomato",
                "price": "12.00",
                "is_active": "on",
                "is_standard": "on",
            },
            follow_redirects=False,
        )
        assert create_catalog.status_code == 303

        enable_standard = admin_client.post(
            "/admin/weekly-menu/enable-standard",
            data={"selected_date": target_date.isoformat()},
            follow_redirects=False,
        )
        assert enable_standard.status_code == 303

        with testing_session_local() as check_session:
            catalog_id = check_session.execute(text("SELECT id FROM catalog_items WHERE name = 'Standard Soup'")).scalar_one()

        api_login = admin_client.post(
            "/api/v1/auth/login",
            json={"email": "weekly-admin@example.com", "password": "secret123"},
        )
        token = api_login.json()["access_token"]
        force_activation = admin_client.post(
            "/api/v1/menu/activate",
            json={"catalog_item_id": catalog_id, "menu_date": target_date.isoformat(), "is_active": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert force_activation.status_code == 200

    with TestClient(app) as employee_client:
        _register_and_login(employee_client, "weekly-employee@example.com", "customer")

        api_login = employee_client.post(
            "/api/v1/auth/login",
            json={"email": "weekly-employee@example.com", "password": "secret123"},
        )
        token = api_login.json()["access_token"]
        submit_order = employee_client.post(
            "/api/v1/orders",
            json={"location_id": location_id, "order_for_next_day": True, "items": [{"catalog_item_id": catalog_id, "quantity": 1}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert submit_order.status_code == 200

    with TestClient(app) as admin_client:
        _register_and_login(admin_client, "weekly-admin2@example.com", "admin")

        summary_response = admin_client.get(f"/catering/orders?date={target_date.isoformat()}")
        assert summary_response.status_code == 200
        assert "Weekly Street" in summary_response.text
