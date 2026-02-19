"""FastAPI entrypoint for single-restaurant catering MVP."""

import os
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import base64

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.seed import ensure_seed_data
from app.db.session import SessionLocal, engine
from app.models import Customer

BASE_DIR = Path(__file__).resolve().parent.parent
MAGIC_CODE_TTL_SECONDS = 10 * 60
RATE_WINDOW_SECONDS = 10 * 60

app = FastAPI(title="Single Restaurant Catering MVP")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)
app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
MAGIC_CODES: dict[str, dict[str, float | str]] = {}
SEND_RATE_LIMIT: dict[str, list[float]] = {}
VERIFY_RATE_LIMIT: dict[str, list[float]] = {}


async def _read_login_payload(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await request.json()
    form = await request.form()
    return {"email": form.get("email", ""), "code": form.get("code", "")}


def _resolve_build_id() -> str:
    explicit = os.getenv("ORDER_UI_BUILD") or os.getenv("GIT_COMMIT_HASH")
    if explicit:
        return explicit.strip()[:12]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR).decode("utf-8").strip()
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
    return f"{root.__module__}:{root.__name__}"


def _route_listing() -> str:
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
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        ensure_seed_data(session)


def _current_customer(request: Request) -> dict:
    return {
        "customer_id": request.session.get("customer_id"),
        "customer_email": request.session.get("customer_email"),
    }


def _require_login(request: Request) -> RedirectResponse | None:
    if _current_customer(request).get("customer_id"):
        return None
    return RedirectResponse(url="/login", status_code=307)


def _trim_window(bucket: dict[str, list[float]], key: str) -> list[float]:
    now = time.time()
    entries = [stamp for stamp in bucket.get(key, []) if now - stamp < RATE_WINDOW_SECONDS]
    bucket[key] = entries
    return entries


def _is_rate_limited(bucket: dict[str, list[float]], key: str, limit: int) -> bool:
    entries = _trim_window(bucket, key)
    if len(entries) >= limit:
        return True
    entries.append(time.time())
    bucket[key] = entries
    return False

def _admin_credentials() -> tuple[str, str]:
    if settings.admin_user and settings.admin_pass:
        return settings.admin_user, settings.admin_pass
    if settings.app_env == "dev":
        print("[ADMIN] ADMIN_USER/ADMIN_PASS missing - using dev fallback admin/admin")
        return "admin", "admin"
    raise HTTPException(status_code=500, detail="Admin credentials are not configured.")


def _is_admin_authorized(request: Request) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False
    if ":" not in decoded:
        return False
    return tuple(decoded.split(":", 1)) == _admin_credentials()


def _require_admin_page_auth(request: Request) -> None:
    if not _is_admin_authorized(request):
        raise HTTPException(status_code=401, detail="Admin authentication required", headers={"WWW-Authenticate": "Basic"})



