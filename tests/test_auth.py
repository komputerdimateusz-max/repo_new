"""Authentication endpoint tests."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import session as db_session
from app.main import app
from app.models import Customer


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def test_register_creates_user(tmp_path: Path, monkeypatch) -> None:
    """Register should create a user and return identity fields."""
    engine = _build_test_engine(tmp_path / "test_register.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "secret123", "role": "customer"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "user@example.com"
    assert body["role"] == "customer"

    with testing_session_local() as db:
        customer = db.scalar(select(Customer).where(Customer.user_id == int(body["id"])).limit(1))
        assert customer is not None
        assert customer.email == "user@example.com"


def test_login_returns_token(tmp_path: Path, monkeypatch) -> None:
    """Login should return a bearer access token for valid credentials."""
    engine = _build_test_engine(tmp_path / "test_login.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/api/v1/auth/register",
            json={"email": "login@example.com", "password": "secret123", "role": "customer"},
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "secret123"},
        )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert isinstance(payload.get("access_token"), str)
    assert payload.get("token_type") == "bearer"


def test_me_returns_current_user(tmp_path: Path, monkeypatch) -> None:
    """Authenticated me endpoint should return the logged-in user."""
    engine = _build_test_engine(tmp_path / "test_me.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/api/v1/auth/register",
            json={"email": "me@example.com", "password": "secret123", "role": "customer"},
        )
        assert register_response.status_code == 201

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "me@example.com", "password": "secret123"},
        )
        assert login_response.status_code == 200

        token = login_response.json()["access_token"]
        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload["email"] == "me@example.com"
    assert me_payload["role"] == "customer"
    assert isinstance(me_payload["id"], int)
