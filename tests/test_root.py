"""Root endpoint tests."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_redirects_to_docs() -> None:
    """Root endpoint should redirect to /docs."""
    response = client.get("/", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/docs"
