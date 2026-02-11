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


def test_app_page_renders() -> None:
    """App endpoint should render the dashboard placeholder page."""
    response = client.get("/app")

    assert response.status_code == 200
