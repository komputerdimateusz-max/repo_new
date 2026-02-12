"""FastAPI application entrypoint."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from app.db.base import Base
from app.db import session as db_session
from app.db.seed import ensure_admin_user
from app.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, get_language, t
from app.models import MenuItem, Order, OrderItem, User
from app.services.menu_service import create_menu_item, list_menu_items_for_date, toggle_menu_item_active
from app.services.user_service import create_user, get_user_by_email, get_user_by_id

app: FastAPI = FastAPI(title=settings.app_name)

base_dir: Path = Path(__file__).resolve().parent.parent
templates: Jinja2Templates = Jinja2Templates(directory=str(base_dir / "frontend" / "templates"))
templates.env.globals["t"] = t
app.mount("/static", StaticFiles(directory=str(base_dir / "frontend" / "static")), name="static")

ALLOWED_ROLES: set[str] = {"employee", "company", "catering", "admin"}


MENU_MANAGER_ROLES: set[str] = {"catering", "admin"}


def _forbidden_catering_access(request: Request) -> RedirectResponse:
    """Redirect non-catering users back to dashboard with localized error."""
    message: str = t("menu.error.forbidden", get_language(request)).replace(" ", "+")
    return RedirectResponse(url=f"/app?message={message}", status_code=status.HTTP_303_SEE_OTHER)


def _require_menu_manager_user(request: Request, db: Session) -> User | RedirectResponse:
    """Return authenticated catering/admin user or redirect response."""
    user: User | None = _current_user_from_cookie(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role not in MENU_MANAGER_ROLES:
        return _forbidden_catering_access(request)
    return user


def _parse_menu_price_to_cents(price_raw: str) -> int:
    """Convert PLN decimal string to integer cents."""
    normalized_price: str = price_raw.strip().replace(",", ".")
    decimal_value = Decimal(normalized_price)
    if decimal_value <= 0:
        raise ValueError("Price must be greater than zero")
    cents: Decimal = (decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


@app.on_event("startup")
def initialize_database_on_startup() -> None:
    """Initialize database schema and development seed data."""
    Base.metadata.create_all(bind=db_session.engine)

    db = db_session.SessionLocal()
    try:
        ensure_admin_user(db)
    finally:
        db.close()


def _template_context(request: Request, **extra: object) -> dict[str, object]:
    lang: str = get_language(request)
    context: dict[str, object] = {"request": request, "lang": lang}
    context.update(extra)
    return context


def _current_user_from_cookie(request: Request, db: Session) -> User | None:
    token: str | None = request.cookies.get("access_token")
    if token is None:
        return None

    try:
        payload = verify_token(token)
        user_id_raw: str | int | None = payload.get("sub")
        user_id: int = int(user_id_raw) if user_id_raw is not None else -1
        return get_user_by_id(db=db, user_id=user_id)
    except (HTTPException, TypeError, ValueError):
        return None


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the public landing page."""
    return templates.TemplateResponse("index.html", _template_context(request))


@app.get("/lang/{lang}", include_in_schema=False)
def set_language(lang: str, request: Request) -> RedirectResponse:
    """Persist language in cookie and redirect to referrer."""
    selected_lang: str = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    redirect_target: str = request.headers.get("referer") or "/"
    response = RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="lang", value=selected_lang, samesite="lax")
    return response


@app.get("/login", include_in_schema=False, response_class=HTMLResponse)
def login_page(request: Request, message: str | None = None) -> HTMLResponse:
    """Render login page and optional success message."""
    return templates.TemplateResponse(
        "login.html",
        _template_context(request, message=message, error=None),
    )


