from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.db.base import Base
from app.main import app
from app.models import User


def _setup_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "admin_users.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr("app.main.engine", engine)
    monkeypatch.setattr("app.main.SessionLocal", testing_session_local)
    return testing_session_local


def _login(client: TestClient, username: str, password: str):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def test_admin_user_crud_and_role_redirect(tmp_path: Path, monkeypatch) -> None:
    session_local = _setup_db(tmp_path, monkeypatch)

    with TestClient(app) as client:
        login = _login(client, "admin", "123")
        assert login.status_code == 303
        assert login.headers["location"] == "/admin"

        create = client.post(
            "/admin/users/new",
            data={"username": "restauracja", "password": "test123", "role": "RESTAURANT", "is_active": "on"},
            follow_redirects=False,
        )
        assert create.status_code == 303
        assert create.headers["location"].startswith("/admin/users")

        user_page = client.get("/admin/users", follow_redirects=True)
        assert "restauracja" in user_page.text

        client.get("/logout")
        rest_login = _login(client, "restauracja", "test123")
        assert rest_login.status_code == 303
        assert rest_login.headers["location"] == "/restaurant"

    with session_local() as db:
        user = db.scalar(select(User).where(User.username == "restauracja").limit(1))
        assert user is not None
        assert user.role == "RESTAURANT"


def test_admin_access_control_and_inactive_login_message(tmp_path: Path, monkeypatch) -> None:
    session_local = _setup_db(tmp_path, monkeypatch)

    with session_local() as db:
        db.add(User(username="cust", password_hash=get_password_hash("secret123"), role="CUSTOMER", is_active=True))
        db.add(User(username="cust2", password_hash=get_password_hash("secret123"), role="CUSTOMER", is_active=True))
        db.commit()

    with TestClient(app) as client:
        anon = client.get("/admin/users", follow_redirects=False)
        assert anon.status_code == 303
        assert anon.headers["location"] == "/login"

        _login(client, "admin", "123")
        with session_local() as db:
            target = db.scalar(select(User).where(User.username == "cust").limit(1))
            assert target is not None
            target_id = target.id

        deactivate = client.post(f"/admin/users/{target_id}/active", data={}, follow_redirects=False)
        assert deactivate.status_code == 303

        client.get("/logout")
        denied = _login(client, "cust", "secret123")
        assert denied.status_code == 200
        assert "inactive" in denied.text.lower()

        # active non-admin user should receive 403 on admin routes
        customer_login = _login(client, "cust2", "secret123")
        assert customer_login.status_code == 303
        assert customer_login.headers["location"] == "/"
        forbidden = client.get("/admin", follow_redirects=False)
        assert forbidden.status_code == 403
