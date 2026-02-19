from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.base import Base
from app.core.security import get_password_hash
from app import main as main_module
from app.main import app
from app.models import User


def _prepare_db(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'roles.db'}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module, "SessionLocal", testing_session_local)
    return testing_session_local


def test_login_redirects_to_role_landing(tmp_path: Path, monkeypatch) -> None:
    session_local = _prepare_db(tmp_path, monkeypatch)
    with session_local() as db:
        db.add_all(
            [
                User(username="admin", password_hash=get_password_hash("123"), role="ADMIN", is_active=True),
                User(username="restaurant1", password_hash=get_password_hash("123"), role="RESTAURANT", is_active=True),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        admin_res = client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
        client.post("/logout")
        rest_res = client.post("/login", data={"username": "restaurant1", "password": "123"}, follow_redirects=False)

    assert admin_res.status_code == 303
    assert admin_res.headers["location"] == "/admin"
    assert rest_res.status_code == 303
    assert rest_res.headers["location"] == "/restaurant"


def test_customer_cannot_access_admin_or_restaurant(tmp_path: Path, monkeypatch) -> None:
    session_local = _prepare_db(tmp_path, monkeypatch)
    with session_local() as db:
        db.add(User(username="customer1", password_hash=get_password_hash("pass"), role="CUSTOMER", is_active=True))
        db.commit()
    with TestClient(app) as client:
        login_res = client.post("/login", data={"username": "customer1", "password": "pass"}, follow_redirects=False)
        assert login_res.headers["location"] == "/"
        admin_res = client.get("/admin", follow_redirects=False)
        restaurant_res = client.get("/restaurant", follow_redirects=False)

    assert admin_res.status_code == 403
    assert restaurant_res.status_code == 303
    assert restaurant_res.headers["location"] == "/"


def test_admin_login_normalizes_role_and_debug_whoami(tmp_path: Path, monkeypatch) -> None:
    session_local = _prepare_db(tmp_path, monkeypatch)
    with session_local() as db:
        db.add(User(username="admin", password_hash=get_password_hash("123"), role="admin", is_active=True))
        db.commit()

    with TestClient(app) as client:
        login_res = client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
        whoami = client.get("/__debug/whoami")

    assert login_res.status_code == 303
    assert login_res.headers["location"] == "/admin"
    assert whoami.status_code == 200
    payload = whoami.json()
    assert payload["session"]["role"] == "ADMIN"
    assert payload["session"]["username"] == "admin"
    assert payload["db_user"]["role"] == "ADMIN"
    assert payload["db_user"]["is_active"] is True

    with session_local() as db:
        db_role = db.scalar(select(User.role).where(User.username == "admin"))
    assert db_role == "ADMIN"
