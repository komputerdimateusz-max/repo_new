"""FastAPI application entrypoint."""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
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
from app.models import Location, MenuItem, Order, OrderItem, User
from app.services.menu_service import create_menu_item, list_menu_items_for_date, toggle_menu_item_active
from app.services.user_service import (
    count_admin_users,
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user_role,
)

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


def _forbidden_settings_access(request: Request) -> RedirectResponse:
    """Redirect non-admin users to dashboard with localized error."""
    message: str = t("settings.error.forbidden", get_language(request)).replace(" ", "+")
    return RedirectResponse(url=f"/app?message={message}", status_code=status.HTTP_303_SEE_OTHER)


def _require_admin_user(request: Request, db: Session) -> User | RedirectResponse:
    """Return authenticated admin user or redirect response."""
    user: User | None = _current_user_from_cookie(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role != "admin":
        return _forbidden_settings_access(request)
    return user


def _build_order_summary_rows(db: Session, orders: list[Order]) -> list[dict[str, object]]:
    """Build compact order summary rows with user email and PLN totals."""
    rows: list[dict[str, object]] = []
    if not orders:
        return rows

    user_ids: set[int] = {order.user_id for order in orders}
    users_by_id: dict[int, User] = {
        user.id: user for user in db.query(User).filter(User.id.in_(user_ids)).all()
    }
    menu_item_ids: set[int] = {
        item.menu_item_id
        for order in orders
        for item in order.items
    }
    menu_by_id: dict[int, MenuItem] = {
        item.id: item for item in db.query(MenuItem).filter(MenuItem.id.in_(menu_item_ids)).all()
    }

    for order in orders:
        total_items: int = 0
        total_cents: int = 0
        for item in order.items:
            menu_item = menu_by_id.get(item.menu_item_id)
            if menu_item is None:
                continue
            total_items += item.quantity
            total_cents += menu_item.price_cents * item.quantity

        user: User | None = users_by_id.get(order.user_id)
        rows.append(
            {
                "order_id": order.id,
                "user_email": user.email if user is not None else "-",
                "total_items": total_items,
                "total_cents": total_cents,
            }
        )

    return rows


def _parse_location_time(time_raw: str) -> time | None:
    """Parse HH:MM value from HTML input."""
    normalized: str = time_raw.strip()
    if not normalized:
        return None
    return datetime.strptime(normalized, "%H:%M").time()


def _build_location_group_summary(db: Session, orders: list[Order]) -> list[dict[str, object]]:
    """Aggregate order totals grouped by location."""
    if not orders:
        return []

    menu_item_ids: set[int] = {
        item.menu_item_id
        for order in orders
        for item in order.items
    }
    menu_by_id: dict[int, MenuItem] = {
        item.id: item for item in db.query(MenuItem).filter(MenuItem.id.in_(menu_item_ids)).all()
    }

    grouped: dict[int, dict[str, object]] = {}
    for order in orders:
        if order.location is None:
            continue
        bucket = grouped.get(order.location_id)
        if bucket is None:
            bucket = {
                "company_name": order.location.company_name,
                "address": order.location.address,
                "orders_count": 0,
                "total_items": 0,
                "total_cents": 0,
            }
            grouped[order.location_id] = bucket

        bucket["orders_count"] += 1
        for item in order.items:
            menu_item = menu_by_id.get(item.menu_item_id)
            if menu_item is None:
                continue
            bucket["total_items"] += item.quantity
            bucket["total_cents"] += menu_item.price_cents * item.quantity

    return list(grouped.values())


def _parse_menu_price_to_cents(price_raw: str) -> int:
    """Convert PLN decimal string to integer cents."""
    normalized_price: str = price_raw.strip().replace(",", ".")
    decimal_value = Decimal(normalized_price)
    if decimal_value <= 0:
        raise ValueError("Price must be greater than zero")
    cents: Decimal = (decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _ensure_location_schema_compatibility() -> None:
    """Apply lightweight schema updates for legacy SQLite databases."""
    with db_session.engine.begin() as connection:
        inspector = inspect(connection)
        table_names: set[str] = set(inspector.get_table_names())

        if "locations" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE locations (
                        id INTEGER PRIMARY KEY,
                        company_name VARCHAR(255) NOT NULL,
                        address VARCHAR(255) NOT NULL,
                        delivery_time_start TIME NULL,
                        delivery_time_end TIME NULL,
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )

        location_columns: set[str] = {column["name"] for column in inspector.get_columns("locations")}
        if "created_at" not in location_columns:
            now_iso: str = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
            connection.execute(
                text(
                    "ALTER TABLE locations ADD COLUMN created_at DATETIME NOT NULL "
                    f"DEFAULT '{now_iso}'"
                )
            )

        orders_columns: set[str] = {column["name"] for column in inspector.get_columns("orders")}
        if "location_id" not in orders_columns:
            default_location = connection.execute(
                text("SELECT id FROM locations ORDER BY id ASC LIMIT 1")
            ).scalar_one_or_none()
            if default_location is None:
                now_iso = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
                connection.execute(
                    text(
                        """
                        INSERT INTO locations (company_name, address, is_active, created_at)
                        VALUES (:company_name, :address, :is_active, :created_at)
                        """
                    ),
                    {
                        "company_name": "Legacy Location",
                        "address": "Unknown Address",
                        "is_active": True,
                        "created_at": now_iso,
                    },
                )
                default_location = connection.execute(
                    text("SELECT id FROM locations ORDER BY id ASC LIMIT 1")
                ).scalar_one()

            connection.execute(
                text(
                    "ALTER TABLE orders ADD COLUMN location_id INTEGER "
                    f"NOT NULL DEFAULT {int(default_location)}"
                )
            )


@app.on_event("startup")
def initialize_database_on_startup() -> None:
    """Initialize database schema and development seed data."""
    Base.metadata.create_all(bind=db_session.engine)
    _ensure_location_schema_compatibility()

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
                today=today,
                current_user=user,
            ),
        )
    finally:
        db.close()


