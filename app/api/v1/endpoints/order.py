"""Customer ordering endpoints for MVP."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Customer, MenuItem, Order, OrderItem
from app.schemas.menu import TodayMenuResponse
from app.schemas.order import OrderCreate, OrderRead
from app.services.mvp_service import ordering_open, todays_menu

router = APIRouter()


@router.get("/menu/today", response_model=TodayMenuResponse)
def get_today_menu(db: Session = Depends(get_db)) -> TodayMenuResponse:
    standard, specials = todays_menu(db=db, target_date=date.today())
    return TodayMenuResponse(standard_items=standard, specials=specials)


@router.get("/status")
def ordering_status(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    is_open = ordering_open(db)
    return {
        "is_open": is_open,
        "message": "Ordering is open" if is_open else "Orders for today are closed.",
    }


@router.post("", response_model=OrderRead)
def submit_order(payload: OrderCreate, db: Session = Depends(get_db)) -> Order:
    if not ordering_open(db):
        raise HTTPException(status_code=400, detail="Orders for today are closed.")

    customer = db.get(Customer, payload.customer_id)
    if customer is None or not customer.is_active:
        raise HTTPException(status_code=404, detail="Customer not found or inactive")

    order = Order(customer_id=payload.customer_id, status="NEW", total_amount=0)
    db.add(order)
    db.flush()

    total = Decimal("0")
    for item_payload in payload.items:
        menu_item = db.get(MenuItem, item_payload.menu_item_id)
        if menu_item is None or not menu_item.is_active:
            raise HTTPException(status_code=404, detail=f"Menu item {item_payload.menu_item_id} not available")

        line_price = Decimal(menu_item.price) * item_payload.quantity
        total += line_price
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=menu_item.id,
                quantity=item_payload.quantity,
                price_snapshot=menu_item.price,
            )
        )

    order.total_amount = float(total)
    db.commit()
    db.refresh(order)
    return order


@router.get("/customer/{customer_id}", response_model=list[OrderRead])
def list_customer_orders(customer_id: int, db: Session = Depends(get_db)) -> list[Order]:
    return db.scalars(select(Order).where(Order.customer_id == customer_id).order_by(Order.created_at.desc())).all()
