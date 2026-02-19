from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.core.security import verify_password
from app.db.base import Base
from app.models import User
from app.services.account_service import ensure_default_admin


def _build_session_local() -> sessionmaker:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_ensure_default_admin_is_idempotent() -> None:
    session_local = _build_session_local()

    with session_local() as session:
        existed = ensure_default_admin(session)
        assert existed is False
        admins = session.scalars(select(User).where(User.username == "admin")).all()
        assert len(admins) == 1

    with session_local() as session:
        existed = ensure_default_admin(session)
        assert existed is True
        admins = session.scalars(select(User).where(User.username == "admin")).all()
        assert len(admins) == 1
        assert admins[0].is_active is True
        assert admins[0].role == "ADMIN"
        assert verify_password("123", admins[0].password_hash)


def test_ensure_default_admin_force_fixes_legacy_role_password_and_active() -> None:
    session_local = _build_session_local()

    with session_local() as session:
        session.execute(
            text(
                """
                INSERT INTO users (username, password_hash, role, is_active, created_at)
                VALUES ('admin', 'legacy-hash', 'customer', 0, CURRENT_TIMESTAMP)
                """
            )
        )
        session.commit()

    with session_local() as session:
        existed = ensure_default_admin(session)
        assert existed is True
        admin = session.scalar(select(User).where(User.username == "admin").limit(1))
        assert admin is not None
        assert admin.is_active is True
        assert admin.role == "ADMIN"
        assert verify_password("123", admin.password_hash)
