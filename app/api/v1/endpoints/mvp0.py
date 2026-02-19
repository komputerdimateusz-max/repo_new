"""MVP0 endpoints for order page, profile, and simple admin tools."""

from __future__ import annotations

import base64
import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.session import get_db
from app.models import Company, Customer, DailySpecial, MenuItem, Order, OrderItem, RestaurantSetting, User
from app.schemas.mvp import (
    AdminSettingsUpdateRequest,
    CompanyRead,
    DailySpecialAdminCreate,
    DailySpecialAdminUpdate,
    MeResponse,
    MeUpdateRequest,
    MenuItemAdminCreate,
    MenuItemAdminUpdate,
    MenuItemTodayRead,
    MenuTodayResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderStatusUpdateRequest,
    OrderTodayItemRead,
    OrderTodayRead,
    SettingsResponse,
)

router = APIRouter()

MENU_CATEGORIES = ["Dania dnia", "Zupy", "Drugie", "Fit", "Napoje", "Dodatki"]
ALLOWED_ORDER_STATUSES = {"NEW", "CONFIRMED", "CANCELLED"}


def _now_server() -> datetime:
    return datetime.now()


def _is_after_cutoff(now: datetime, cut_off_time: str) -> bool:
    cut_h, cut_m = map(int, cut_off_time.split(":"))
    cutoff_dt = now.replace(hour=cut_h, minute=cut_m, second=0, microsecond=0)
    return now > cutoff_dt


def _get_settings(db: Session) -> RestaurantSetting:
    app_settings = db.get(RestaurantSetting, 1)
    if app_settings is None:
        raise HTTPException(status_code=500, detail="Restaurant settings are missing.")
    return app_settings


def _require_customer(request: Request, db: Session) -> Customer:
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    if user_id is None or role != "CUSTOMER":
        raise HTTPException(status_code=401, detail="Customer login required")
    customer = db.scalar(select(Customer).where(Customer.user_id == int(user_id)).limit(1))
    if customer is None:
        raise HTTPException(status_code=401, detail="Customer profile missing")
    return customer


