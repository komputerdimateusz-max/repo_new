"""MVP0 endpoints for order page."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models import Company, Customer, DailySpecial, MenuItem, Order, OrderItem, RestaurantSetting
from app.schemas.mvp import (
    CompanyRead,
    MenuItemTodayRead,
    MenuTodayResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderTodayItemRead,
    OrderTodayRead,
    SettingsResponse,
)

router = APIRouter()

MENU_CATEGORIES = ["Dania dnia", "Zupy", "Drugie", "Fit", "Napoje", "Dodatki"]


def _now_server() -> datetime:
    return datetime.now()


def _is_after_cutoff(now: datetime, cut_off_time: str) -> bool:
    cut_h, cut_m = map(int, cut_off_time.split(":"))
    cutoff_dt = now.replace(hour=cut_h, minute=cut_m, second=0, microsecond=0)
    return now > cutoff_dt


def _get_settings(db: Session) -> RestaurantSetting:
    settings = db.get(RestaurantSetting, 1)
    if settings is None:
        raise HTTPException(status_code=500, detail="Restaurant settings are missing.")
    return settings


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    settings = _get_settings(db)
    return SettingsResponse(
        cut_off_time=settings.cut_off_time,
        delivery_fee=settings.delivery_fee,
        delivery_window_start=settings.delivery_window_start,
        delivery_window_end=settings.delivery_window_end,
        now_server=_now_server(),
    )


@router.get("/companies", response_model=list[CompanyRead])
def list_companies(db: Session = Depends(get_db)) -> list[CompanyRead]:
    rows = db.scalars(select(Company).where(Company.is_active.is_(True)).order_by(Company.name)).all()
    return [CompanyRead(id=item.id, name=item.name) for item in rows]


@router.get("/menu/today", response_model=MenuTodayResponse)
def menu_today(category: str | None = Query(default=None), db: Session = Depends(get_db)) -> MenuTodayResponse:
    today = date.today()
    settings = _get_settings(db)

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
        if existing is None:
            preferred_special_by_menu_id[sp.menu_item_id] = sp
        elif existing.date is None and sp.date is not None:
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
        badge = "Danie dnia" if is_special else None
        items.append(
            MenuItemTodayRead(
                id=item.id,
                name=item.name,
                description=item.description,
                price=item.price,
                category=item.category,
                badge=badge,
                image_url=item.image_url,
            )
        )

    return MenuTodayResponse(
        date=today.isoformat(),
        cut_off_time=settings.cut_off_time,
        categories=MENU_CATEGORIES,
        active_category=category,
        items=items,
    )


@router.post("/orders", response_model=OrderCreateResponse)
def create_order(payload: OrderCreateRequest, db: Session = Depends(get_db)) -> OrderCreateResponse:
    settings = _get_settings(db)
    now = _now_server()
    if _is_after_cutoff(now, settings.cut_off_time):
        raise HTTPException(status_code=403, detail="Orders for today are closed.")

    if payload.payment_method not in {"BLIK", "KARTA", "GOTOWKA"}:
        raise HTTPException(status_code=422, detail="Unsupported payment method.")

    company = db.get(Company, payload.company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=404, detail="Company not found.")

    customer = db.scalar(select(Customer).where(Customer.email == payload.customer_email))
    if customer is None:
        customer = Customer(
            email=payload.customer_email,
            name=payload.customer_email.split("@")[0],
            company_id=company.id,
            postal_code=None,
            is_active=True,
        )
        db.add(customer)
        db.flush()

    if not payload.items:
        raise HTTPException(status_code=422, detail="Order items are required.")

    subtotal = Decimal("0.00")
    order_items: list[OrderItem] = []
    for line in payload.items:
        if line.qty < 1:
            raise HTTPException(status_code=422, detail="qty must be >=1")
        item = db.get(MenuItem, line.menu_item_id)
        if item is None or not item.is_active:
            raise HTTPException(status_code=404, detail=f"Menu item {line.menu_item_id} not available")
        subtotal += item.price * line.qty
        order_items.append(OrderItem(menu_item_id=item.id, qty=line.qty, price_snapshot=item.price))

    total = subtotal + settings.delivery_fee
    order = Order(
        customer_id=customer.id,
        company_id=company.id,
        status="NEW",
        notes=payload.notes,
        payment_method=payload.payment_method,
        subtotal_amount=subtotal,
        delivery_fee=settings.delivery_fee,
        total_amount=total,
    )
    order.items = order_items
    db.add(order)
    db.commit()
    db.refresh(order)

    return OrderCreateResponse(
        order_id=order.id,
        status=order.status,
        total_amount=order.total_amount,
        created_at=order.created_at,
    )


@router.get("/orders/today", response_model=list[OrderTodayRead])
def list_today_orders(db: Session = Depends(get_db)) -> list[OrderTodayRead]:
    today = date.today()
    orders = db.execute(
        select(Order)
        .options(joinedload(Order.items), joinedload(Order.customer))
        .where(Order.created_at >= datetime.combine(today, datetime.min.time()))
        .order_by(Order.created_at.desc())
    ).unique().scalars().all()

    result: list[OrderTodayRead] = []
    for order in orders:
        if order.created_at.date() != today:
            continue
        result.append(
            OrderTodayRead(
                order_id=order.id,
                company_id=order.company_id,
                customer_email=order.customer.email,
                status=order.status,
                created_at=order.created_at,
                total_amount=order.total_amount,
                items=[
                    OrderTodayItemRead(menu_item_id=item.menu_item_id, qty=item.qty, price_snapshot=item.price_snapshot)
                    for item in order.items
                ],
            )
        )
    return result
