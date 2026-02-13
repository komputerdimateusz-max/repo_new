"""Catering menu management HTML flow tests."""

from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db import session as db_session
from app.main import app
from app.models.menu import CatalogItem, DailyMenuItem


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _login_with_role(client: TestClient, email: str, role: str) -> None:
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


def test_get_catering_menu_as_employee_is_forbidden(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_catering_menu_employee.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "employee-ui@example.com", "customer")
        response = client.get("/catering/menu", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app")


def test_get_catering_menu_as_catering_returns_ok(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_catering_menu_catering.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        catalog_item = CatalogItem(name="Today Soup", description="Fresh", price_cents=1000, is_active=True)
        setup_session.add(catalog_item)
        setup_session.flush()
        setup_session.add(
            DailyMenuItem(
                menu_date=date.today(),
                catalog_item_id=catalog_item.id,
                is_active=True,
            )
        )
        setup_session.add(
            DailyMenuItem(
                menu_date=date.today() - timedelta(days=1),
                catalog_item_id=catalog_item.id,
                is_active=True,
            )
        )
        setup_session.commit()
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "catering-ui@example.com", "restaurant")
        response = client.get("/catering/menu")

    assert response.status_code == 200
    assert "Today Soup" in response.text


def test_post_catering_menu_creates_catalog_item_and_redirects(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_catering_menu_create.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "admin-ui@example.com", "admin")
        response = client.post(
            "/catering/menu",
            data={
                "name": "Pierogi",
                "description": "Ruskie",
                "price": "12.50",
                "is_active": "on",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/catering/menu?message=")

    session: Session = testing_session_local()
    try:
        created_item: CatalogItem | None = session.query(CatalogItem).filter(CatalogItem.name == "Pierogi").first()
        assert created_item is not None
        assert created_item.price_cents == 1250
        assert created_item.is_active is True
    finally:
        session.close()


def test_post_toggle_changes_daily_is_active(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_catering_menu_toggle.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    session: Session = testing_session_local()
    try:
        catalog_item = CatalogItem(name="Kotlet", description="Schabowy", price_cents=2200, is_active=True)
        session.add(catalog_item)
        session.flush()
        daily_item = DailyMenuItem(menu_date=date.today(), catalog_item_id=catalog_item.id, is_active=True)
        session.add(daily_item)
        session.commit()
        catalog_item_id: int = catalog_item.id
    finally:
        session.close()

    with TestClient(app) as client:
        _login_with_role(client, "catering-toggle@example.com", "restaurant")
        response = client.post(
            f"/catering/menu/{catalog_item_id}/toggle",
            follow_redirects=False,
        )

    assert response.status_code == 303

    verify_session: Session = testing_session_local()
    try:
        updated_item: DailyMenuItem | None = (
            verify_session.query(DailyMenuItem)
            .filter(DailyMenuItem.catalog_item_id == catalog_item_id, DailyMenuItem.menu_date == date.today())
            .first()
        )
        assert updated_item is not None
        assert updated_item.is_active is False
    finally:
        verify_session.close()
