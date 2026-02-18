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
    assert "ORDER_UI_BUILD:" in response.text
    assert '/static/order.css' in response.text
    assert '/static/order.js' in response.text


def test_legacy_customer_order_routes_redirect_to_root() -> None:
    for path in ("/order", "/place-order", "/customer/order"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/"


def test_order_static_assets_are_served() -> None:
    css_response = client.get("/static/order.css")
    js_response = client.get("/static/order.js")

    assert css_response.status_code == 200
    assert js_response.status_code == 200


def test_api_root_returns_json_metadata() -> None:
    response = client.get("/api")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_docs_is_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text
