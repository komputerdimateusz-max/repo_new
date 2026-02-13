"""Order status flow tests for restaurant/admin UI endpoint."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.location import Location
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def _login_with_role(client: TestClient, email: str, role: str) -> None:
    payload: dict[str, str] = {"email": email, "password": "secret123", "role": role}
    if role == "restaurant":
        payload["restaurant_id"] = "1"
    register_response = client.post(
        "/register",
        data=payload,
        follow_redirects=False,
    )
    assert register_response.status_code == 303

    login_response = client.post(
        "/login",
        data={"email": email, "password": "secret123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303


def test_restaurant_can_progress_own_order_status(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_status_progress.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "restaurant-status@example.com", "restaurant")
        setup_session: Session = testing_session_local()
        try:
            restaurant_user: User = setup_session.query(User).filter(User.email == "restaurant-status@example.com").one()
            location = Location(company_name="Status Co", address="Status Street", is_active=True)
            setup_session.add(location)
            setup_session.flush()
            order = Order(
                user_id=restaurant_user.id,
                location_id=location.id,
                restaurant_id=restaurant_user.restaurant_id,
                order_date=date.today(),
                status="pending",
            )
            setup_session.add(order)
            setup_session.commit()
            setup_session.refresh(order)
            order_id = order.id
        finally:
            setup_session.close()

        response = client.post(
            f"/restaurant/orders/{order_id}/status",
            data={"new_status": "confirmed", "selected_date": date.today().isoformat(), "selected_status": "all"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "message=" in response.headers["location"]

    verify_session: Session = testing_session_local()
    try:
        updated_order: Order = verify_session.query(Order).filter(Order.id == order_id).one()
        assert updated_order.status == "confirmed"
        assert updated_order.status_updated_at is not None
        assert updated_order.confirmed_at is not None
    finally:
        verify_session.close()


def test_restaurant_cannot_change_other_restaurant_order(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_status_forbidden.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "restaurant-scope@example.com", "restaurant")

        setup_session: Session = testing_session_local()
        try:
            current_user: User = setup_session.query(User).filter(User.email == "restaurant-scope@example.com").one()
            location = Location(company_name="Scope Co", address="Scope Street", is_active=True)
            setup_session.add(location)
            setup_session.flush()
            other_restaurant = Restaurant(name="Second Restaurant", is_active=True)
            setup_session.add(other_restaurant)
            setup_session.flush()

            foreign_order = Order(
                user_id=current_user.id,
                location_id=location.id,
                restaurant_id=other_restaurant.id,
                order_date=date.today(),
                status="pending",
            )
            setup_session.add(foreign_order)
            setup_session.commit()
            setup_session.refresh(foreign_order)
            foreign_order_id = foreign_order.id
        finally:
            setup_session.close()

        response = client.post(
            f"/restaurant/orders/{foreign_order_id}/status",
            data={"new_status": "confirmed", "selected_date": date.today().isoformat(), "selected_status": "all"},
            follow_redirects=False,
        )

    assert response.status_code == 403


def test_invalid_transition_is_blocked(tmp_path: Path, monkeypatch) -> None:
    engine = _build_test_engine(tmp_path / "test_status_invalid_transition.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        _login_with_role(client, "restaurant-invalid@example.com", "restaurant")
        setup_session: Session = testing_session_local()
        try:
            restaurant_user: User = setup_session.query(User).filter(User.email == "restaurant-invalid@example.com").one()
            location = Location(company_name="Invalid Co", address="Invalid Street", is_active=True)
            setup_session.add(location)
            setup_session.flush()
            order = Order(
                user_id=restaurant_user.id,
                location_id=location.id,
                restaurant_id=restaurant_user.restaurant_id,
                order_date=date.today(),
                status="delivered",
            )
            setup_session.add(order)
            setup_session.commit()
            setup_session.refresh(order)
            order_id = order.id
        finally:
            setup_session.close()

        response = client.post(
            f"/restaurant/orders/{order_id}/status",
            data={"new_status": "prepared", "selected_date": date.today().isoformat(), "selected_status": "all"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
