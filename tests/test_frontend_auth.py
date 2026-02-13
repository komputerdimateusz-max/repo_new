"""Frontend authentication flow tests."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import session as db_session
from app.main import app


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def test_get_register_returns_ok() -> None:
    """GET /register should render the registration page."""
    with TestClient(app) as client:
        response = client.get("/register")

    assert response.status_code == 200


def test_post_register_creates_user_and_redirects(tmp_path: Path, monkeypatch) -> None:
    """POST /register should create a user and redirect to /login."""
    engine = _build_test_engine(tmp_path / "test_register_form.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        response = client.post(
            "/register",
            data={"email": "newuser@example.com", "password": "secret123", "role": "customer"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_post_login_with_valid_credentials_redirects_to_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """POST /login should redirect to /app for valid credentials."""
    engine = _build_test_engine(tmp_path / "test_login_form.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        register_response = client.post(
            "/register",
            data={"email": "loginform@example.com", "password": "secret123", "role": "customer"},
            follow_redirects=False,
        )
        assert register_response.status_code == 303

        login_response = client.post(
            "/login",
            data={"email": "loginform@example.com", "password": "secret123"},
            follow_redirects=False,
        )

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/app"
    assert "access_token" in login_response.headers.get("set-cookie", "")
