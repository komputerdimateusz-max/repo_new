"""Admin settings page tests."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.main import app
from app.models.user import User


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def test_non_admin_cannot_access_settings(tmp_path: Path, monkeypatch) -> None:
    """Non-admin should be redirected away from settings."""
    engine = _build_test_engine(tmp_path / "test_non_admin_settings.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "employee@example.com", "password": "secret123", "role": "employee"},
            follow_redirects=False,
        )
        client.post(
            "/login",
            data={"email": "employee@example.com", "password": "secret123"},
            follow_redirects=False,
        )

        response = client.get("/settings", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/app?message=")


def test_admin_can_access_settings(tmp_path: Path, monkeypatch) -> None:
    """Admin should access settings page."""
    engine = _build_test_engine(tmp_path / "test_admin_settings.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "admin@example.com", "password": "secret123", "role": "admin"},
            follow_redirects=False,
        )
        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "secret123"},
            follow_redirects=False,
        )

        response = client.get("/settings")

    assert response.status_code == 200
    assert "User roles" in response.text


def test_admin_can_update_user_role(tmp_path: Path, monkeypatch) -> None:
    """Admin role update should persist."""
    engine = _build_test_engine(tmp_path / "test_admin_update_role.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        client.post(
            "/register",
            data={"email": "admin@example.com", "password": "secret123", "role": "admin"},
            follow_redirects=False,
        )
        client.post(
            "/register",
            data={"email": "target@example.com", "password": "secret123", "role": "employee"},
            follow_redirects=False,
        )
        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "secret123"},
            follow_redirects=False,
        )

        update_response = client.post(
            "/settings/users/2/role",
            data={"role": "catering"},
            follow_redirects=False,
        )

    assert update_response.status_code == 303

    db = testing_session_local()
    try:
        updated_user = db.query(User).filter(User.id == 2).first()
    finally:
        db.close()

    assert updated_user is not None
    assert updated_user.role == "catering"
