"""FastAPI application entrypoint."""

from datetime import date, datetime, time, timedelta
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
from app.db.migrations import ensure_sqlite_schema
from app.db.seed import ensure_admin_user
from app.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, get_language, t
from app.models import CatalogItem, DailyMenuItem, Location, Order, OrderItem, User
from app.services.menu_service import (
    activate_catalog_item_for_date,
    copy_menu,
    create_catalog_item,
    enable_standard_for_date,
    get_menu_for_date,
    list_catalog_items,
    list_menu_items_for_date,
    toggle_menu_item_active,
)
from app.services.order_service import CutoffPassedError, resolve_target_order_date
from app.services.settings_service import (
    get_order_window_times,
    is_within_order_window,
    parse_hhmm_time,
    save_order_window_times,
)
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


def _current_local_datetime() -> datetime:
    """Return current local datetime."""
    return datetime.now()




def _current_local_time() -> time:
    """Return current local time."""
    return _current_local_datetime().time().replace(second=0, microsecond=0)


def _get_order_window_times(db: Session) -> tuple[time, time]:
    """Return configured order opening window with config fallback."""
    return get_order_window_times(
        db,
        default_open_time=settings.app_order_open_time,
        default_close_time=settings.app_order_close_time,
    )


def _is_ordering_open_now(db: Session, now_time: time | None = None) -> tuple[bool, time, time]:
    """Check if ordering is open at the current local time."""
    open_time, close_time = _get_order_window_times(db)
    current_time: time = now_time or _current_local_time()
    return is_within_order_window(current_time, open_time, close_time), open_time, close_time


def _order_horizon_dates() -> list[date]:
    """Return selectable order dates: today + next 6 days."""
    today: date = date.today()
    return [today + timedelta(days=offset) for offset in range(7)]


def _parse_horizon_date(raw_value: str | None) -> date:
    """Parse date and clamp to ordering horizon to prevent abuse."""
    horizon: list[date] = _order_horizon_dates()
    default_date: date = horizon[0]
    if not raw_value:
        return default_date
    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError:
        return default_date
    if parsed < horizon[0] or parsed > horizon[-1]:
        return default_date
    return parsed


