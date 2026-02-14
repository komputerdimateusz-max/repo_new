"""FastAPI application entrypoint."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func
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
from app.models import (
    CatalogItem,
    DailyMenuItem,
    Location,
    Order,
    OrderItem,
    Restaurant,
    RestaurantLocation,
    RestaurantOpeningHours,
    User,
)
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
from app.services.order_status import ORDER_STATUSES, can_transition, set_status
from app.services.restaurant_service import (
    get_active_restaurants_for_location,
    get_effective_cutoff,
    get_opening_hours_for_restaurant,
    is_ordering_open,
    is_ordering_open_for_restaurant,
    validate_restaurant_delivers_to_location,
)
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

ALLOWED_ROLES: set[str] = {"admin", "customer", "restaurant"}


MENU_MANAGER_ROLES: set[str] = {"restaurant", "admin"}




def _is_valid_user_scope(user: User) -> bool:
    if user.role == "restaurant":
        return user.restaurant_id is not None
    if user.role == "customer":
        return user.restaurant_id is None
    if user.role == "admin":
        return True
    return False

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


def _get_default_restaurant(db: Session) -> Restaurant:
    restaurant: Restaurant | None = db.query(Restaurant).order_by(Restaurant.id.asc()).first()
    if restaurant is None:
        restaurant = Restaurant(name="Default Restaurant", is_active=True)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
    return restaurant


def _require_catering_restaurant(user: User, db: Session) -> Restaurant:
    if user.role == "admin":
        return _get_default_restaurant(db)
    if user.restaurant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant user has no restaurant")
    restaurant = db.query(Restaurant).filter(Restaurant.id == user.restaurant_id).first()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant not found")
    return restaurant

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
                "status": order.status,
            }
        )

    return rows




def _parse_kitchen_date(raw_value: str | None) -> date:
    """Parse kitchen report date from query string with today fallback."""
    if not raw_value:
        return date.today()
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return date.today()


def _parse_kitchen_mode(raw_value: str | None) -> str:
    """Return supported kitchen mode."""
    return raw_value if raw_value in {"aggregate", "detailed"} else "aggregate"


def _build_kitchen_aggregate_rows(db: Session, *, restaurant_id: int, selected_date: date) -> list[dict[str, object]]:
    """Build aggregated dish quantities for kitchen operations."""
    rows = (
        db.query(
            CatalogItem.name.label("dish_name"),
            func.sum(OrderItem.quantity).label("total_quantity"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(CatalogItem, CatalogItem.id == OrderItem.catalog_item_id)
        .filter(
            # Recommended DB index for this filter path: orders (restaurant_id, order_date, status)
            Order.restaurant_id == restaurant_id,
            Order.order_date == selected_date,
            Order.status.in_(["confirmed", "prepared"]),
        )
        .group_by(CatalogItem.name)
        .order_by(func.sum(OrderItem.quantity).desc(), CatalogItem.name.asc())
        .all()
    )
    return [
        {"dish_name": row.dish_name, "total_quantity": int(row.total_quantity or 0)}
        for row in rows
    ]


def _build_kitchen_detailed_rows(db: Session, *, restaurant_id: int, selected_date: date) -> list[dict[str, object]]:
    """Build per-location dish quantities for kitchen operations."""
    rows = (
        db.query(
            CatalogItem.name.label("dish_name"),
            Location.company_name.label("location_name"),
            func.sum(OrderItem.quantity).label("quantity"),
            func.sum(case((Order.status == "prepared", OrderItem.quantity), else_=0)).label("prepared_quantity"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(CatalogItem, CatalogItem.id == OrderItem.catalog_item_id)
        .join(Location, Location.id == Order.location_id)
        .filter(
            # Recommended DB index for this filter path: orders (restaurant_id, order_date, status)
            Order.restaurant_id == restaurant_id,
            Order.order_date == selected_date,
            Order.status.in_(["confirmed", "prepared"]),
        )
        .group_by(CatalogItem.name, Location.company_name)
        .order_by(CatalogItem.name.asc(), Location.company_name.asc())
        .all()
    )
    return [
        {
            "dish_name": row.dish_name,
            "location_name": row.location_name,
            "quantity": int(row.quantity or 0),
            "prepared_quantity": int(row.prepared_quantity or 0),
        }
        for row in rows
    ]

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


def _list_catalog_items_for_date(db: Session, target_date: date, restaurant_id: int) -> list[CatalogItem]:
    """Return catalog dishes that are enabled for the selected day and restaurant."""
    daily_rows: list[DailyMenuItem] = get_menu_for_date(db=db, target_date=target_date, restaurant_id=restaurant_id)
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
        user = get_user_by_id(db=db, user_id=user_id)
        if user is None or not _is_valid_user_scope(user):
            return None
        return user
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
        if not _is_valid_user_scope(user):
            return templates.TemplateResponse(
                "login.html",
                _template_context(request, error=t("error.invalid_role", get_language(request)), message=None),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        token: str = create_access_token(data={"sub": str(user.id), "role": user.role, "restaurant_id": user.restaurant_id})
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


@app.get("/logout", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    """Clear access token cookie and redirect to home page."""
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token")
    return response


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
    restaurant_id_raw: str = form_data.get("restaurant_id", [""])[0].strip()

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

        restaurant_id: int | None = int(restaurant_id_raw) if restaurant_id_raw.isdigit() else None
        if role == "restaurant" and restaurant_id is None:
            return templates.TemplateResponse(
                "register.html",
                _template_context(request, error="Restaurant users require a restaurant assignment."),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if role == "customer":
            restaurant_id = None

        create_user(
            db=db,
            email=email,
            hashed_password=get_password_hash(password),
            role=role,
            restaurant_id=restaurant_id,
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
        restaurant = _get_default_restaurant(db)
        menu_items: list[CatalogItem] = _list_catalog_items_for_date(db=db, target_date=today, restaurant_id=restaurant.id)

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


@app.get("/panel", include_in_schema=False)
def panel_alias() -> RedirectResponse:
    """Redirect legacy panel route to dashboard."""
    return RedirectResponse(url="/app", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/menu", include_in_schema=False, response_class=HTMLResponse)
def menu_page(request: Request) -> HTMLResponse:
    """Render today's menu and order form for authenticated users."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

        selected_restaurant_id_raw: str | None = request.query_params.get("restaurant_id")
        selected_restaurant_id: int | None = int(selected_restaurant_id_raw) if selected_restaurant_id_raw and selected_restaurant_id_raw.isdigit() else None
        show_open_only: bool = request.query_params.get("show_open_only") in {"1", "true", "on"}

        restaurants: list[Restaurant] = []
        if user.role == "restaurant":
            if user.restaurant_id is not None:
                own_restaurant: Restaurant | None = db.query(Restaurant).filter(Restaurant.id == user.restaurant_id).first()
                if own_restaurant is not None:
                    restaurants = [own_restaurant]
        elif user.role in {"customer", "admin"}:
            restaurants = (
                db.query(Restaurant)
                .filter(Restaurant.is_active.is_(True))
                .order_by(Restaurant.name.asc(), Restaurant.id.asc())
                .all()
            )

        now_time: time = _current_local_time()
        if show_open_only:
            restaurants = [restaurant for restaurant in restaurants if is_ordering_open_for_restaurant(db, restaurant.id, now_time)]

        selected_restaurant: Restaurant | None = None
        if restaurants:
            if selected_restaurant_id is not None:
                selected_restaurant = next((restaurant for restaurant in restaurants if restaurant.id == selected_restaurant_id), None)
            if selected_restaurant is None:
                selected_restaurant = restaurants[0]

        today: date = date.today()
        menu_items: list[CatalogItem] = []
        if selected_restaurant is not None:
            menu_items = _list_catalog_items_for_date(db=db, target_date=today, restaurant_id=selected_restaurant.id)

        return templates.TemplateResponse(
            "menu.html",
            _template_context(
                request,
                menu_items=menu_items,
                current_user=user,
                restaurants=restaurants,
                selected_restaurant=selected_restaurant,
                selected_restaurant_id=selected_restaurant.id if selected_restaurant is not None else None,
                show_open_only=show_open_only,
            ),
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
                order_status=order.status if order is not None else None,
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
    selected_restaurant_id: int | None = None,
    quantities: dict[int, int] | None = None,
) -> HTMLResponse:
    """Render order page with optional cut-off prompt state."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        if user.role not in {"customer", "admin"}:
            return _forbidden_catering_access(request)

        target_date: date = _parse_horizon_date(selected_date.isoformat() if selected_date else None)
        horizon_dates: list[date] = _order_horizon_dates()

        locations: list[Location] = (
            db.query(Location)
            .filter(Location.is_active.is_(True))
            .order_by(Location.company_name.asc(), Location.address.asc())
            .all()
        )

        if selected_location_id is None:
            location_param = request.query_params.get("location_id")
            if location_param and location_param.isdigit():
                selected_location_id = int(location_param)

        if selected_restaurant_id is None:
            restaurant_param = request.query_params.get("restaurant_id")
            if restaurant_param and restaurant_param.isdigit():
                selected_restaurant_id = int(restaurant_param)

        show_open_only: bool = request.query_params.get("show_open_only") in {"1", "true", "on"}

        restaurants: list[Restaurant] = []
        restaurant_statuses: list[dict[str, object]] = []
        selected_restaurant: Restaurant | None = None
        now_time = _current_local_time()
        if selected_location_id is not None:
            restaurants = get_active_restaurants_for_location(db, selected_location_id)
            restaurant_statuses = [
                {
                    "restaurant": restaurant,
                    "open_now": is_ordering_open_for_restaurant(db, restaurant.id, now_time),
                }
                for restaurant in restaurants
            ]
            selected_restaurant = next(
                (
                    row["restaurant"]
                    for row in restaurant_statuses
                    if row["restaurant"].id == selected_restaurant_id
                ),
                None,
            )
            if selected_restaurant_id is not None and selected_restaurant is None:
                error = "Selected restaurant does not deliver to selected location."
                selected_restaurant_id = None

            if show_open_only and selected_restaurant_id is None:
                restaurant_statuses = [row for row in restaurant_statuses if row["open_now"] is True]

        menu_items: list[CatalogItem] = []
        ordering_open: bool = True
        open_time: time = settings.app_order_open_time
        close_time: time = settings.app_order_close_time
        next_opening_message: str | None = None
        if selected_restaurant is not None:
            ordering_open, open_time, close_time = is_ordering_open(db, selected_restaurant.id, now_time)
            menu_items = _list_catalog_items_for_date(db=db, target_date=target_date, restaurant_id=selected_restaurant.id)
            if not ordering_open:
                next_opening_message = _next_order_window_open_message(request, open_time)

        return templates.TemplateResponse(
            "order.html",
            _template_context(
                request,
                menu_items=menu_items,
                locations=locations,
                restaurants=restaurant_statuses,
                error=error,
                selected_date=target_date,
                min_date=horizon_dates[0],
                max_date=horizon_dates[-1],
                cutoff_prompt=cutoff_prompt,
                selected_location_id=selected_location_id,
                selected_restaurant_id=selected_restaurant_id,
                selected_restaurant=selected_restaurant,
                show_open_only=show_open_only,
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
        restaurants: list[Restaurant] = db.query(Restaurant).order_by(Restaurant.name.asc()).all()
        return templates.TemplateResponse(
            "settings.html",
            _template_context(
                request,
                current_user=user_or_response,
                current_restaurant=None,
                users=users,
                restaurants=restaurants,
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
    restaurant_id_raw: str = form_data.get("restaurant_id", [""])[0].strip()

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
        if role == "restaurant":
            if not restaurant_id_raw.isdigit():
                message = "Restaurant users must be assigned to a restaurant.".replace(" ", "+")
                return RedirectResponse(url=f"/settings?message={message}", status_code=status.HTTP_303_SEE_OTHER)
            user.restaurant_id = int(restaurant_id_raw)
            db.add(user)
            db.commit()
        elif user.restaurant_id is not None:
            user.restaurant_id = None
            db.add(user)
            db.commit()
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
            .filter(CatalogItem.is_active.is_(True), CatalogItem.restaurant_id == _get_default_restaurant(db).id)
            .order_by(CatalogItem.name.asc())
            .all()
        )
        menu_rows: list[DailyMenuItem] = list_menu_items_for_date(db=db, menu_date=selected_date, restaurant_id=_get_default_restaurant(db).id)
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
                current_restaurant=None,
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
            restaurant_id=_get_default_restaurant(db).id,
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

        enable_standard_for_date(db=db, target_date=selected_date, restaurant_id=_get_default_restaurant(db).id)
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

        copy_menu(db=db, from_date=from_date, to_date=selected_date, restaurant_id=_get_default_restaurant(db).id)
    finally:
        db.close()

    return RedirectResponse(url=f"/admin/weekly-menu?date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/opening-hours", include_in_schema=False, response_class=HTMLResponse)
def admin_opening_hours_page(
    request: Request,
    message: str | None = None,
    error: str | None = None,
) -> Response:
    """Render ordering opening hours settings per restaurant for admin users."""
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        restaurants: list[Restaurant] = db.query(Restaurant).order_by(Restaurant.name.asc()).all()
        selected_restaurant_id = request.query_params.get("restaurant_id")
        restaurant: Restaurant = restaurants[0] if restaurants else _get_default_restaurant(db)
        if selected_restaurant_id and selected_restaurant_id.isdigit():
            picked = db.query(Restaurant).filter(Restaurant.id == int(selected_restaurant_id)).first()
            if picked is not None:
                restaurant = picked

        opening = get_opening_hours_for_restaurant(db, restaurant.id)
        open_time = opening.ordering_open_time if opening else settings.app_order_open_time
        close_time = opening.ordering_close_time if opening else settings.app_order_close_time
        return templates.TemplateResponse(
            "admin_opening_hours.html",
            _template_context(
                request,
                current_user=user_or_response,
                message=message,
                error=error,
                restaurants=restaurants,
                selected_restaurant_id=restaurant.id,
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
    restaurant_id_raw: str = form_data.get("restaurant_id", [""])[0].strip()

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_admin_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        if not restaurant_id_raw.isdigit():
            return RedirectResponse(url="/admin/opening-hours", status_code=status.HTTP_303_SEE_OTHER)

        try:
            open_time = parse_hhmm_time(open_time_raw)
            close_time = parse_hhmm_time(close_time_raw)
        except ValueError:
            error = t("opening_hours.error.invalid_time", lang).replace(" ", "+")
            return RedirectResponse(
                url=f"/admin/opening-hours?error={error}&restaurant_id={restaurant_id_raw}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        db.query(RestaurantOpeningHours).filter(RestaurantOpeningHours.restaurant_id == int(restaurant_id_raw)).update({"is_active": False})
        db.add(
            RestaurantOpeningHours(
                restaurant_id=int(restaurant_id_raw),
                ordering_open_time=open_time,
                ordering_close_time=close_time,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    message = t("opening_hours.success.saved", lang).replace(" ", "+")
    return RedirectResponse(
        url=f"/admin/opening-hours?message={message}&restaurant_id={restaurant_id_raw}",
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


@app.get("/admin/restaurants", include_in_schema=False, response_class=HTMLResponse)
def admin_restaurants_page(request: Request, message: str | None = None) -> Response:
    db: Session = db_session.SessionLocal()
    try:
        admin = _require_admin_user(request, db)
        if isinstance(admin, RedirectResponse):
            return admin
        restaurants = db.query(Restaurant).order_by(Restaurant.id.asc()).all()
        return templates.TemplateResponse("admin_restaurants.html", _template_context(request, current_user=admin, restaurants=restaurants, message=message))
    finally:
        db.close()


@app.post("/admin/restaurants", include_in_schema=False)
async def admin_restaurants_create(request: Request) -> Response:
    form_data = parse_qs((await request.body()).decode("utf-8"))
    name = form_data.get("name", [""])[0].strip()
    is_active = form_data.get("is_active", [""])[0] == "on"
    db: Session = db_session.SessionLocal()
    try:
        admin = _require_admin_user(request, db)
        if isinstance(admin, RedirectResponse):
            return admin
        if name:
            db.add(Restaurant(name=name, is_active=is_active))
            db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/restaurants", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/restaurant-coverage", include_in_schema=False, response_class=HTMLResponse)
def admin_restaurant_coverage_page(request: Request, message: str | None = None) -> Response:
    db: Session = db_session.SessionLocal()
    try:
        admin = _require_admin_user(request, db)
        if isinstance(admin, RedirectResponse):
            return admin
        restaurants = db.query(Restaurant).order_by(Restaurant.name.asc()).all()
        selected_restaurant_id = request.query_params.get("restaurant_id")
        restaurant = restaurants[0] if restaurants else _get_default_restaurant(db)
        if selected_restaurant_id and selected_restaurant_id.isdigit():
            picked = db.query(Restaurant).filter(Restaurant.id == int(selected_restaurant_id)).first()
            if picked is not None:
                restaurant = picked
        locations = db.query(Location).order_by(Location.company_name.asc()).all()
        mappings = db.query(RestaurantLocation).filter(RestaurantLocation.restaurant_id == restaurant.id).all()
        mapping_by_location = {m.location_id: m for m in mappings}
        return templates.TemplateResponse("admin_restaurant_coverage.html", _template_context(request, current_user=admin, restaurants=restaurants, selected_restaurant_id=restaurant.id, locations=locations, mapping_by_location=mapping_by_location, message=message))
    finally:
        db.close()


@app.post("/admin/restaurant-coverage", include_in_schema=False)
async def admin_restaurant_coverage_save(request: Request) -> Response:
    form_data = parse_qs((await request.body()).decode("utf-8"))
    restaurant_id_raw = form_data.get("restaurant_id", [""])[0]
    location_id_raw = form_data.get("location_id", [""])[0]
    is_active = form_data.get("is_active", [""])[0] == "on"
    cut_off = form_data.get("cut_off_time_override", [""])[0].strip()
    if not restaurant_id_raw.isdigit() or not location_id_raw.isdigit():
        return RedirectResponse(url="/admin/restaurant-coverage", status_code=status.HTTP_303_SEE_OTHER)
    db: Session = db_session.SessionLocal()
    try:
        admin = _require_admin_user(request, db)
        if isinstance(admin, RedirectResponse):
            return admin
        mapping = db.query(RestaurantLocation).filter(RestaurantLocation.restaurant_id == int(restaurant_id_raw), RestaurantLocation.location_id == int(location_id_raw)).first()
        if mapping is None:
            mapping = RestaurantLocation(restaurant_id=int(restaurant_id_raw), location_id=int(location_id_raw), is_active=is_active)
            db.add(mapping)
        else:
            mapping.is_active = is_active
        mapping.cut_off_time_override = _parse_location_time(cut_off) if cut_off else None
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/admin/restaurant-coverage?restaurant_id={restaurant_id_raw}", status_code=status.HTTP_303_SEE_OTHER)




@app.get("/restaurant/opening-hours", include_in_schema=False, response_class=HTMLResponse)
def restaurant_opening_hours_page(request: Request, message: str | None = None, error: str | None = None) -> Response:
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response
        if user_or_response.role != "restaurant":
            return _forbidden_catering_access(request)
        restaurant = _require_catering_restaurant(user_or_response, db)
        opening = get_opening_hours_for_restaurant(db, restaurant.id)
        open_time = opening.ordering_open_time if opening else settings.app_order_open_time
        close_time = opening.ordering_close_time if opening else settings.app_order_close_time
        return templates.TemplateResponse(
            "admin_opening_hours.html",
            _template_context(
                request,
                current_user=user_or_response,
                message=message,
                error=error,
                restaurants=[restaurant],
                selected_restaurant_id=restaurant.id,
                open_time=open_time.strftime("%H:%M"),
                close_time=close_time.strftime("%H:%M"),
            ),
        )
    finally:
        db.close()


@app.post("/restaurant/opening-hours", include_in_schema=False)
async def restaurant_opening_hours_save(request: Request) -> Response:
    form_data = parse_qs((await request.body()).decode("utf-8"))
    open_time_raw: str = form_data.get("open_time", [""])[0].strip()
    close_time_raw: str = form_data.get("close_time", [""])[0].strip()
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response
        if user_or_response.role != "restaurant":
            return _forbidden_catering_access(request)
        restaurant = _require_catering_restaurant(user_or_response, db)
        open_time = parse_hhmm_time(open_time_raw)
        close_time = parse_hhmm_time(close_time_raw)
        db.query(RestaurantOpeningHours).filter(RestaurantOpeningHours.restaurant_id == restaurant.id).update({"is_active": False})
        db.add(RestaurantOpeningHours(restaurant_id=restaurant.id, ordering_open_time=open_time, ordering_close_time=close_time, is_active=True))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/restaurant/opening-hours", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/restaurant/coverage", include_in_schema=False, response_class=HTMLResponse)
def restaurant_coverage_page(request: Request, message: str | None = None) -> Response:
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response
        if user_or_response.role != "restaurant":
            return _forbidden_catering_access(request)
        restaurant = _require_catering_restaurant(user_or_response, db)
        locations = db.query(Location).order_by(Location.company_name.asc()).all()
        mappings = db.query(RestaurantLocation).filter(RestaurantLocation.restaurant_id == restaurant.id).all()
        mapping_by_location = {m.location_id: m for m in mappings}
        return templates.TemplateResponse(
            "admin_restaurant_coverage.html",
            _template_context(
                request,
                current_user=user_or_response,
                restaurants=[restaurant],
                selected_restaurant_id=restaurant.id,
                locations=locations,
                mapping_by_location=mapping_by_location,
                message=message,
            ),
        )
    finally:
        db.close()


@app.post("/restaurant/coverage", include_in_schema=False)
async def restaurant_coverage_save(request: Request) -> Response:
    form_data = parse_qs((await request.body()).decode("utf-8"))
    location_id_raw = form_data.get("location_id", [""])[0]
    is_active = form_data.get("is_active", [""])[0] == "on"
    cut_off = form_data.get("cut_off_time_override", [""])[0].strip()
    if not location_id_raw.isdigit():
        return RedirectResponse(url="/restaurant/coverage", status_code=status.HTTP_303_SEE_OTHER)
    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response
        if user_or_response.role != "restaurant":
            return _forbidden_catering_access(request)
        restaurant = _require_catering_restaurant(user_or_response, db)
        mapping = db.query(RestaurantLocation).filter(RestaurantLocation.restaurant_id == restaurant.id, RestaurantLocation.location_id == int(location_id_raw)).first()
        if mapping is None:
            mapping = RestaurantLocation(restaurant_id=restaurant.id, location_id=int(location_id_raw), is_active=is_active)
            db.add(mapping)
        else:
            mapping.is_active = is_active
        mapping.cut_off_time_override = _parse_location_time(cut_off) if cut_off else None
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/restaurant/coverage", status_code=status.HTTP_303_SEE_OTHER)

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
        if user.role not in {"customer", "admin"}:
            return _forbidden_catering_access(request)

        form_data = parse_qs((await request.body()).decode("utf-8"))
        now: datetime = _current_local_datetime()

        selected_date: date = _parse_horizon_date(form_data.get("selected_date", [None])[0])
        quantities: dict[int, int] = _parse_quantities(form_data)

        location_id_raw: str = form_data.get("location_id", [""])[0].strip()
        restaurant_id_raw: str = form_data.get("restaurant_id", [""])[0].strip()
        if not location_id_raw.isdigit() or not restaurant_id_raw.isdigit():
            message = "Please select location and restaurant.".replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}&date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)

        location_id = int(location_id_raw)
        restaurant_id = int(restaurant_id_raw)

        location: Location | None = db.query(Location).filter(Location.id == location_id, Location.is_active.is_(True)).first()
        restaurant: Restaurant | None = db.query(Restaurant).filter(Restaurant.id == restaurant_id, Restaurant.is_active.is_(True)).first()
        if location is None or restaurant is None:
            message = "Invalid location or restaurant.".replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}&date={selected_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)

        if not validate_restaurant_delivers_to_location(db, restaurant.id, location.id):
            message = "Selected restaurant does not deliver to selected location.".replace(" ", "+")
            return RedirectResponse(url=f"/order?error={message}&date={selected_date.isoformat()}&location_id={location.id}", status_code=status.HTTP_303_SEE_OTHER)

        restaurant_open, _, _ = is_ordering_open(db, restaurant.id, now.time().replace(second=0, microsecond=0))
        if not restaurant_open:
            return _render_order_page(
                request=request,
                error=t("order.opening_hours.closed", lang),
                selected_date=selected_date,
                selected_location_id=location.id,
                selected_restaurant_id=restaurant.id,
                cutoff_prompt=False,
                quantities=quantities,
            )

        order_for_next_day: bool = form_data.get("order_for_next_day", [""])[0] == "1"
        target_date: date = selected_date
        if selected_date == now.date():
            try:
                target_date = resolve_target_order_date(
                    now=now,
                    cutoff_time=get_effective_cutoff(db, restaurant.id, location.id, location),
                    order_for_next_day=order_for_next_day,
                )
            except CutoffPassedError:
                return _render_order_page(
                    request=request,
                    error=None,
                    selected_date=selected_date,
                    cutoff_prompt=True,
                    selected_location_id=location.id,
                    selected_restaurant_id=restaurant.id,
                    quantities=quantities,
                )

        order: Order | None = (
            db.query(Order)
            .filter(Order.user_id == user.id, Order.order_date == target_date, Order.restaurant_id == restaurant.id)
            .first()
        )
        if order is None:
            order = Order(
                user_id=user.id,
                location_id=location.id,
                restaurant_id=restaurant.id,
                order_date=target_date,
                status="pending",
            )
            db.add(order)
            db.flush()
        else:
            order.location_id = location.id

        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

        allowed_catalog_ids: set[int] = {
            item.id for item in _list_catalog_items_for_date(db=db, target_date=target_date, restaurant_id=restaurant.id)
        }

        for catalog_item_id, quantity in quantities.items():
            if quantity < 1 or catalog_item_id not in allowed_catalog_ids:
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

        restaurant = _require_catering_restaurant(user_or_response, db)
        catalog_items: list[CatalogItem] = list_catalog_items(db=db, restaurant_id=restaurant.id)
        today_items: list[DailyMenuItem] = list_menu_items_for_date(db=db, menu_date=selected_date, restaurant_id=restaurant.id)
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
                current_restaurant=restaurant,
            ),
        )
    finally:
        db.close()


@app.get("/restaurant/menu", include_in_schema=False)
def restaurant_menu_alias() -> RedirectResponse:
    """Redirect legacy restaurant menu route to catering menu."""
    return RedirectResponse(url="/catering/menu", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/catering/menu", include_in_schema=False)
async def catering_menu_create(request: Request) -> Response:
    """Create catalog item from catering/admin HTML form."""
    form_data = parse_qs((await request.body()).decode("utf-8"))

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        restaurant = _require_catering_restaurant(user_or_response, db)

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
                    catalog_items=list_catalog_items(db=db, restaurant_id=restaurant.id),
                    today_items=list_menu_items_for_date(db=db, menu_date=date.today(), restaurant_id=restaurant.id),
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
                    catalog_items=list_catalog_items(db=db, restaurant_id=restaurant.id),
                    today_items=list_menu_items_for_date(db=db, menu_date=date.today(), restaurant_id=restaurant.id),
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
            restaurant_id=restaurant.id,
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

        restaurant = _require_catering_restaurant(user_or_response, db)
        catalog_item = db.query(CatalogItem).filter(CatalogItem.id == catalog_item_id, CatalogItem.restaurant_id == restaurant.id).first()
        if catalog_item is None:
            return RedirectResponse(url="/catering/menu", status_code=status.HTTP_303_SEE_OTHER)
        daily_item: DailyMenuItem | None = (
            db.query(DailyMenuItem)
            .filter(
                DailyMenuItem.catalog_item_id == catalog_item_id,
                DailyMenuItem.menu_date == date.today(),
                DailyMenuItem.restaurant_id == restaurant.id,
            )
            .first()
        )
        if daily_item is None:
            activate_catalog_item_for_date(
                db=db,
                catalog_item_id=catalog_item_id,
                menu_date=date.today(),
                restaurant_id=restaurant.id,
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
def catering_orders_page(request: Request, message: str | None = None, error: str | None = None) -> Response:
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

        status_filter: str = request.query_params.get("status", "all")
        selected_status: str = status_filter if status_filter in {"all", *ORDER_STATUSES} else "all"
        query = db.query(Order).filter(Order.order_date == selected_date)

        restaurant: Restaurant | None
        if user_or_response.role == "admin":
            restaurant = None
        else:
            restaurant = _require_catering_restaurant(user_or_response, db)
            query = query.filter(Order.restaurant_id == restaurant.id)

        if selected_status != "all":
            query = query.filter(Order.status == selected_status)

        orders: list[Order] = query.order_by(Order.id.asc()).all()
        order_rows: list[dict[str, object]] = _build_order_summary_rows(db=db, orders=orders)
        location_summaries: list[dict[str, object]] = _build_location_group_summary(db=db, orders=orders)
        return templates.TemplateResponse(
            "catering_orders.html",
            _template_context(
                request,
                selected_date=selected_date,
                order_rows=order_rows,
                location_summaries=location_summaries,
                selected_status=selected_status,
                order_statuses=ORDER_STATUSES,
                message=message,
                error=error,
                current_user=user_or_response,
                current_restaurant=restaurant,
            ),
        )
    finally:
        db.close()


@app.post("/restaurant/orders/{order_id}/status", include_in_schema=False)
async def update_restaurant_order_status(request: Request, order_id: int) -> Response:
    """Update order status for restaurant/admin users."""
    form_data = parse_qs((await request.body()).decode("utf-8"))
    new_status: str = form_data.get("new_status", [""])[0]
    selected_date: str = form_data.get("selected_date", [date.today().isoformat()])[0]
    selected_status: str = form_data.get("selected_status", ["all"])[0]

    db: Session = db_session.SessionLocal()
    try:
        user_or_response = _require_menu_manager_user(request, db)
        if isinstance(user_or_response, RedirectResponse):
            return user_or_response

        order: Order | None = db.query(Order).filter(Order.id == order_id).first()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        if user_or_response.role == "restaurant" and order.restaurant_id != user_or_response.restaurant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

        if new_status not in ORDER_STATUSES:
            error_message = "Invalid status selected.".replace(" ", "+")
            return RedirectResponse(
                url=f"/catering/orders?date={selected_date}&status={selected_status}&error={error_message}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        if not can_transition(order.status, new_status):
            error_message = f"Cannot change status from {order.status} to {new_status}.".replace(" ", "+")
            return RedirectResponse(
                url=f"/catering/orders?date={selected_date}&status={selected_status}&error={error_message}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        set_status(order, new_status, _current_local_datetime())
        db.commit()
    finally:
        db.close()

    success_message = "Order status updated.".replace(" ", "+")
    return RedirectResponse(
        url=f"/catering/orders?date={selected_date}&status={selected_status}&message={success_message}",
        status_code=status.HTTP_303_SEE_OTHER,
    )




@app.get("/restaurant/kitchen", include_in_schema=False, response_class=HTMLResponse)
def restaurant_kitchen_page(request: Request) -> Response:
    """Render read-only kitchen production view for restaurant users."""
    db: Session = db_session.SessionLocal()
    try:
        user: User | None = _current_user_from_cookie(request, db)
        if user is None:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        if user.role != "restaurant":
            return _forbidden_catering_access(request)
        if user.restaurant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant user has no restaurant")

        selected_date: date = _parse_kitchen_date(request.query_params.get("date"))
        selected_mode: str = _parse_kitchen_mode(request.query_params.get("mode"))
        auto_refresh: bool = request.query_params.get("auto_refresh") == "1"

        aggregate_rows: list[dict[str, object]] = []
        detailed_rows: list[dict[str, object]] = []
        if selected_mode == "aggregate":
            aggregate_rows = _build_kitchen_aggregate_rows(db, restaurant_id=user.restaurant_id, selected_date=selected_date)
        else:
            detailed_rows = _build_kitchen_detailed_rows(db, restaurant_id=user.restaurant_id, selected_date=selected_date)

        return templates.TemplateResponse(
            "restaurant/kitchen.html",
            _template_context(
                request,
                current_user=user,
                selected_date=selected_date,
                selected_mode=selected_mode,
                auto_refresh=auto_refresh,
                aggregate_rows=aggregate_rows,
                detailed_rows=detailed_rows,
            ),
        )
    finally:
        db.close()

@app.get("/restaurant/orders", include_in_schema=False)
def restaurant_orders_alias(request: Request) -> RedirectResponse:
    """Redirect legacy restaurant orders route to catering orders."""
    query = request.url.query
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"/catering/orders{suffix}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