def _parse_basic_auth_header(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


def _require_admin(request: Request) -> None:
    if request.session.get("role") != "ADMIN":
        raise HTTPException(status_code=401, detail="Admin authentication required")


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    app_settings = _get_settings(db)
    return SettingsResponse(
        cut_off_time=app_settings.cut_off_time,
        delivery_fee=app_settings.delivery_fee,
        delivery_window_start=app_settings.delivery_window_start,
        delivery_window_end=app_settings.delivery_window_end,
        now_server=_now_server(),
    )


@router.get("/companies", response_model=list[CompanyRead])
def list_companies(db: Session = Depends(get_db)) -> list[CompanyRead]:
    rows = db.scalars(select(Company).where(Company.is_active.is_(True)).order_by(Company.name)).all()
    return [CompanyRead(id=item.id, name=item.name) for item in rows]


@router.get("/me", response_model=MeResponse)
def get_me(request: Request, db: Session = Depends(get_db)) -> MeResponse:
    customer = _require_customer(request, db)
    return MeResponse(
        email=customer.email,
        name=customer.name,
        company_id=customer.company_id,
        postal_code=customer.postal_code,
    )


@router.patch("/me", response_model=MeResponse)
def patch_me(payload: MeUpdateRequest, request: Request, db: Session = Depends(get_db)) -> MeResponse:
    customer = _require_customer(request, db)
    if payload.company_id is not None:
        company = db.get(Company, payload.company_id)
        if company is None or not company.is_active:
            raise HTTPException(status_code=404, detail="Company not found.")
    customer.company_id = payload.company_id
    customer.name = payload.name.strip()
    customer.postal_code = payload.postal_code
    db.commit()
    db.refresh(customer)
    return MeResponse(
        email=customer.email,
        name=customer.name,
        company_id=customer.company_id,
        postal_code=customer.postal_code,
    )


@router.get("/menu/today", response_model=MenuTodayResponse)
def menu_today(category: str | None = Query(default=None), db: Session = Depends(get_db)) -> MenuTodayResponse:
    today = date.today()
    app_settings = _get_settings(db)

    specials = db.scalars(
        select(DailySpecial)
        .where(DailySpecial.is_active.is_(True))
        .where(
            or_(
                DailySpecial.date == today,
                and_(DailySpecial.date.is_(None), DailySpecial.weekday == today.weekday()),
            )
        )
    ).all()

    preferred_special_by_menu_id: dict[int, DailySpecial] = {}
    for sp in specials:
        existing = preferred_special_by_menu_id.get(sp.menu_item_id)
        if existing is None or (existing.date is None and sp.date is not None):
            preferred_special_by_menu_id[sp.menu_item_id] = sp

    stmt = select(MenuItem).where(MenuItem.is_active.is_(True))
    if category:
        stmt = stmt.where(MenuItem.category == category)

    all_items = db.scalars(stmt.order_by(MenuItem.category, MenuItem.name)).all()
    items: list[MenuItemTodayRead] = []
    for item in all_items:
        is_special = item.id in preferred_special_by_menu_id
        if not item.is_standard and not is_special:
            continue
        items.append(
            MenuItemTodayRead(
                id=item.id,
                name=item.name,
                description=item.description,
                price=item.price,
                category=item.category,
                badge="Danie dnia" if is_special else None,
                image_url=item.image_url,
            )
        )

    return MenuTodayResponse(
        date=today.isoformat(),
        cut_off_time=app_settings.cut_off_time,
        categories=MENU_CATEGORIES,
        active_category=category,
        items=items,
    )


@router.post("/orders", response_model=OrderCreateResponse)
def create_order(payload: OrderCreateRequest, request: Request, db: Session = Depends(get_db)) -> OrderCreateResponse:
    app_settings = _get_settings(db)
    now = _now_server()
    if _is_after_cutoff(now, app_settings.cut_off_time):
        raise HTTPException(status_code=403, detail="Orders for today are closed.")

    customer = _require_customer(request, db)
    if customer.company_id is None:
        raise HTTPException(status_code=422, detail="Company selection is required before ordering.")
    company = db.get(Company, customer.company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=422, detail="Customer profile company is invalid.")

    if payload.payment_method not in {"BLIK", "KARTA", "GOTOWKA"}:
        raise HTTPException(status_code=422, detail="Unsupported payment method.")
    if not payload.items:
        raise HTTPException(status_code=422, detail="Order items are required.")

    subtotal = Decimal("0.00")
    order_items: list[OrderItem] = []
    for line in payload.items:
        item = db.get(MenuItem, line.menu_item_id)
        if item is None or not item.is_active:
            raise HTTPException(status_code=404, detail=f"Menu item {line.menu_item_id} not available")
        subtotal += item.price * line.qty
        order_items.append(OrderItem(menu_item_id=item.id, qty=line.qty, price_snapshot=item.price))

    total = subtotal + app_settings.delivery_fee
    order = Order(
        customer_id=customer.id,
        company_id=customer.company_id,
        status="NEW",
        notes=payload.notes,
        payment_method=payload.payment_method,
        subtotal_amount=subtotal,
        delivery_fee=app_settings.delivery_fee,
        total_amount=total,
    )
    order.items = order_items
    db.add(order)
    db.commit()
    db.refresh(order)

    return OrderCreateResponse(
        order_id=order.id,
        status=order.status,
        subtotal_amount=order.subtotal_amount,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        delivery_window_start=app_settings.delivery_window_start,
        delivery_window_end=app_settings.delivery_window_end,
        payment_method=order.payment_method,
        created_at=order.created_at,
        items=[OrderTodayItemRead(menu_item_id=i.menu_item_id, qty=i.qty, price_snapshot=i.price_snapshot) for i in order.items],
    )


@router.get("/orders/me/today", response_model=OrderTodayRead | None)
def my_today_latest_order(request: Request, db: Session = Depends(get_db)) -> OrderTodayRead | None:
    customer = _require_customer(request, db)
    today = date.today()
    orders = db.execute(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.menu_item), joinedload(Order.customer), joinedload(Order.company))
        .where(Order.customer_id == customer.id)
        .where(Order.created_at >= datetime.combine(today, datetime.min.time()))
        .order_by(Order.created_at.desc())
    ).unique().scalars().all()
    today_orders = [order for order in orders if order.created_at.date() == today]
    if not today_orders:
        return None
    return _serialize_order(today_orders[0])


def _serialize_order(order: Order) -> OrderTodayRead:
    return OrderTodayRead(
        order_id=order.id,
        company_id=order.company_id,
        company_name=order.company.name if order.company else None,
        customer_email=order.customer.email,
        status=order.status,
        created_at=order.created_at,
        subtotal_amount=order.subtotal_amount,
        delivery_fee=order.delivery_fee,
        total_amount=order.total_amount,
        payment_method=order.payment_method,
        notes=order.notes,
        items=[
            OrderTodayItemRead(
                menu_item_id=item.menu_item_id,
                qty=item.qty,
                price_snapshot=item.price_snapshot,
                name=item.menu_item.name if item.menu_item else None,
            )
            for item in order.items
        ],
    )


