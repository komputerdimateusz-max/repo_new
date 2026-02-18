"""Routing tests for UI root and API root."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_returns_ordering_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Place Order" in response.text
    assert "Wybierz firmę" in response.text


def test_api_root_returns_json_metadata() -> None:
    response = client.get("/api")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_docs_is_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text
