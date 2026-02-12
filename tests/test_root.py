"""Frontend page endpoint tests."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_renders_landing_page() -> None:
    """Root endpoint should render the landing page."""
    response = client.get("/")

    assert response.status_code == 200
    assert "repo_new" in response.text


def test_login_page_renders() -> None:
    """Login endpoint should render the login page."""
    response = client.get("/login")

    assert response.status_code == 200


def test_register_page_renders() -> None:
    """Register endpoint should render the registration page."""
    response = client.get("/register")

    assert response.status_code == 200


def test_app_page_requires_authentication() -> None:
    """App endpoint should redirect unauthenticated users to login."""
    response = client.get("/app", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