@router.get("/admin/settings", response_model=SettingsResponse)
def admin_get_settings(request: Request, db: Session = Depends(get_db)) -> SettingsResponse:
    _require_admin(request)
    return get_settings(db)


@router.patch("/admin/settings", response_model=SettingsResponse)
def admin_patch_settings(
    payload: AdminSettingsUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SettingsResponse:
    _require_admin(request)
    app_settings = _get_settings(db)
    app_settings.cut_off_time = payload.cut_off_time
    app_settings.delivery_fee = payload.delivery_fee
    app_settings.delivery_window_start = payload.delivery_window_start
    app_settings.delivery_window_end = payload.delivery_window_end
    db.commit()
    return get_settings(db)


@router.get("/admin/menu_items")
def admin_menu_items(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    _require_admin(request)
    items = db.scalars(select(MenuItem).order_by(MenuItem.id.asc())).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "price": str(item.price),
            "category": item.category,
            "is_standard": item.is_standard,
            "is_active": item.is_active,
            "image_url": item.image_url,
        }
        for item in items
    ]


@router.post("/admin/menu_items")
def admin_menu_items_create(
    payload: MenuItemAdminCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(request)
    item = MenuItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id}


@router.patch("/admin/menu_items/{item_id}")
def admin_menu_items_patch(item_id: int, payload: MenuItemAdminUpdate, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request)
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return {"ok": True}


@router.delete("/admin/menu_items/{item_id}")
def admin_menu_items_delete(item_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request)
    item = db.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found.")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/admin/daily_specials")
def admin_specials(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    _require_admin(request)
    specials = db.scalars(select(DailySpecial).order_by(DailySpecial.id.asc())).all()
    return [
        {
            "id": sp.id,
            "menu_item_id": sp.menu_item_id,
            "date": sp.date.isoformat() if sp.date else None,
            "weekday": sp.weekday,
            "is_active": sp.is_active,
        }
        for sp in specials
    ]


@router.post("/admin/daily_specials")
def admin_specials_create(payload: DailySpecialAdminCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request)
    sp = DailySpecial(**payload.model_dump())
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return {"id": sp.id}


@router.patch("/admin/daily_specials/{special_id}")
def admin_specials_patch(
    special_id: int,
    payload: DailySpecialAdminUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(request)
    sp = db.get(DailySpecial, special_id)
    if sp is None:
        raise HTTPException(status_code=404, detail="Special not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(sp, key, value)
    db.commit()
    return {"ok": True}


@router.delete("/admin/daily_specials/{special_id}")
def admin_specials_delete(special_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request)
    sp = db.get(DailySpecial, special_id)
    if sp is None:
        raise HTTPException(status_code=404, detail="Special not found.")
    db.delete(sp)
    db.commit()
    return {"ok": True}


@router.get("/admin/orders/today", response_model=list[OrderTodayRead])
def admin_today_orders(request: Request, db: Session = Depends(get_db)) -> list[OrderTodayRead]:
    _require_admin(request)
    today = date.today()
    orders = db.execute(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.menu_item), joinedload(Order.customer), joinedload(Order.company))
        .where(Order.created_at >= datetime.combine(today, datetime.min.time()))
        .order_by(Order.created_at.desc())
    ).unique().scalars().all()
    return [_serialize_order(order) for order in orders if order.created_at.date() == today]


@router.patch("/admin/orders/{order_id}")
def admin_update_order_status(
    order_id: int,
    payload: OrderStatusUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(request)
    if payload.status not in ALLOWED_ORDER_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported status")
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    order.status = payload.status
    db.commit()
    return {"ok": True}


@router.get("/admin/orders/today.csv")
def admin_today_orders_csv(request: Request, db: Session = Depends(get_db)) -> Response:
    _require_admin(request)
    orders = admin_today_orders(request, db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["order_id", "time", "company", "customer_email", "items", "notes", "payment", "subtotal", "delivery_fee", "total", "status"])
    for order in orders:
        item_summary = "; ".join(f"{item.name or item.menu_item_id} x{item.qty}" for item in order.items)
        writer.writerow(
            [
                order.order_id,
                order.created_at.isoformat(),
                order.company_name or order.company_id,
                order.customer_email,
                item_summary,
                order.notes or "",
                order.payment_method,
                str(order.subtotal_amount),
                str(order.delivery_fee),
                str(order.total_amount),
                order.status,
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="orders-today.csv"'},
    )


@router.get("/admin/orders/today/export")
def admin_today_orders_export_legacy(request: Request, db: Session = Depends(get_db)) -> Response:
    return admin_today_orders_csv(request, db)
