"""Role normalization tests for user creation and SQLite startup migration."""

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.migrations import ensure_sqlite_schema
from app.models.user import User
from app.services.user_service import create_user


def test_create_user_normalizes_lowercase_role() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        user = create_user(
            db=session,
            username="new-customer",
            hashed_password="hash",
            role="customer",
            email="new-customer@example.com",
        )

    assert user.role == "CUSTOMER"


def test_create_user_rejects_unknown_role() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        try:
            create_user(
                db=session,
                username="new-manager",
                hashed_password="hash",
                role="manager",
                email="new-manager@example.com",
            )
            assert False, "Expected ValueError for unknown role"
        except ValueError as exc:
            assert "Invalid role" in str(exc)


def test_sqlite_migration_normalizes_legacy_lowercase_roles() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (username, password_hash, role, email, is_active, created_at)
                VALUES
                    ('legacy-admin', 'hash', 'admin', 'legacy-admin@example.com', 1, CURRENT_TIMESTAMP),
                    ('legacy-rest', 'hash', 'restaurant', 'legacy-rest@example.com', 1, CURRENT_TIMESTAMP),
                    ('legacy-customer', 'hash', 'customer', 'legacy-customer@example.com', 1, CURRENT_TIMESTAMP)
                """
            )
        )

    ensure_sqlite_schema(engine)

    with Session(engine) as session:
        roles = set(session.scalars(select(User.role)).all())

    assert roles == {"ADMIN", "RESTAURANT", "CUSTOMER"}
