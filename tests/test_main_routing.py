"""Routing tests for UI root and API root."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_returns_ordering_ui_with_debug_markers() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ORDER UI NEW TEMPLATE LIVE" in response.text
    assert "ORDER_UI_BUILD:" in response.text
    assert '/static/order.css?v=' in response.text
    assert '/static/order.js?v=' in response.text
    assert response.headers["X-ORDER-UI-TEMPLATE"].endswith("/templates/order.html")
    assert response.headers["X-ORDER-UI-HANDLER"] == "app.main:root"
    assert response.headers["X-ORDER-UI-BUILD"]


def test_legacy_customer_order_routes_redirect_to_root() -> None:
    for path in ("/order", "/place-order", "/customer", "/customer/order"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/"


def test_order_static_assets_are_served() -> None:
    css_response = client.get("/static/order.css")
    js_response = client.get("/static/order.js")

    assert css_response.status_code == 200
    assert js_response.status_code == 200


def test_order_debug_endpoints_expose_route_and_source() -> None:
    routes_response = client.get("/__debug/routes")
    assert routes_response.status_code == 200
    assert "/ [GET] -> app.main:root" in routes_response.text

    source_response = client.get("/__debug/order-source")
    assert source_response.status_code == 200
    payload = source_response.json()
    assert payload["handler"] == "app.main:root"
    assert payload["template_path"].endswith("/templates/order.html")
    assert payload["static_css_href"].startswith("/static/order.css?v=")
    assert payload["static_js_href"].startswith("/static/order.js?v=")
    assert payload["git_sha"]


def test_api_root_returns_json_metadata() -> None:
    response = client.get("/api")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_docs_is_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text
