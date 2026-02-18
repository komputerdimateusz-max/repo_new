"""FastAPI entrypoint for single-restaurant catering MVP."""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Single Restaurant Catering MVP")
app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _resolve_build_id() -> str:
    """Resolve a short build identifier for debug rendering."""
    explicit = os.getenv("ORDER_UI_BUILD") or os.getenv("GIT_COMMIT_HASH")
    if explicit:
        return explicit.strip()[:12]

    try:
        commit = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR)
            .decode("utf-8")
            .strip()
        )
        if commit:
            return commit
    except Exception:
        pass

    return uuid4().hex[:8]


ORDER_UI_BUILD_ID = _resolve_build_id()
ORDER_UI_BUILD_TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
ORDER_TEMPLATE_NAME = "order.html"
ORDER_TEMPLATE_PATH = str((BASE_DIR / "templates" / ORDER_TEMPLATE_NAME).resolve())


def _order_handler_ref() -> str:
    """Return canonical handler reference for order page."""
    return f"{root.__module__}:{root.__name__}"


def _route_listing() -> str:
    """Render a debug list of all registered routes."""
    lines: list[str] = []
    for route in app.routes:
        route_methods = getattr(route, "methods", None) or []
        methods = ",".join(sorted(route_methods))
        endpoint = getattr(route, "endpoint", None)
        endpoint_name = getattr(endpoint, "__name__", "<no-endpoint>")
        endpoint_module = getattr(endpoint, "__module__", "<unknown>")
        lines.append(f"{route.path} [{methods}] -> {endpoint_module}:{endpoint_name}")
    return "\n".join(sorted(lines))


@app.on_event("startup")
def startup() -> None:
    """Ensure DB schema exists."""
    Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    """Render MVP customer ordering page."""
    menu_items = [
        {"name": "Kotlet schabowy", "description": "Ziemniaki puree, surówka", "price": "29,00 zł"},
        {"name": "Pierogi ruskie", "description": "8 sztuk, cebulka", "price": "24,00 zł"},
        {"name": "Sałatka grecka", "description": "Feta, oliwki, warzywa", "price": "21,00 zł"},
        {"name": "Zupa pomidorowa", "description": "Makaron, natka pietruszki", "price": "14,00 zł"},
        {"name": "Makaron pesto", "description": "Parmezan, orzeszki piniowe", "price": "26,00 zł"},
        {"name": "Naleśniki z twarogiem", "description": "2 sztuki, sos owocowy", "price": "18,00 zł"},
    ]
    cart_items = [
        {"name": "Kotlet schabowy", "qty": 1, "price": "29,00 zł"},
        {"name": "Zupa pomidorowa", "qty": 2, "price": "28,00 zł"},
    ]
    context = {
        "request": request,
        "menu_items": menu_items,
        "cart_items": cart_items,
        "total": "57,00 zł",
        "order_ui_build": f"{ORDER_UI_BUILD_ID} {ORDER_UI_BUILD_TS}",
        "order_ui_git_sha": ORDER_UI_BUILD_ID,
        "order_ui_template_path": ORDER_TEMPLATE_PATH,
        "order_ui_template_name": ORDER_TEMPLATE_NAME,
    }
    response = templates.TemplateResponse(request, ORDER_TEMPLATE_NAME, context)
    response.headers["X-ORDER-UI-TEMPLATE"] = ORDER_TEMPLATE_PATH
    response.headers["X-ORDER-UI-HANDLER"] = _order_handler_ref()
    response.headers["X-ORDER-UI-BUILD"] = ORDER_UI_BUILD_ID
    return response


@app.get("/order", include_in_schema=False)
@app.get("/place-order", include_in_schema=False)
@app.get("/customer", include_in_schema=False)
@app.get("/customer/order", include_in_schema=False)
def redirect_legacy_order_routes() -> RedirectResponse:
    """Redirect legacy customer order paths to canonical root page."""
    return RedirectResponse(url="/", status_code=307)


@app.get("/__debug/routes", include_in_schema=False, response_class=PlainTextResponse)
def debug_routes() -> PlainTextResponse:
    """Return registered route listing for routing verification."""
    return PlainTextResponse(_route_listing())


@app.get("/__debug/order-source", include_in_schema=False)
def debug_order_source() -> dict[str, str]:
    """Return canonical order UI source details."""
    return {
        "handler": _order_handler_ref(),
        "template_path": ORDER_TEMPLATE_PATH,
        "static_css_href": f"/static/order.css?v={ORDER_UI_BUILD_ID}",
        "static_js_href": f"/static/order.js?v={ORDER_UI_BUILD_ID}",
        "git_sha": ORDER_UI_BUILD_ID,
    }


@app.get("/api")
def api_root() -> dict[str, str]:
    """Return API root metadata."""
    return {
        "app": settings.app_name,
        "message": "MVP 1.0 single restaurant catering API",
        "docs": "/docs",
        "admin": "/api/v1/admin",
        "order": "/api/v1/order",
    }
