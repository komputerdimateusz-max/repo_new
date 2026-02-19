"""FastAPI entrypoint for single-restaurant catering MVP."""

import os
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.seed import ensure_seed_data
from app.db.session import SessionLocal, engine
from app.models import Company, Customer

BASE_DIR = Path(__file__).resolve().parent.parent
CUSTOMER_COOKIE = "customer_session"
ADMIN_COOKIE = "admin_session"

app = FastAPI(title="Single Restaurant Catering MVP")
app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
MAGIC_CODES: dict[str, str] = {}


def create_token(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def read_token(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return jwt.decode(raw, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return {}


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
    return read_token(request.cookies.get(CUSTOMER_COOKIE))


def _require_login(request: Request) -> RedirectResponse | None:
    if _current_customer(request).get("customer_id"):
        return None
    return RedirectResponse(url="/login", status_code=307)


@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect
    context = {"request": request, "order_ui_build": f"{ORDER_UI_BUILD_ID} {ORDER_UI_BUILD_TS}", "order_ui_git_sha": ORDER_UI_BUILD_ID, "order_ui_template_path": ORDER_TEMPLATE_PATH, "order_ui_template_name": ORDER_TEMPLATE_NAME, "user_email": _current_customer(request).get("customer_email")}
    response = templates.TemplateResponse(request, ORDER_TEMPLATE_NAME, context)
    response.headers["X-ORDER-UI-TEMPLATE"] = ORDER_TEMPLATE_PATH
    response.headers["X-ORDER-UI-BUILD"] = ORDER_UI_BUILD_ID
    response.headers["X-ORDER-UI-HANDLER"] = _order_handler_ref()
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if _current_customer(request).get("customer_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "message": request.query_params.get("error"), "email": ""})


@app.post("/login/send")
async def login_send(request: Request) -> dict[str, str]:
    data = await request.json()
    clean_email = str(data.get("email", "")).strip().lower()
    if not clean_email:
        raise ValueError("email required")
    magic_code = f"{random.randint(0, 999999):06d}"
    MAGIC_CODES[clean_email] = magic_code
    print(f"[MVP login] magic code for {clean_email}: {magic_code}")
    return {"message": "Magic code generated. Check server logs."}


@app.post("/login/verify")
async def login_verify(request: Request) -> RedirectResponse:
    data = await request.json()
    clean_email = str(data.get("email", "")).strip().lower()
    code = str(data.get("code", "")).strip()
    if MAGIC_CODES.get(clean_email) != code:
        return RedirectResponse(url="/login?error=invalid_code", status_code=303)

    with SessionLocal() as db:
        customer = db.query(Customer).filter(Customer.email == clean_email).first()
        if customer is None:
            company = db.query(Company).filter(Company.is_active.is_(True)).order_by(Company.id.asc()).first()
            if company is None:
                return RedirectResponse(url="/login?error=no_company", status_code=303)
            customer = Customer(email=clean_email, name=clean_email.split("@")[0], company_id=company.id, postal_code=None, is_active=True)
            db.add(customer)
            db.commit()
            db.refresh(customer)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(CUSTOMER_COOKIE, create_token({"customer_id": customer.id, "customer_email": customer.email}), httponly=True, samesite="lax")
    MAGIC_CODES.pop(clean_email, None)
    return response


@app.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(CUSTOMER_COOKIE)
    return response


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "profile.html", {"request": request, "email": _current_customer(request).get("customer_email")})


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin_login.html", {"request": request, "message": request.query_params.get("error")})


@app.post("/admin/login")
async def admin_login(request: Request) -> RedirectResponse:
    data = await request.json()
    if data.get("password") != settings.admin_password:
        return RedirectResponse(url="/admin/login?error=1", status_code=303)
    response = RedirectResponse(url="/admin/settings", status_code=303)
    response.set_cookie(ADMIN_COOKIE, create_token({"is_admin": True}), httponly=True, samesite="lax")
    return response


def _is_admin(request: Request) -> bool:
    return bool(read_token(request.cookies.get(ADMIN_COOKIE)).get("is_admin"))


@app.get("/admin/logout")
def admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


def _admin_page(request: Request, template_name: str) -> HTMLResponse:
    if not _is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(request, template_name, {"request": request})


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request) -> HTMLResponse:
    return _admin_page(request, "admin_settings.html")


@app.get("/admin/menu", response_class=HTMLResponse)
def admin_menu_page(request: Request) -> HTMLResponse:
    return _admin_page(request, "admin_menu.html")


@app.get("/admin/specials", response_class=HTMLResponse)
def admin_specials_page(request: Request) -> HTMLResponse:
    return _admin_page(request, "admin_specials.html")


@app.get("/admin/orders/today", response_class=HTMLResponse)
def admin_orders_page(request: Request) -> HTMLResponse:
    return _admin_page(request, "admin_orders_today.html")


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
    return {"handler": _order_handler_ref(), "template_path": ORDER_TEMPLATE_PATH, "static_css_href": f"/static/order.css?v={ORDER_UI_BUILD_ID}", "static_js_href": f"/static/order.js?v={ORDER_UI_BUILD_ID}", "git_sha": ORDER_UI_BUILD_ID}


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"app": settings.app_name, "message": "MVP 1.0 single restaurant catering API", "docs": "/docs", "api_v1": "/api/v1"}
