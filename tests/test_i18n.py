"""Language switch tests."""

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


def test_switching_language_sets_cookie_and_translates_login(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Switch language route should set cookie and alter rendered text."""
    engine = _build_test_engine(tmp_path / "test_i18n.db")
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session_local)

    with TestClient(app) as client:
        switch_response = client.get("/lang/pl", headers={"referer": "/login"}, follow_redirects=False)
        assert switch_response.status_code == 303
        assert switch_response.headers["location"] == "/login"
        assert "lang=pl" in switch_response.headers.get("set-cookie", "")

        login_response = client.get("/login", cookies={"lang": "pl"})

    assert login_response.status_code == 200
    assert "Logowanie" in login_response.text
