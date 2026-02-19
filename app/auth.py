"""Session-based authentication helpers for server-rendered routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse

ROLE_LANDING: dict[str, str] = {
    "ADMIN": "/admin",
    "RESTAURANT": "/restaurant",
    "CUSTOMER": "/",
}


SessionUser = dict[str, Any]


def role_landing(role: str | None) -> str:
    """Resolve role landing path with customer root fallback."""
    return ROLE_LANDING.get(str(role), "/")


def get_current_user(request: Request) -> SessionUser | None:
    """Return current authenticated user snapshot from session."""
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    username = request.session.get("username")
    if user_id and role and username:
        return {"user_id": user_id, "role": role, "username": username}
    return None


def require_login(request: Request) -> SessionUser | RedirectResponse:
    """Require an authenticated session for page access."""
    current = get_current_user(request)
    if current is None:
        return RedirectResponse(url="/login", status_code=303)
    return current


def require_role(*roles: str) -> Callable[[Request], SessionUser | RedirectResponse]:
    """Build a role-check callable for session-rendered routes."""

    allowed = {role.upper() for role in roles}

    def _checker(request: Request) -> SessionUser | RedirectResponse:
        current = require_login(request)
        if isinstance(current, RedirectResponse):
            return current
        current_role = str(current.get("role", "")).upper()
        if current_role not in allowed:
            return RedirectResponse(url=role_landing(current_role), status_code=303)
        return current

    return _checker
