"""Supported locations feature tests."""

from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app import main as main_module
from app.main import app
from app.models import Location, MenuItem, Order, OrderItem


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


def test_admin_can_create_location(tmp_path: Path, monkeypatch) -> None:
    """Admin should create location from admin panel."""
    engine = _build_test_engine(tmp_path / "test_create_location.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "admin-location@example.com", "admin")
        response = client.post(
            "/admin/locations",
            data={
                "company_name": "Acme",
                "address": "Main 1",
                "delivery_time_start": "10:00",
                "delivery_time_end": "12:00",
                "cutoff_time": "10:30",
                "is_active": "on",
            },
            follow_redirects=False,
        )

        page_response = client.get("/admin/locations")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/locations?message=")

    session: Session = testing_session_local()
    try:
        created: Location | None = session.query(Location).filter(Location.company_name == "Acme").first()
        assert created is not None
        assert created.address == "Main 1"
        assert created.is_active is True
        assert created.cutoff_time is not None
        assert created.cutoff_time.strftime("%H:%M") == "10:30"
    finally:
        session.close()

    assert page_response.status_code == 200
    assert "10:30" in page_response.text


def test_non_admin_cannot_access_admin_locations(tmp_path: Path, monkeypatch) -> None:
    """Employee should be redirected from admin locations page."""
    engine = _build_test_engine(tmp_path / "test_locations_forbidden.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "employee-location@example.com", "customer")
        response = client.get("/admin/locations", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app")


def test_order_requires_location(tmp_path: Path, monkeypatch) -> None:
    """Order submit without location must fail validation."""
    engine = _build_test_engine(tmp_path / "test_order_location_required.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        setup_session.add(
            MenuItem(
                menu_date=date.today(),
                name="Soup",
                description="Hot",
                price_cents=1000,
                is_active=True,
            )
        )
        setup_session.commit()
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "order-no-location@example.com", "customer")
        response = client.post("/app/order", data={"qty_1": "1"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/order?error=")


def test_order_saved_with_location_id(tmp_path: Path, monkeypatch) -> None:
    """Order should persist selected location id."""
    engine = _build_test_engine(tmp_path / "test_order_location_saved.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        location = Location(company_name="Beta", address="Street 2", is_active=True, cutoff_time=time(23, 59))
        setup_session.add(location)
        setup_session.add(
            MenuItem(
                menu_date=date.today(),
                name="Pasta",
                description="Tomato",
                price_cents=2300,
                is_active=True,
            )
        )
        setup_session.commit()
        setup_session.refresh(location)
        location_id = location.id
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "order-location@example.com", "customer")
        response = client.post(
            "/app/order",
            data={"location_id": str(location_id), "qty_1": "2"},
            follow_redirects=False,
        )

    assert response.status_code == 303

    verify_session: Session = testing_session_local()
    try:
        created_order: Order | None = verify_session.query(Order).first()
        assert created_order is not None
        assert created_order.location_id == location_id
    finally:
        verify_session.close()


def test_order_for_today_before_cutoff_succeeds(tmp_path: Path, monkeypatch) -> None:
    """Order should be created for today when now is before cut-off."""
    engine = _build_test_engine(tmp_path / "test_order_before_cutoff.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(main_module, "_current_local_datetime", lambda: now)

    setup_session: Session = testing_session_local()
    try:
        location = Location(company_name="Gamma", address="Street 3", is_active=True, cutoff_time=now.time().replace(hour=10, minute=0))
        menu = MenuItem(menu_date=now.date(), name="Rice", description="Veg", price_cents=1200, is_active=True)
        setup_session.add_all([location, menu])
        setup_session.commit()
        setup_session.refresh(location)
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "before-cutoff@example.com", "customer")
        response = client.post(
            "/app/order",
            data={"location_id": str(location.id), "qty_1": "1"},
            follow_redirects=False,
        )

    assert response.status_code == 303


def test_order_for_today_after_cutoff_shows_prompt(tmp_path: Path, monkeypatch) -> None:
    """Order after cut-off should return prompt and skip creating today's order."""
    engine = _build_test_engine(tmp_path / "test_order_after_cutoff_prompt.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    now = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(main_module, "_current_local_datetime", lambda: now)

    setup_session: Session = testing_session_local()
    try:
        location = Location(company_name="Delta", address="Street 4", is_active=True, cutoff_time=now.time().replace(hour=10, minute=0))
        menu = MenuItem(menu_date=now.date(), name="Fish", description="Fresh", price_cents=1800, is_active=True)
        setup_session.add_all([location, menu])
        setup_session.commit()
        setup_session.refresh(location)
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "after-cutoff@example.com", "customer")
        response = client.post(
            "/app/order",
            data={"location_id": str(location.id), "qty_1": "1"},
            follow_redirects=False,
        )

    assert response.status_code == 200
    assert "The cut-off time for this location has passed" in response.text

    verify_session: Session = testing_session_local()
    try:
        created_order: Order | None = verify_session.query(Order).filter(Order.order_date == now.date()).first()
        assert created_order is None
    finally:
        verify_session.close()


def test_order_for_tomorrow_after_cutoff_succeeds(tmp_path: Path, monkeypatch) -> None:
    """Order for next day should be saved when submitted after cut-off with confirmation flag."""
    engine = _build_test_engine(tmp_path / "test_order_after_cutoff_tomorrow.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    now = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(main_module, "_current_local_datetime", lambda: now)

    setup_session: Session = testing_session_local()
    try:
        location = Location(company_name="Epsilon", address="Street 5", is_active=True, cutoff_time=now.time().replace(hour=10, minute=0))
        menu = MenuItem(menu_date=now.date(), name="Chicken", description="Grill", price_cents=1700, is_active=True)
        setup_session.add_all([location, menu])
        setup_session.commit()
        setup_session.refresh(location)
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "tomorrow-order@example.com", "customer")
        response = client.post(
            "/app/order",
            data={"location_id": str(location.id), "qty_1": "1", "order_for_next_day": "1"},
            follow_redirects=False,
        )

    assert response.status_code == 303

    verify_session: Session = testing_session_local()
    try:
        created_order: Order | None = verify_session.query(Order).first()
        assert created_order is not None
        assert created_order.order_date == now.date() + timedelta(days=1)
    finally:
        verify_session.close()


def test_catering_orders_summary_groups_by_location(tmp_path: Path, monkeypatch) -> None:
    """Orders summary section should aggregate rows per location."""
    engine = _build_test_engine(tmp_path / "test_orders_summary_locations.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    setup_session: Session = testing_session_local()
    try:
        location_a = Location(company_name="Acme", address="Main 1", is_active=True)
        location_b = Location(company_name="Beta", address="Main 2", is_active=True)
        menu = MenuItem(menu_date=date.today(), name="Lunch", description="Box", price_cents=1500, is_active=True)
        setup_session.add_all([location_a, location_b, menu])
        setup_session.commit()
        setup_session.refresh(location_a)
        setup_session.refresh(location_b)
        setup_session.refresh(menu)

        order_a = Order(user_id=1, location_id=location_a.id, order_date=date.today(), status="pending")
        order_b = Order(user_id=2, location_id=location_b.id, order_date=date.today(), status="pending")
        setup_session.add_all([order_a, order_b])
        setup_session.commit()
        setup_session.refresh(order_a)
        setup_session.refresh(order_b)

        setup_session.add_all(
            [
                OrderItem(order_id=order_a.id, menu_item_id=menu.id, quantity=2),
                OrderItem(order_id=order_b.id, menu_item_id=menu.id, quantity=1),
            ]
        )
        setup_session.commit()
    finally:
        setup_session.close()

    with TestClient(app) as client:
        _login_with_role(client, "admin-summary@example.com", "admin")

        response = client.get("/catering/orders")

    assert response.status_code == 200
    assert "Acme" in response.text
    assert "Beta" in response.text
    assert "Main 1" in response.text
    assert "Main 2" in response.text