@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect
    context = {
        "request": request,
        "order_ui_build": f"{ORDER_UI_BUILD_ID} {ORDER_UI_BUILD_TS}",
        "order_ui_git_sha": ORDER_UI_BUILD_ID,
        "order_ui_template_path": ORDER_TEMPLATE_PATH,
        "order_ui_template_name": ORDER_TEMPLATE_NAME,
        "user_email": _current_customer(request).get("customer_email"),
        "debug_ui": settings.debug_ui,
    }
    response = templates.TemplateResponse(request, ORDER_TEMPLATE_NAME, context)
    response.headers["X-ORDER-UI-TEMPLATE"] = ORDER_TEMPLATE_PATH
    response.headers["X-ORDER-UI-BUILD"] = ORDER_UI_BUILD_ID
    response.headers["X-ORDER-UI-HANDLER"] = _order_handler_ref()
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, message: str | None = None) -> HTMLResponse:
    if _current_customer(request).get("customer_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "message": message, "email": ""})


@app.post("/login/send", response_class=HTMLResponse)
async def login_send(request: Request) -> HTMLResponse:
    data = await _read_login_payload(request)
    clean_email = str(data.get("email", "")).strip().lower()
    if not clean_email:
        return login_page(request, message="Invalid code")

    if _is_rate_limited(SEND_RATE_LIMIT, clean_email, 5):
        return login_page(request, message="Too many requests. Try again later.")

    magic_code = f"{random.randint(0, 999999):06d}"
    MAGIC_CODES[clean_email] = {"code": magic_code, "expires_at": time.time() + MAGIC_CODE_TTL_SECONDS}
    if settings.app_env == "dev":
        print(f"[LOGIN] Magic code for {clean_email}: {magic_code}")
    return login_page(request, message="Code sent (check server logs)")


@app.post("/login/verify")
async def login_verify(request: Request) -> RedirectResponse | HTMLResponse:
    data = await _read_login_payload(request)
    clean_email = str(data.get("email", "")).strip().lower()
    code = str(data.get("code", "")).strip()

    if _is_rate_limited(VERIFY_RATE_LIMIT, clean_email, 10):
        return login_page(request, message="Too many requests. Try again later.")

    entry = MAGIC_CODES.get(clean_email)
    if not entry or entry.get("expires_at", 0) < time.time() or entry.get("code") != code:
        return login_page(request, message="Invalid code")

    with SessionLocal() as db:
        customer = db.query(Customer).filter(Customer.email == clean_email).first()
        if customer is None:
            customer = Customer(email=clean_email, name=clean_email.split("@")[0], company_id=None, postal_code=None, is_active=True)
            db.add(customer)
            db.commit()
            db.refresh(customer)

    request.session["customer_id"] = customer.id
    request.session["customer_email"] = customer.email
    MAGIC_CODES.pop(clean_email, None)
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    response = RedirectResponse(url="/login", status_code=303)
    return response


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "profile.html", {"request": request, "email": _current_customer(request).get("customer_email")})


@app.get("/my-order", response_class=HTMLResponse)
def my_order_page(request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "my_order.html", {"request": request, "user_email": _current_customer(request).get("customer_email")})


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request) -> HTMLResponse:
    _require_admin_page_auth(request)
    return templates.TemplateResponse(request, "admin_settings.html", {"request": request})


@app.get("/admin/menu", response_class=HTMLResponse)
def admin_menu_page(request: Request) -> HTMLResponse:
    _require_admin_page_auth(request)
    return templates.TemplateResponse(request, "admin_menu.html", {"request": request})


@app.get("/admin/specials", response_class=HTMLResponse)
def admin_specials_page(request: Request) -> HTMLResponse:
    _require_admin_page_auth(request)
    return templates.TemplateResponse(request, "admin_specials.html", {"request": request})


@app.get("/admin/orders/today", response_class=HTMLResponse)
def admin_orders_page(request: Request) -> HTMLResponse:
    _require_admin_page_auth(request)
    return templates.TemplateResponse(request, "admin_orders_today.html", {"request": request})


@app.get("/admin/orders/today.csv")
def admin_orders_csv_redirect(request: Request) -> RedirectResponse:
    _require_admin_page_auth(request)
    return RedirectResponse(url="/api/v1/admin/orders/today.csv", status_code=307)


@app.get("/order", include_in_schema=False)
@app.get("/place-order", include_in_schema=False)
@app.get("/customer", include_in_schema=False)
@app.get("/customer/order", include_in_schema=False)
def redirect_legacy_order_routes() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=307)


@app.get("/__debug/routes", include_in_schema=False, response_class=PlainTextResponse)
def debug_routes() -> PlainTextResponse:
    return PlainTextResponse(_route_listing())


@app.get("/__debug/order-source", include_in_schema=False)
def debug_order_source() -> dict[str, str]:
    return {
        "handler": _order_handler_ref(),
        "template_path": ORDER_TEMPLATE_PATH,
        "static_css_href": f"/static/order.css?v={ORDER_UI_BUILD_ID}",
        "static_js_href": f"/static/order.js?v={ORDER_UI_BUILD_ID}",
        "git_sha": ORDER_UI_BUILD_ID,
    }


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"app": settings.app_name, "message": "MVP 1.0 single restaurant catering API", "docs": "/docs", "api_v1": "/api/v1"}
