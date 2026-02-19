"""Magic login flow resilience tests."""

from fastapi.testclient import TestClient

from app import main


def test_login_send_invalid_email_shows_validation_message() -> None:
    """Invalid email should render login page with a user-friendly validation error."""
    with TestClient(main.app) as client:
        response = client.post("/login/send", data={"email": "invalid-email"})

    assert response.status_code == 200
    assert "Invalid email" in response.text


def test_login_send_exception_is_handled(monkeypatch) -> None:
    """Unexpected send failures should render a friendly error and not crash."""

    async def broken_payload(_request):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "_read_login_payload", broken_payload)

    with TestClient(main.app) as client:
        response = client.post("/login/send", data={"email": "pilot@example.com"})

    assert response.status_code == 200
    assert "Could not send code. Check server logs." in response.text


def test_debug_last_login_code_requires_debug_flag(monkeypatch) -> None:
    """Debug endpoint should be hidden unless DEBUG=true."""
    main.MAGIC_CODES["pilot@example.com"] = {"code": "123456", "expires_at": 9999999999.0}

    monkeypatch.setenv("DEBUG", "false")
    with TestClient(main.app) as client:
        disabled_response = client.get("/__debug/last_login_code", params={"email": "pilot@example.com"})
    assert disabled_response.status_code == 404

    monkeypatch.setenv("DEBUG", "true")
    with TestClient(main.app) as client:
        enabled_response = client.get("/__debug/last_login_code", params={"email": "pilot@example.com"})

    assert enabled_response.status_code == 200
    payload = enabled_response.json()
    assert payload["code"] == "123456"
    assert payload["email"] == "pilot@example.com"
