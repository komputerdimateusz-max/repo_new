"""Regression tests for session login redirect loops."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


def test_login_page_is_accessible_when_logged_out() -> None:
    with TestClient(app) as client:
        response = client.get("/login", follow_redirects=False)

    assert response.status_code == 200


def test_root_redirects_logged_in_admin_to_admin_page_without_loop(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main._session_user",
        lambda request: {"user_id": 1, "username": "admin", "role": "ADMIN"},
    )

    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_login_sets_session_cookie_and_redirects_to_role_landing(monkeypatch) -> None:
    dummy_user = SimpleNamespace(id=7, username="alice", role="CUSTOMER")

    monkeypatch.setattr("app.main.authenticate_user", lambda db, username, password: dummy_user)
    monkeypatch.setattr("app.main.ensure_customer_profile", lambda db, user: SimpleNamespace(id=9, email="alice@example.com"))

    with TestClient(app) as client:
        response = client.post(
            "/login",
            data={"username": "alice", "password": "secret"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "session=" in response.headers.get("set-cookie", "")


def test_debug_auth_endpoint_reports_session_when_debug_enabled(monkeypatch) -> None:
    monkeypatch.setattr("app.main.settings.debug", True)
    dummy_user = SimpleNamespace(id=10, username="debug-user", role="CUSTOMER")

    monkeypatch.setattr("app.main.authenticate_user", lambda db, username, password: dummy_user)
    monkeypatch.setattr("app.main.ensure_customer_profile", lambda db, user: SimpleNamespace(id=10, email="debug-user@example.com"))

    with TestClient(app) as client:
        login_response = client.post(
            "/login",
            data={"username": "debug-user", "password": "secret"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        response = client.get("/__debug/auth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_present"] is True
    assert payload["user_id"] == 10
    assert payload["role"] == "CUSTOMER"
    assert payload["cookie_seen"] is True