@app.post("/login", include_in_schema=False, response_class=HTMLResponse)
async def login_submit(request: Request) -> HTMLResponse:
    """Handle login submission and persist access token cookie on success."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    email: str = form_data.get("email", [""])[0]
    password: str = form_data.get("password", [""])[0]

    db: Session = db_session.SessionLocal()
    try:
        user: User | None = get_user_by_email(db=db, email=email)
        if user is None or not verify_password(password, user.hashed_password):
            return templates.TemplateResponse(
                "login.html",
                _template_context(request, error=t("error.invalid_credentials", get_language(request)), message=None),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        token: str = create_access_token(data={"sub": str(user.id)})
        response: RedirectResponse = RedirectResponse(
            url="/app",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            samesite="lax",
        )
        return response
    finally:
        db.close()


@app.get("/register", include_in_schema=False, response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    """Render account registration page."""
    return templates.TemplateResponse(
        "register.html",
        _template_context(request, error=None),
    )


@app.post("/register", include_in_schema=False, response_class=HTMLResponse)
async def register_submit(request: Request) -> HTMLResponse:
    """Handle registration form submission."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    email: str = form_data.get("email", [""])[0]
    password: str = form_data.get("password", [""])[0]
    role: str = form_data.get("role", [""])[0]

    if role not in ALLOWED_ROLES:
        return templates.TemplateResponse(
            "register.html",
            _template_context(request, error=t("error.invalid_role", get_language(request))),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    db: Session = db_session.SessionLocal()
    try:
        existing_user: User | None = get_user_by_email(db=db, email=email)
        if existing_user is not None:
            return templates.TemplateResponse(
                "register.html",
                _template_context(request, error=t("error.email_registered", get_language(request))),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        create_user(
            db=db,
            email=email,
            hashed_password=get_password_hash(password),
            role=role,
        )
        success_message: str = t("register.success", get_language(request)).replace(" ", "+")
        return RedirectResponse(
            url=f"/login?message={success_message}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    finally:
        db.close()


@app.get("/app", include_in_schema=False, response_class=HTMLResponse)
def app_shell(request: Request, message: str | None = None) -> HTMLResponse:
    """Render dashboard for authenticated users only."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        today: date = date.today()
        menu_items: list[MenuItem] = (
            db.query(MenuItem)
            .filter(MenuItem.menu_date == today, MenuItem.is_active.is_(True))
            .order_by(MenuItem.id.asc())
            .all()
        )

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == today)
            .first()
        )
        order_items: list[dict[str, object]] = []
        total_cents: int = 0

        if order is not None:
            menu_by_id: dict[int, MenuItem] = {item.id: item for item in menu_items}
            missing_ids: list[int] = [
                item.menu_item_id for item in order.items if item.menu_item_id not in menu_by_id
            ]
            if missing_ids:
                for menu_item in db.query(MenuItem).filter(MenuItem.id.in_(missing_ids)).all():
                    menu_by_id[menu_item.id] = menu_item

            for item in order.items:
                menu_item = menu_by_id.get(item.menu_item_id)
                if menu_item is None:
                    continue
                line_total: int = menu_item.price_cents * item.quantity
                total_cents += line_total
                order_items.append(
                    {
                        "name": menu_item.name,
                        "quantity": item.quantity,
                        "price_cents": menu_item.price_cents,
                        "line_total_cents": line_total,
                    }
                )

        return templates.TemplateResponse(
            "app.html",
            _template_context(
                request,
                menu_items=menu_items,
                order_items=order_items,
                total_cents=total_cents,
                message=message,
                current_user=user,
            ),
        )
    finally:
        db.close()


@app.post("/app/order", include_in_schema=False)
async def submit_order(request: Request) -> RedirectResponse:
    """Submit order form from dashboard UI."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        form_data = parse_qs((await request.body()).decode("utf-8"))
        today: date = date.today()

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == today)
            .first()
        )
        if order is None:
            order = Order(user_id=user.id, order_date=today, status="created")
            db.add(order)
            db.flush()

        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

        for key, values in form_data.items():
            if not key.startswith("qty_"):
                continue
            menu_item_id: int = int(key.replace("qty_", ""))
            quantity_raw: str = values[0]
            if not quantity_raw:
                continue
            quantity: int = int(quantity_raw)
            if quantity < 1:
                continue
            db.add(OrderItem(order_id=order.id, menu_item_id=menu_item_id, quantity=quantity))

        db.commit()
    finally:
        db.close()

    message = t("order.updated", get_language(request)).replace(" ", "+")
    return RedirectResponse(url=f"/app?message={message}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/catering/menu", include_in_schema=False, response_class=HTMLResponse)
def catering_menu_page(request: Request, message: str | None = None) -> HTMLResponse:
    """Render catering/admin menu management page."""
    selected_date_str: str = request.query_params.get("date", date.today().isoformat())
    try:
        selected_date: date = date.fromisoformat(selected_date_str)
    except ValueError:
        selected_date = date.today()
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        menu_items: list[MenuItem] = list_menu_items_for_date(db=db, menu_date=selected_date)
        return templates.TemplateResponse(
            "catering_menu.html",
            _template_context(
                request,
                selected_date=selected_date,
                menu_items=menu_items,
                message=message,
                error=None,
                current_user=user_or_response,
            ),
        )
    finally:
        db.close()


@app.post("/catering/menu", include_in_schema=False)
async def catering_menu_create(request: Request) -> Response:
    """Create menu item from catering/admin HTML form."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    selected_date_str: str = form_data.get("menu_date", [date.today().isoformat()])[0]

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        try:
            selected_date = date.fromisoformat(selected_date_str)
        except ValueError:
            selected_date = date.today()
            selected_date_str = selected_date.isoformat()
        name: str = form_data.get("name", [""])[0].strip()
        description_raw: str = form_data.get("description", [""])[0].strip()
        price_raw: str = form_data.get("price", [""])[0]
        is_active: bool = form_data.get("is_active", [""])[0] == "on"

        if not name:
            error_message = t("menu.error.name_required", get_language(request))
            menu_items = list_menu_items_for_date(db=db, menu_date=selected_date)
            return templates.TemplateResponse(
                "catering_menu.html",
                _template_context(
                    request,
                    selected_date=selected_date,
                    menu_items=menu_items,
                    message=None,
                    error=error_message,
                    current_user=user_or_response,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            price_cents: int = _parse_menu_price_to_cents(price_raw)
        except (InvalidOperation, ValueError):
            error_message = t("menu.error.invalid_price", get_language(request))
            menu_items = list_menu_items_for_date(db=db, menu_date=selected_date)
            return templates.TemplateResponse(
                "catering_menu.html",
                _template_context(
                    request,
                    selected_date=selected_date,
                    menu_items=menu_items,
                    message=None,
                    error=error_message,
                    current_user=user_or_response,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        create_menu_item(
            db=db,
            menu_date=selected_date,
            name=name,
            description=description_raw or None,
            price_cents=price_cents,
            is_active=is_active,
        )
    finally:
        db.close()

    success_message: str = t("menu.success.created", get_language(request)).replace(" ", "+")
    return RedirectResponse(
        url=f"/catering/menu?date={selected_date_str}&message={success_message}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/catering/menu/{menu_item_id}/toggle", include_in_schema=False)
def catering_menu_toggle(request: Request, menu_item_id: int) -> RedirectResponse:
    """Toggle active state for selected menu item."""
    selected_date_str: str = request.query_params.get("date", date.today().isoformat())
    try:
        selected_date: date = date.fromisoformat(selected_date_str)
    except ValueError:
        selected_date = date.today()
    selected_date_str: str = selected_date.isoformat()
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        menu_item: MenuItem | None = db.query(MenuItem).filter(MenuItem.id == menu_item_id).first()
        if menu_item is not None:
            toggle_menu_item_active(db=db, menu_item=menu_item)
    finally:
        db.close()

    return RedirectResponse(
        url=f"/catering/menu?date={selected_date_str}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
