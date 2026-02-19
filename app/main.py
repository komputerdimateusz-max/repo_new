"""FastAPI entrypoint for single-restaurant catering MVP."""

from __future__ import annotations

import logging
import os
import subprocess
from decimal import Decimal
from urllib.parse import parse_qs
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.api import api_router
from app.auth import get_current_user, role_landing
from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.migrations import ensure_sqlite_schema
from app.db.seed import ensure_seed_data
from app.db.session import SessionLocal, engine
from app.models import MenuItem, RestaurantSetting, User
from app.models.user import normalize_user_role
from app.services.account_service import authenticate_user, ensure_customer_profile, ensure_default_admin

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

app = FastAPI(title="Single Restaurant Catering MVP")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 7,
)
app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
MENU_CATEGORIES = ["Dania dnia", "Zupy", "Drugie", "Fit", "Napoje", "Dodatki"]


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


@app.on_event("startup")
def startup() -> None:
    secret_from_env = bool(os.getenv("SESSION_SECRET"))
    source = "env" if secret_from_env else "fallback"
    logger.info("Session secret source: %s", source)
    if not secret_from_env:
        logger.warning("SESSION_SECRET not set; using development fallback secret.")
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema(engine)
    with SessionLocal() as session:
        try:
            ensure_seed_data(session)
            admin_present = ensure_default_admin(session)
            logger.info("[BOOTSTRAP] default admin present: %s", "yes" if admin_present else "no")
        except Exception:
            logger.exception("[BOOTSTRAP] Seed/bootstrap failed; continuing startup.")


def _session_user(request: Request) -> dict[str, str | int] | None:
    return get_current_user(request)


def _role_landing(role: str | None) -> str:
    return role_landing(role)


def _require_login(request: Request) -> dict[str, str | int] | RedirectResponse:
    current = _session_user(request)
    if current:
        return current
    return RedirectResponse(url="/login", status_code=303)


def _require_role_page(request: Request, allowed: set[str]) -> dict[str, str | int] | RedirectResponse:
    current = _require_login(request)
    if isinstance(current, RedirectResponse):
        return current
    if str(current["role"]) not in allowed:
        return RedirectResponse(url=role_landing(str(current["role"])), status_code=303)
    return current


async def _form_data(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    current = _require_role_page(request, {"CUSTOMER"})
    if isinstance(current, RedirectResponse):
        return current
    context = {
        "request": request,
        "order_ui_build": ORDER_UI_BUILD_ID,
        "user_email": current["username"],
        "debug_ui": settings.debug_ui,
    }
    return templates.TemplateResponse(request, "order.html", context)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    current = _session_user(request)
    if current:
        return RedirectResponse(url=role_landing(str(current["role"])), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": error})


@app.post("/login", response_class=RedirectResponse)
async def login_submit(request: Request):
    form = await _form_data(request)
    username = form.get("username", "")
    password = form.get("password", "")
    with SessionLocal() as db:
        user = authenticate_user(db, username=username, password=password)
        if user is None:
            return login_page(request, error="Invalid username or password")

        request.session.clear()
        request.session["user_id"] = user.id
        request.session["role"] = user.role
        request.session["username"] = user.username

        user_role = user.role
        if user_role == "CUSTOMER":
            try:
                customer = ensure_customer_profile(db, user)
            except Exception:
                logger.exception("[AUTH] Failed to ensure customer profile during login for user_id=%s", user.id)
                request.session.clear()
                return login_page(request, error="Could not finish login. Please try again.")
            if customer is None:
                request.session.clear()
                return login_page(request, error="Could not finish login. Please try again.")
            request.session["customer_id"] = customer.id
            request.session["customer_email"] = customer.email

    return RedirectResponse(url=role_landing(user_role), status_code=303)


@app.post("/logout", response_class=RedirectResponse)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/logout", response_class=RedirectResponse)
def logout_get(request: Request):
    return logout(request)


@app.get("/__debug/auth", include_in_schema=False)
def debug_auth(request: Request):
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")
    session_keys = sorted(list(request.session.keys()))
    return {
        "path": str(request.url.path),
        "session_present": len(session_keys) > 0,
        "session_keys": session_keys,
        "user_id": request.session.get("user_id"),
        "role": request.session.get("role"),
        "cookie_seen": "session" in request.cookies,
    }


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    current = _require_role_page(request, {"CUSTOMER"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "profile.html", {"request": request, "email": request.session.get("customer_email", current["username"])})


@app.get("/my-order", response_class=HTMLResponse)
def my_order_page(request: Request):
    current = _require_role_page(request, {"CUSTOMER"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "my_order.html", {"request": request, "user_email": current["username"]})


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "admin_home.html", {"request": request, "username": current["username"]})


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.id.asc())).all()
    return templates.TemplateResponse(request, "admin_users.html", {"request": request, "users": users})


@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_users_new(request: Request):
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "admin_users_new.html", {"request": request})


@app.post("/admin/users", response_class=RedirectResponse)
@app.post("/admin/users/new", response_class=RedirectResponse)
async def admin_users_create(request: Request):
    form = await _form_data(request)
    username = form.get("username", "")
    password = form.get("password", "")
    role = form.get("role", "")
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    try:
        clean_role = normalize_user_role(role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if clean_role not in {"RESTAURANT", "CUSTOMER"}:
        raise HTTPException(status_code=400, detail="Invalid role for admin creation")
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username.strip()).limit(1))
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        user = User(username=username.strip(), password_hash=get_password_hash(password), role=clean_role, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        if clean_role == "CUSTOMER":
            ensure_customer_profile(db, user)
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/password", response_class=RedirectResponse)
@app.post("/admin/users/{user_id}/reset-password", response_class=RedirectResponse)
async def admin_user_password(request: Request, user_id: int):
    form = await _form_data(request)
    password = form.get("password", "")
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        user.password_hash = get_password_hash(password)
        db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/restaurant", response_class=HTMLResponse)
def restaurant_home(request: Request):
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "restaurant_home.html", {"request": request, "username": current["username"]})


