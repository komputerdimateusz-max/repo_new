from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.main import app
from app.models import Customer, User


def _setup_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "customer_registration.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr("app.main.engine", engine)
    monkeypatch.setattr("app.main.SessionLocal", testing_session_local)
    return testing_session_local


def test_customer_self_registration_creates_customer_and_logs_in(tmp_path: Path, monkeypatch) -> None:
    session_local = _setup_db(tmp_path, monkeypatch)

    with TestClient(app) as client:
        page = client.get("/register")
        assert page.status_code == 200
        assert "Rejestracja dotyczy tylko klientów." in page.text

        response = client.post(
            "/register",
            data={"username": "test1", "password": "test123", "confirm_password": "test123"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"

        home = client.get("/", follow_redirects=False)
        assert home.status_code == 200

        client.get("/logout", follow_redirects=False)
        login = client.post(
            "/login",
            data={"username": "test1", "password": "test123"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/"

        client.get("/logout", follow_redirects=False)
        client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
        users_page = client.get("/admin/users", follow_redirects=False)
        assert users_page.status_code == 200
        assert "test1" in users_page.text

    with session_local() as db:
        user = db.scalar(select(User).where(User.username == "test1").limit(1))
        assert user is not None
        assert user.role == "CUSTOMER"
        assert user.is_active is True

        customer = db.scalar(select(Customer).where(Customer.user_id == user.id).limit(1))
        assert customer is not None
        assert customer.company_id is None


def test_register_redirects_logged_in_users(tmp_path: Path, monkeypatch) -> None:
    _setup_db(tmp_path, monkeypatch)

    with TestClient(app) as client:
        login = client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
        assert login.status_code == 303

        register_page = client.get("/register", follow_redirects=False)
        assert register_page.status_code == 303
        assert register_page.headers["location"] == "/admin"
