"""Tests for customer profile company selection and order integration."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.db.base import Base
from app.main import app
from app.models import Company, Customer, User


def _setup_test_db(tmp_path: Path) -> tuple[sessionmaker, int, int | None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_profile.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        user = User(
            username="customer1",
            password_hash=get_password_hash("secret"),
            role="CUSTOMER",
            email="customer1@example.com",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        alpha = Company(name="Alpha", is_active=True)
        beta = Company(name="Beta", is_active=True)
        inactive = Company(name="Inactive", is_active=False)
        db.add_all([alpha, beta, inactive])
        db.commit()
        db.refresh(alpha)
        db.refresh(beta)

        customer = Customer(
            user_id=user.id,
            name="Customer One",
            email="customer1@example.com",
            company_id=None,
            postal_code=None,
            is_active=True,
        )
        db.add(customer)
        db.commit()
        user_id = user.id
        beta_id = beta.id

    return TestingSessionLocal, user_id, beta_id


def test_profile_get_renders_active_companies(tmp_path: Path, monkeypatch) -> None:
    testing_session_local, user_id, selected_company_id = _setup_test_db(tmp_path)
    monkeypatch.setattr("app.main.SessionLocal", testing_session_local)
    monkeypatch.setattr(
        "app.main._require_role_page",
        lambda request, allowed: {"user_id": user_id, "username": "customer1", "role": "CUSTOMER"},
    )

    with testing_session_local() as db:
        customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
        assert customer is not None
        customer.company_id = selected_company_id
        db.commit()

    with TestClient(app) as client:
        response = client.get("/profile")

    assert response.status_code == 200
    assert "Mój profil" in response.text
    assert "Alpha" in response.text
    assert "Beta" in response.text
    assert "Inactive" not in response.text
    assert f'value="{selected_company_id}" selected' in response.text


def test_profile_post_persists_selected_company(tmp_path: Path, monkeypatch) -> None:
    testing_session_local, user_id, selected_company_id = _setup_test_db(tmp_path)
    monkeypatch.setattr("app.main.SessionLocal", testing_session_local)
    monkeypatch.setattr(
        "app.main._require_role_page",
        lambda request, allowed: {"user_id": user_id, "username": "customer1", "role": "CUSTOMER"},
    )

    with TestClient(app) as client:
        response = client.post("/profile", data={"company_id": str(selected_company_id)}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile?message=Zapisano"

    with testing_session_local() as db:
        customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
        assert customer is not None
        assert customer.company_id == selected_company_id


def test_order_page_shows_company_warning_when_missing(tmp_path: Path, monkeypatch) -> None:
    testing_session_local, user_id, _selected_company_id = _setup_test_db(tmp_path)
    monkeypatch.setattr("app.main.SessionLocal", testing_session_local)
    monkeypatch.setattr(
        "app.main._require_role_page",
        lambda request, allowed: {"user_id": user_id, "username": "customer1", "role": "CUSTOMER"},
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Wybierz firmę w profilu, aby złożyć zamówienie." in response.text
    assert "data-checkout-btn disabled" in response.text