def _next_order_window_open_message(request: Request, open_time: time) -> str:
    """Build user-friendly next opening message."""
    open_time_display: str = open_time.strftime("%H:%M")
    return t("order.opening_hours.next_open", get_language(request)).format(time=open_time_display)

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
    catalog_item_ids: set[int] = {
        item.catalog_item_id
        for order in orders
        for item in order.items
        if item.catalog_item_id is not None
    }
    menu_by_id: dict[int, CatalogItem] = {
        item.id: item for item in db.query(CatalogItem).filter(CatalogItem.id.in_(catalog_item_ids)).all()
    }

    for order in orders:
        total_items: int = 0
        total_cents: int = 0
        for item in order.items:
            menu_item = menu_by_id.get(item.catalog_item_id)
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

    catalog_item_ids: set[int] = {
        item.catalog_item_id
        for order in orders
        for item in order.items
        if item.catalog_item_id is not None
    }
    menu_by_id: dict[int, CatalogItem] = {
        item.id: item for item in db.query(CatalogItem).filter(CatalogItem.id.in_(catalog_item_ids)).all()
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
            menu_item = menu_by_id.get(item.catalog_item_id)
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


def _list_catalog_items_for_date(db: Session, target_date: date) -> list[CatalogItem]:
    """Return catalog dishes that are enabled for the selected day."""
    daily_rows: list[DailyMenuItem] = get_menu_for_date(db=db, target_date=target_date)
    return [row.catalog_item for row in daily_rows]


@app.on_event("startup")
def initialize_database_on_startup() -> None:
    """Initialize database schema and development seed data."""
    Base.metadata.create_all(bind=db_session.engine)
    ensure_sqlite_schema(db_session.engine)

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
        menu_items: list[CatalogItem] = _list_catalog_items_for_date(db=db, target_date=today)

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == today)
            .first()
        )
        order_items: list[dict[str, object]] = []
        total_cents: int = 0

        if order is not None:
            menu_by_id: dict[int, CatalogItem] = {item.id: item for item in menu_items}
            missing_ids: list[int] = [
                item.catalog_item_id
                for item in order.items
                if item.catalog_item_id is not None and item.catalog_item_id not in menu_by_id
            ]
            if missing_ids:
                for menu_item in db.query(CatalogItem).filter(CatalogItem.id.in_(missing_ids)).all():
                    menu_by_id[menu_item.id] = menu_item

            for item in order.items:
                menu_item = menu_by_id.get(item.catalog_item_id)
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
        menu_items: list[CatalogItem] = _list_catalog_items_for_date(db=db, target_date=today)

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

        tomorrow_date: date = date.fromordinal(date.today().toordinal() + 1)

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == selected_date)
            .first()
        )
        tomorrow_order_exists: bool = (
            db.query(Order.id)
            .filter(Order.user_id == user.id, Order.order_date == tomorrow_date)
            .first()
            is not None
        )
        order_items: list[dict[str, object]] = []
        total_cents: int = 0

        if order is not None:
            catalog_item_ids = [item.catalog_item_id for item in order.items if item.catalog_item_id is not None]
            menu_by_id: dict[int, CatalogItem] = {}
            if catalog_item_ids:
                for menu_item in db.query(CatalogItem).filter(CatalogItem.id.in_(catalog_item_ids)).all():
                    menu_by_id[menu_item.id] = menu_item

            for item in order.items:
                menu_item = menu_by_id.get(item.catalog_item_id)
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
                tomorrow_date=tomorrow_date,
                tomorrow_order_exists=tomorrow_order_exists,
                message=message,
                current_user=user,
            ),
        )
    finally:
        db.close()


@app.get("/order", include_in_schema=False, response_class=HTMLResponse)
def order_page(request: Request, error: str | None = None) -> HTMLResponse:
    """Render focused order submission page for selected menu date."""
    selected_date: date = _parse_horizon_date(request.query_params.get("date"))
    return _render_order_page(request=request, error=error, selected_date=selected_date)


def _parse_quantities(form_data: dict[str, list[str]]) -> dict[int, int]:
    """Extract menu item quantities from form data."""
    quantities: dict[int, int] = {}
    for key, values in form_data.items():
        if not key.startswith("qty_"):
            continue
        try:
            catalog_item_id = int(key.replace("qty_", ""))
            quantity = int(values[0] if values else "0")
        except ValueError:
            continue
        if quantity >= 0:
            quantities[catalog_item_id] = quantity
    return quantities