@app.get("/menu", include_in_schema=False, response_class=HTMLResponse)
def menu_page(request: Request) -> HTMLResponse:
    """Render today's menu and order form for authenticated users."""
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

        return templates.TemplateResponse(
            "menu.html",
            _template_context(request, menu_items=menu_items, current_user=user),
        )
    finally:
        db.close()


@app.get("/orders", include_in_schema=False, response_class=HTMLResponse)
def orders_page(request: Request, message: str | None = None) -> HTMLResponse:
    """Render current user's orders for selected date (today by default)."""
    selected_date_str: str = request.query_params.get("date", date.today().isoformat())
    try:
        selected_date: date = date.fromisoformat(selected_date_str)
    except ValueError:
        selected_date = date.today()

    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == selected_date)
            .first()
        )
        order_items: list[dict[str, object]] = []
        total_cents: int = 0

        if order is not None:
            menu_item_ids = [item.menu_item_id for item in order.items]
            menu_by_id: dict[int, MenuItem] = {}
            if menu_item_ids:
                for menu_item in db.query(MenuItem).filter(MenuItem.id.in_(menu_item_ids)).all():
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
                        "line_total_cents": line_total,
                    }
                )

        return templates.TemplateResponse(
            "orders.html",
            _template_context(
                request,
                order_items=order_items,
                total_cents=total_cents,
                selected_date=selected_date,
                message=message,
                current_user=user,
            ),
        )
    finally:
        db.close()


@app.get("/order", include_in_schema=False, response_class=HTMLResponse)
def order_page(request: Request, error: str | None = None) -> HTMLResponse:
    """Render focused order submission page for today's active menu."""
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
        locations: list[Location] = (
            db.query(Location)
            .filter(Location.is_active.is_(True))
            .order_by(Location.company_name.asc(), Location.address.asc())
            .all()
        )
        return templates.TemplateResponse(
            "order.html",
            _template_context(
                request,
                menu_items=menu_items,
                locations=locations,
                error=error,
                current_user=user,
            ),
        )
    finally:
        db.close()


