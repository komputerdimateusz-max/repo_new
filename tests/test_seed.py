"""Database seed behavior tests."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.seed import ensure_admin_user
from app.models.user import User


def _build_test_engine(db_file: Path) -> Engine:
    return create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )


def test_ensure_admin_user_creates_user_in_dev(tmp_path: Path, monkeypatch) -> None:
    """Admin seed should create the user when environment is development."""
    engine = _build_test_engine(tmp_path / "seed_dev.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "admin_email", "admin@local.dev")
    monkeypatch.setattr(settings, "admin_password", "Admin123!")
    monkeypatch.setattr(settings, "admin_role", "admin")

    hashed_password = "hashed-admin-password"
    monkeypatch.setattr("app.db.seed.get_password_hash", lambda _: hashed_password)

    with testing_session_local() as session:
        ensure_admin_user(session)

    with testing_session_local() as session:
        user: User | None = session.query(User).filter(User.email == "admin@local.dev").first()
        assert user is not None
        assert user.role == "admin"
        assert user.hashed_password == hashed_password


def test_ensure_admin_user_skips_creation_in_non_dev(tmp_path: Path, monkeypatch) -> None:
    """Admin seed should not create users when environment is not development."""
    engine = _build_test_engine(tmp_path / "seed_prod.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "admin_email", "admin@local.dev")
    monkeypatch.setattr(settings, "admin_password", "Admin123!")
    monkeypatch.setattr(settings, "admin_role", "admin")

    with testing_session_local() as session:
        ensure_admin_user(session)

    with testing_session_local() as session:
        user: User | None = session.query(User).filter(User.email == "admin@local.dev").first()
        assert user is None
