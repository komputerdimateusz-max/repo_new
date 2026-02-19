"""Username/password login flow tests."""

from fastapi.testclient import TestClient

from app import main


def test_login_with_invalid_credentials_shows_validation_message() -> None:
    with TestClient(main.app) as client:
        response = client.post("/login", data={"username": "bad", "password": "bad"})
    assert response.status_code == 200
    assert "Invalid username or password" in response.text


def test_default_admin_exists_and_login_redirects_to_admin() -> None:
    with TestClient(main.app) as client:
        response = client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_debug_whoami_reports_admin_role_in_db_and_session() -> None:
    with TestClient(main.app) as client:
        login = client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
        assert login.status_code == 303

        whoami = client.get("/__debug/whoami")

    assert whoami.status_code == 200
    payload = whoami.json()
    assert payload["db"]["username"] == "admin"
    assert payload["db"]["role"] == "ADMIN"
    assert payload["db"]["is_active"] is True
    assert payload["session"]["username"] == "admin"
    assert payload["session"]["role"] == "ADMIN"


def test_logout_clears_session() -> None:
    with TestClient(main.app) as client:
        client.post("/login", data={"username": "admin", "password": "123"}, follow_redirects=False)
        logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