@app.get("/restaurant/menu", response_class=HTMLResponse)
def restaurant_menu(request: Request):
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        items = db.scalars(select(MenuItem).order_by(MenuItem.id.desc())).all()
    return templates.TemplateResponse(request, "restaurant_menu.html", {"request": request, "items": items})


@app.get("/restaurant/menu/new", response_class=HTMLResponse)
def restaurant_menu_new(request: Request):
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "restaurant_menu_form.html", {"request": request, "item": None, "categories": MENU_CATEGORIES})


@app.get("/restaurant/menu/{item_id}/edit", response_class=HTMLResponse)
def restaurant_menu_edit(request: Request, item_id: int):
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        item = db.get(MenuItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Menu item not found")
    return templates.TemplateResponse(request, "restaurant_menu_form.html", {"request": request, "item": item, "categories": MENU_CATEGORIES})


@app.post("/restaurant/menu", response_class=RedirectResponse)
@app.post("/restaurant/menu/new", response_class=RedirectResponse)
async def restaurant_menu_create(request: Request):
    form = await _form_data(request)
    name = form.get("name", "")
    description = form.get("description", "")
    price = Decimal(form.get("price", "0"))
    category = form.get("category", "")
    is_standard = form.get("is_standard") == "true"
    is_active = form.get("is_active") == "true"
    image_url = form.get("image_url", "")
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        db.add(MenuItem(name=name, description=description or None, price=price, category=category, is_standard=is_standard, is_active=is_active, image_url=image_url or None))
        db.commit()
    return RedirectResponse(url="/restaurant/menu", status_code=303)


@app.post("/restaurant/menu/{item_id}", response_class=RedirectResponse)
async def restaurant_menu_update(request: Request, item_id: int):
    form = await _form_data(request)
    name = form.get("name", "")
    description = form.get("description", "")
    price = Decimal(form.get("price", "0"))
    category = form.get("category", "")
    is_standard = form.get("is_standard") == "true"
    is_active = form.get("is_active") == "true"
    image_url = form.get("image_url", "")
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        item = db.get(MenuItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Menu item not found")
        item.name = name
        item.description = description or None
        item.price = price
        item.category = category
        item.is_standard = is_standard
        item.is_active = is_active
        item.image_url = image_url or None
        db.commit()
    return RedirectResponse(url="/restaurant/menu", status_code=303)


@app.post("/restaurant/menu/{item_id}/toggle-active", response_class=RedirectResponse)
def restaurant_menu_toggle_active(request: Request, item_id: int):
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        item = db.get(MenuItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Menu item not found")
        item.is_active = not item.is_active
        db.commit()
    return RedirectResponse(url="/restaurant/menu", status_code=303)


@app.get("/restaurant/settings", response_class=HTMLResponse)
def restaurant_settings_page(request: Request):
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        app_settings = db.get(RestaurantSetting, 1)
    return templates.TemplateResponse(request, "restaurant_settings.html", {"request": request, "settings": app_settings})


@app.post("/restaurant/settings", response_class=RedirectResponse)
async def restaurant_settings_save(request: Request):
    form = await _form_data(request)
    cut_off_time = form.get("cut_off_time", "")
    delivery_fee = Decimal(form.get("delivery_fee", "0"))
    delivery_window_start = form.get("delivery_window_start", "")
    delivery_window_end = form.get("delivery_window_end", "")
    current = _require_role_page(request, {"RESTAURANT", "ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    with SessionLocal() as db:
        app_settings = db.get(RestaurantSetting, 1)
        if app_settings is None:
            raise HTTPException(status_code=500, detail="Settings row is missing")
        app_settings.cut_off_time = cut_off_time
        app_settings.delivery_fee = delivery_fee
        app_settings.delivery_window_start = delivery_window_start
        app_settings.delivery_window_end = delivery_window_end
        db.commit()
    return RedirectResponse(url="/restaurant/settings", status_code=303)




@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request):
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "admin_settings.html", {"request": request})


@app.get("/admin/menu", response_class=HTMLResponse)
def admin_menu_page(request: Request):
    current = _require_role_page(request, {"ADMIN"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "admin_menu.html", {"request": request})


@app.get("/admin/specials", response_class=HTMLResponse)
def admin_specials_page(request: Request):
    current = _require_role_page(request, {"ADMIN", "RESTAURANT"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "admin_specials.html", {"request": request})


@app.get("/admin/orders/today", response_class=HTMLResponse)
def admin_orders_page(request: Request):
    current = _require_role_page(request, {"ADMIN", "RESTAURANT"})
    if isinstance(current, RedirectResponse):
        return current
    return templates.TemplateResponse(request, "admin_orders_today.html", {"request": request})


@app.get("/admin/orders/today.csv", response_class=RedirectResponse)
def admin_orders_csv_redirect(request: Request):
    current = _require_role_page(request, {"ADMIN", "RESTAURANT"})
    if isinstance(current, RedirectResponse):
        return current
    return RedirectResponse(url="/api/v1/admin/orders/today.csv", status_code=307)
@app.get("/__debug/routes", include_in_schema=False, response_class=PlainTextResponse)
def debug_routes() -> PlainTextResponse:
    lines = []
    for route in app.routes:
        methods = ",".join(sorted(getattr(route, "methods", None) or []))
        endpoint = getattr(route, "endpoint", None)
        lines.append(f"{route.path} [{methods}] -> {getattr(endpoint, '__name__', '<no-endpoint>')}")
    return PlainTextResponse("\n".join(sorted(lines)))
