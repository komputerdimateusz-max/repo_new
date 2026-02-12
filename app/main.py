"""FastAPI application entrypoint."""

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
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
from app.services.user_service import create_user, get_user_by_email, get_user_by_id

app: FastAPI = FastAPI(title=settings.app_name)

base_dir: Path = Path(__file__).resolve().parent.parent
templates: Jinja2Templates = Jinja2Templates(directory=str(base_dir / "frontend" / "templates"))
templates.env.globals["t"] = t
app.mount("/static", StaticFiles(directory=str(base_dir / "frontend" / "static")), name="static")

ALLOWED_ROLES: set[str] = {"employee", "company", "catering", "admin"}


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


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