def _render_order_page(
    *,
    request: Request,
    error: str | None,
    selected_date: date | None = None,
    cutoff_prompt: bool = False,
    selected_location_id: int | None = None,
    quantities: dict[int, int] | None = None,
) -> HTMLResponse:
    """Render order page with optional cut-off prompt state."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        ordering_open, open_time, close_time = _is_ordering_open_now(db)
        next_opening_message: str | None = None
        if not ordering_open:
            next_opening_message = _next_order_window_open_message(request, open_time)

        target_date: date = _parse_horizon_date(selected_date.isoformat() if selected_date else None)
        menu_items: list[CatalogItem] = _list_catalog_items_for_date(db=db, target_date=target_date)
        horizon_dates: list[date] = _order_horizon_dates()
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
                selected_date=target_date,
                min_date=horizon_dates[0],
                max_date=horizon_dates[-1],
                cutoff_prompt=cutoff_prompt,
                selected_location_id=selected_location_id,
                quantities=quantities or {},
                current_user=user,
                ordering_open=ordering_open,
                ordering_open_time=open_time.strftime("%H:%M"),
                ordering_close_time=close_time.strftime("%H:%M"),
                ordering_closed_message=t("order.opening_hours.closed", get_language(request)),
                next_opening_message=next_opening_message,
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


@app.get("/admin/weekly-menu", include_in_schema=False, response_class=HTMLResponse)
def admin_weekly_menu_page(request: Request, message: str | None = None) -> Response:
    """Render weekly menu scheduling page for admin users."""
    selected_date: date = _parse_horizon_date(request.query_params.get("date"))
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        catalog_items: list[CatalogItem] = (
            db.query(CatalogItem)
            .filter(CatalogItem.is_active.is_(True))
            .order_by(CatalogItem.name.asc())
            .all()
        )
        menu_rows: list[DailyMenuItem] = list_menu_items_for_date(db=db, menu_date=selected_date)
        return templates.TemplateResponse(
            "weekly_menu.html",
            _template_context(
                request,
                selected_date=selected_date,
                min_date=_order_horizon_dates()[0],
                max_date=_order_horizon_dates()[-1],
                catalog_items=catalog_items,
                menu_rows=menu_rows,
                message=message,
                current_user=user_or_response,
            ),
        )
    finally:
        db.close()


@app.post("/admin/weekly-menu/add", include_in_schema=False)
async def admin_weekly_menu_add(request: Request) -> Response:
    """Add selected catalog item to selected date."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    selected_date: date = _parse_horizon_date(form_data.get("selected_date", [None])[0])
    catalog_item_id_raw: str = form_data.get("catalog_item_id", [""])[0]

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        try:
            catalog_item_id = int(catalog_item_id_raw)
        except ValueError:
            return RedirectResponse(url=f"/admin/weekly-menu?date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)

        activate_catalog_item_for_date(
            db=db,
            catalog_item_id=catalog_item_id,
            menu_date=selected_date,
            is_active=True,
        )
    finally:
        db.close()

    return RedirectResponse(url=f"/admin/weekly-menu?date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/weekly-menu/{daily_item_id}/remove", include_in_schema=False)
def admin_weekly_menu_remove(request: Request, daily_item_id: int) -> Response:
    """Remove a daily menu row from selected date."""
    selected_date: date = _parse_horizon_date(request.query_params.get("date"))
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        row: DailyMenuItem | None = db.query(DailyMenuItem).filter(DailyMenuItem.id == daily_item_id).first()
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()

    return RedirectResponse(url=f"/admin/weekly-menu?date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/weekly-menu/enable-standard", include_in_schema=False)
async def admin_weekly_menu_enable_standard(request: Request) -> Response:
    """Enable standard dishes for selected day."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    selected_date: date = _parse_horizon_date(form_data.get("selected_date", [None])[0])

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        enable_standard_for_date(db=db, target_date=selected_date)
    finally:
        db.close()

    return RedirectResponse(url=f"/admin/weekly-menu?date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/weekly-menu/copy", include_in_schema=False)
async def admin_weekly_menu_copy(request: Request) -> Response:
    """Copy menu from one date to another."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    selected_date: date = _parse_horizon_date(form_data.get("selected_date", [None])[0])
    from_date: date = _parse_horizon_date(form_data.get("from_date", [None])[0])

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        copy_menu(db=db, from_date=from_date, to_date=selected_date)
    finally:
        db.close()

    return RedirectResponse(url=f"/admin/weekly-menu?date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/opening-hours", include_in_schema=False, response_class=HTMLResponse)
def admin_opening_hours_page(
    request: Request,
    message: str | None = None,
    error: str | None = None,
) -> Response:
    """Render ordering opening hours settings for admin users."""
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        open_time, close_time = _get_order_window_times(db)
        return templates.TemplateResponse(
            "admin_opening_hours.html",
            _template_context(
                request,
                current_user=user_or_response,
                message=message,
                error=error,
                open_time=open_time.strftime("%H:%M"),
                close_time=close_time.strftime("%H:%M"),
            ),
        )
    finally:
        db.close()


@app.post("/admin/opening-hours", include_in_schema=False)
async def admin_opening_hours_save(request: Request) -> Response:
    """Persist ordering opening hours settings."""
    lang: str = get_language(request)
    form_data = parse_qs((await request.body()).decode("utf-8"))
    open_time_raw: str = form_data.get("open_time", [""])[0].strip()
    close_time_raw: str = form_data.get("close_time", [""])[0].strip()

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        try:
            open_time = parse_hhmm_time(open_time_raw)
            close_time = parse_hhmm_time(close_time_raw)
        except ValueError:
            error = t("opening_hours.error.invalid_time", lang).replace(" ", "+")
            return RedirectResponse(
                url=f"/admin/opening-hours?error={error}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        if open_time >= close_time:
            error = t("opening_hours.error.invalid_window", lang).replace(" ", "+")
            return RedirectResponse(
                url=f"/admin/opening-hours?error={error}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        save_order_window_times(db, open_time=open_time, close_time=close_time)
    finally:
        db.close()

    message = t("opening_hours.success.saved", lang).replace(" ", "+")
    return RedirectResponse(
        url=f"/admin/opening-hours?message={message}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    cutoff_time_raw: str = form_data.get("cutoff_time", [""])[0]
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
            cutoff_time = _parse_location_time(cutoff_time_raw)
        except ValueError:
            message = t("locations.error.invalid_time", get_language(request)).replace(" ", "+")
            return RedirectResponse(url=f"/admin/locations?message={message}", status_code=status.HTTP_303_SEE_OTHER)

        location = Location(
            company_name=company_name,
            address=address,
            delivery_time_start=delivery_time_start,
            delivery_time_end=delivery_time_end,
            cutoff_time=cutoff_time,
            is_active=is_active,
            is_standard=is_standard,
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
async def submit_order(request: Request) -> Response:
    """Submit order form from dashboard UI."""
    lang: str = get_language(request)
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        form_data = parse_qs((await request.body()).decode("utf-8"))
        now: datetime = _current_local_datetime()
        ordering_open, open_time, close_time = _is_ordering_open_now(db, now.time().replace(second=0, microsecond=0))

        selected_date: date = _parse_horizon_date(form_data.get("selected_date", [None])[0])
        quantities: dict[int, int] = _parse_quantities(form_data)

        if not ordering_open:
            return _render_order_page(
                request=request,
                error=t("order.opening_hours.closed", lang),
                selected_date=selected_date,
                cutoff_prompt=False,
                selected_location_id=None,
                quantities={},
            )

        location_id_raw: str = form_data.get("location_id", [""])[0].strip()
        if not location_id_raw:
            message = t("order.error.location_required", lang).replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}&date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)

        try:
            location_id: int = int(location_id_raw)
        except ValueError:
            message = t("order.error.location_required", lang).replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}&date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)

        location: Location | None = (
            db.query(Location)
            .filter(Location.id == location_id, Location.is_active.is_(True))
            .first()
        )
        if location is None:
            message = t("order.error.location_required", lang).replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}&date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)

        order_for_next_day: bool = form_data.get("order_for_next_day", [""])[0] == "1"
        target_date: date = selected_date
        if selected_date == now.date():
            try:
                target_date = resolve_target_order_date(
                    now=now,
                    location=location,
                    order_for_next_day=order_for_next_day,
                )
            except CutoffPassedError:
                return _render_order_page(
                    request=request,
                    error=None,
                    selected_date=selected_date,
                    cutoff_prompt=True,
                    selected_location_id=location.id,
                    quantities=quantities,
                )

        if target_date < _order_horizon_dates()[0] or target_date > _order_horizon_dates()[-1]:
            return _render_order_page(
                request=request,
                error=t("order.error.invalid_date", lang),
                selected_date=selected_date,
                cutoff_prompt=False,
                selected_location_id=location.id,
                quantities=quantities,
            )

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == target_date)
            .first()
        )
        if order is None:
            order = Order(user_id=user.id, location_id=location.id, order_date=target_date, status="created")
            db.add(order)
            db.flush()
        else:
            order.location_id = location.id

        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

        allowed_catalog_ids: set[int] = {
            item.id for item in _list_catalog_items_for_date(db=db, target_date=target_date)
        }

        for catalog_item_id, quantity in quantities.items():
            if quantity < 1:
                continue
            if catalog_item_id not in allowed_catalog_ids:
                continue
            db.add(OrderItem(order_id=order.id, catalog_item_id=catalog_item_id, quantity=quantity))

        db.commit()
    finally:
        db.close()

    message = t("order.updated", lang).replace(" ", "+")
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

        catalog_items: list[CatalogItem] = list_catalog_items(db=db)
        today_items: list[DailyMenuItem] = list_menu_items_for_date(db=db, menu_date=selected_date)
        enabled_today_ids: set[int] = {
            item.catalog_item_id for item in today_items if item.is_active and item.catalog_item.is_active
        }
        return templates.TemplateResponse(
            "catering_menu.html",
            _template_context(
                request,
                selected_date=selected_date,
                catalog_items=catalog_items,
                today_items=today_items,
                enabled_today_ids=enabled_today_ids,
                message=message,
                error=None,
                current_user=user_or_response,
            ),
        )
    finally:
        db.close()


