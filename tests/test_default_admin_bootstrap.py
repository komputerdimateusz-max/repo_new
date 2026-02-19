from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

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


def test_ensure_default_admin_reactivates_existing_inactive_user() -> None:
    session_local = _build_session_local()

    with session_local() as session:
        session.add(User(username="admin", password_hash="hash", role="ADMIN", is_active=False))
        session.commit()

    with session_local() as session:
        existed = ensure_default_admin(session)
        assert existed is True
        admin = session.scalar(select(User).where(User.username == "admin").limit(1))
        assert admin is not None
        assert admin.is_active is True