@app.get("/billing", include_in_schema=False, response_class=HTMLResponse)
def billing_page(request: Request) -> HTMLResponse:
    """Render placeholder billing page for authenticated users."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        return templates.TemplateResponse(
            "billing.html",
            _template_context(request, current_user=user),
        )
    finally:
        db.close()


@app.get("/settings", include_in_schema=False, response_class=HTMLResponse)
def settings_page(request: Request, message: str | None = None) -> Response:
    """Render user role management page for admin users."""
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        users: list[User] = list_users(db=db)
        return templates.TemplateResponse(
            "settings.html",
            _template_context(
                request,
                current_user=user_or_response,
                users=users,
                message=message,
            ),
        )
    finally:
        db.close()


@app.post("/settings/users/{user_id}/role", include_in_schema=False)
async def settings_update_user_role(request: Request, user_id: int) -> Response:
    """Update selected user role from admin settings form."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    role: str = form_data.get("role", [""])[0]

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        if role not in ALLOWED_ROLES:
            message = t("settings.error.invalid_role", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/settings?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        user: User | None = get_user_by_id(db=db, user_id=user_id)
        if user is None:
            message = t("settings.error.user_not_found", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/settings?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        update_user_role(db=db, user=user, role=role)
    finally:
        db.close()

    message = t("settings.success.role_updated", get_language(request)).replace(" ", "+")
    return RedirectResponse(url=f"/settings?message={message}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/locations", include_in_schema=False, response_class=HTMLResponse)
def admin_locations_page(request: Request, message: str | None = None) -> Response:
    """Render locations management page for admin users."""
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        locations: list[Location] = db.query(Location).order_by(Location.id.asc()).all()
        return templates.TemplateResponse(
            "admin_locations.html",
            _template_context(
                request,
                current_user=user_or_response,
                message=message,
                locations=locations,
            ),
        )
    finally:
        db.close()


@app.post("/admin/locations", include_in_schema=False)
async def admin_locations_create(request: Request) -> Response:
    """Create location from admin form submission."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    company_name: str = form_data.get("company_name", [""])[0].strip()
    address: str = form_data.get("address", [""])[0].strip()
    delivery_time_start_raw: str = form_data.get("delivery_time_start", [""])[0]
    delivery_time_end_raw: str = form_data.get("delivery_time_end", [""])[0]
    is_active: bool = form_data.get("is_active", [""])[0] == "on"

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        if not company_name or not address:
            message = t("locations.error.required_fields", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/admin/locations?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        try:
            delivery_time_start = _parse_location_time(delivery_time_start_raw)
            delivery_time_end = _parse_location_time(delivery_time_end_raw)
        except ValueError:
            message = t("locations.error.invalid_time", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/admin/locations?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        location = Location(
            company_name=company_name,
            address=address,
            delivery_time_start=delivery_time_start,
            delivery_time_end=delivery_time_end,
            is_active=is_active,
        )
        db.add(location)
        db.commit()
    finally:
        db.close()

    message = t("locations.success.created", get_language(request)).replace(" ", "+")
    return RedirectResponse(url=f"/admin/locations?message={message}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/locations/{location_id}/toggle", include_in_schema=False)
def admin_locations_toggle(request: Request, location_id: int) -> RedirectResponse:
    """Toggle active state of selected location."""
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        location: Location | None = db.query(Location).filter(Location.id == location_id).first()
        if location is not None:
            location.is_active = not location.is_active
            db.add(location)
            db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/locations", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/dev/promote-admin", include_in_schema=False)
async def dev_promote_admin(request: Request) -> Response:
    """Promote a user to admin in development environment only."""
    if settings.app_env != "dev":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    form_data = parse_qs((await request.body()).decode("utf-8"))
    email: str = form_data.get("email", [""])[0].strip()

    db: Session = db_session.SessionLocal()
    try:
        if count_admin_users(db=db) > 0:
            message = t("settings.dev.admin_exists", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/login?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        user: User | None = get_user_by_email(db=db, email=email)
        if user is None:
            message = t("settings.error.user_not_found", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/login?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        update_user_role(db=db, user=user, role="admin")
    finally:
        db.close()

    message = t("settings.dev.promoted", get_language(request)).replace(" ", "+")
    return RedirectResponse(url=f"/login?message={message}", status_code=status.HTTP_303_SEE_OTHER)


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
        location_id_raw: str = form_data.get("location_id", [""])[0].strip()
        if not location_id_raw:
            message = t("order.error.location_required", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}", status_code=status.HTTP_303_SEE_OTHER)

        try:
            location_id: int = int(location_id_raw)
        except ValueError:
            message = t("order.error.location_required", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}", status_code=status.HTTP_303_SEE_OTHER)

        location: Location | None = (
            db.query(Location)
            .filter(Location.id == location_id, Location.is_active.is_(True))
            .first()
        )
        if location is None:
            message = t("order.error.location_required", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}", status_code=status.HTTP_303_SEE_OTHER)

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == today)
            .first()
        )
        if order is None:
            order = Order(user_id=user.id, location_id=location.id, order_date=today, status="created")
            db.add(order)
            db.flush()
        else:
            order.location_id = location.id

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
    return RedirectResponse(url=f"/orders?message={message}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/catering/menu", include_in_schema=False, response_class=HTMLResponse)
def catering_menu_page(request: Request, message: str | None = None) -> HTMLResponse:
    """Render catering/admin menu management page."""
    selected_date: date = date.today()
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
    selected_date: date = date.today()

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

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
        url=f"/catering/menu?message={success_message}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/catering/menu/{menu_item_id}/toggle", include_in_schema=False)
def catering_menu_toggle(request: Request, menu_item_id: int) -> RedirectResponse:
    """Toggle active state for selected menu item."""
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
        url="/catering/menu",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/catering/orders", include_in_schema=False, response_class=HTMLResponse)
def catering_orders_page(request: Request) -> Response:
    """Render daily order list for catering/admin users."""
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

        orders: list[Order] = (
            db.query(Order)
            .filter(Order.order_date == selected_date)
            .order_by(Order.id.asc())
            .all()
        )
        order_rows: list[dict[str, object]] = _build_order_summary_rows(db=db, orders=orders)
        location_summaries: list[dict[str, object]] = _build_location_group_summary(db=db, orders=orders)
        return templates.TemplateResponse(
            "catering_orders.html",
            _template_context(
                request,
                selected_date=selected_date,
                order_rows=order_rows,
                location_summaries=location_summaries,
                current_user=user_or_response,
            ),
        )
    finally:
        db.close()


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