@app.post("/catering/menu", include_in_schema=False)
async def catering_menu_create(request: Request) -> Response:
    """Create catalog item from catering/admin HTML form."""
    form_data = parse_qs((await request.body()).decode("utf-8"))

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        name: str = form_data.get("name", [""])[0].strip()
        description_raw: str = form_data.get("description", [""])[0].strip()
        price_raw: str = form_data.get("price", [""])[0]
        is_active: bool = form_data.get("is_active", [""])[0] == "on"
        is_standard: bool = form_data.get("is_standard", [""])[0] == "on"

        if not name:
            error_message = t("menu.error.name_required", get_language(request))
            return templates.TemplateResponse(
                "catering_menu.html",
                _template_context(
                    request,
                    selected_date=date.today(),
                    catalog_items=list_catalog_items(db=db),
                    today_items=list_menu_items_for_date(db=db, menu_date=date.today()),
                    enabled_today_ids=set(),
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
            return templates.TemplateResponse(
                "catering_menu.html",
                _template_context(
                    request,
                    selected_date=date.today(),
                    catalog_items=list_catalog_items(db=db),
                    today_items=list_menu_items_for_date(db=db, menu_date=date.today()),
                    enabled_today_ids=set(),
                    message=None,
                    error=error_message,
                    current_user=user_or_response,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        create_catalog_item(
            db=db,
            name=name,
            description=description_raw or None,
            price_cents=price_cents,
            is_active=is_active,
            is_standard=is_standard,
        )
    finally:
        db.close()

    success_message: str = t("menu.success.created", get_language(request)).replace(" ", "+")
    return RedirectResponse(
        url=f"/catering/menu?message={success_message}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/catering/menu/{catalog_item_id}/toggle", include_in_schema=False)
def catering_menu_toggle(request: Request, catalog_item_id: int) -> RedirectResponse:
    """Toggle active state for selected catalog item for today."""
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        daily_item: DailyMenuItem | None = (
            db.query(DailyMenuItem)
            .filter(
                DailyMenuItem.catalog_item_id == catalog_item_id,
                DailyMenuItem.menu_date == date.today(),
            )
            .first()
        )
        if daily_item is None:
            activate_catalog_item_for_date(
                db=db,
                catalog_item_id=catalog_item_id,
                menu_date=date.today(),
                is_active=True,
            )
        else:
            toggle_menu_item_active(db=db, menu_item=daily_item)
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
