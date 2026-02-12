"""Order endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.menu import MenuItem
from app.models.order import Order, OrderItem
from app.models.user import User
from app.schemas.order import (
    OrderCreate,
    OrderItemResponse,
    OrderResponse,
    UserOrderItemResponse,
    UserOrderResponse,
)

router: APIRouter = APIRouter()


def _serialize_user_order(order: Order, menu_items: dict[int, MenuItem]) -> UserOrderResponse:
    items: list[UserOrderItemResponse] = []
    total_cents: int = 0

    for item in order.items:
        menu_item: MenuItem | None = menu_items.get(item.menu_item_id)
        if menu_item is None:
            continue
        total_cents += menu_item.price_cents * item.quantity
        items.append(
            UserOrderItemResponse(
                menu_item_id=item.menu_item_id,
                name=menu_item.name,
                quantity=item.quantity,
                price_cents=menu_item.price_cents,
            )
        )

    return UserOrderResponse(
        id=order.id,
        order_date=order.order_date,
        status=order.status,
        items=items,
        total_cents=total_cents,
    )


@router.post("", response_model=OrderResponse)
def create_or_replace_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderResponse:
    """Create or replace today's order for the current user."""
    today: date = date.today()

    order: Order | None = (
        db.query(Order)
        .filter(Order.user_id == current_user.id, Order.order_date == today)
        .first()
    )
    if order is None:
        order = Order(user_id=current_user.id, order_date=today, status="created")
        db.add(order)
        db.flush()

    db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

    item_responses: list[OrderItemResponse] = []
    for item in payload.items:
        menu_item: MenuItem | None = db.get(MenuItem, item.menu_item_id)
        if menu_item is None:
            raise HTTPException(status_code=404, detail=f"Menu item {item.menu_item_id} not found")
        if item.quantity < 1:
            raise HTTPException(status_code=400, detail="Quantity must be >= 1")

        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=item.menu_item_id,
                quantity=item.quantity,
            )
        )
        item_responses.append(
            OrderItemResponse(menu_item_id=item.menu_item_id, quantity=item.quantity)
        )

    db.commit()
    db.refresh(order)

    return OrderResponse(
        order_id=order.id,
        order_date=order.order_date,
        status=order.status,
        items=item_responses,
    )


@router.get("/me", response_model=list[UserOrderResponse])
def get_my_orders(
    date_value: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UserOrderResponse]:
    """Return current user's orders for selected date or today."""
    target_date: date = date_value or date.today()
    orders: list[Order] = (
        db.query(Order)
        .filter(Order.user_id == current_user.id, Order.order_date == target_date)
        .order_by(Order.id.asc())
        .all()
    )

    menu_item_ids: set[int] = {item.menu_item_id for order in orders for item in order.items}
    menu_items: list[MenuItem] = (
        db.query(MenuItem).filter(MenuItem.id.in_(menu_item_ids)).all() if menu_item_ids else []
    )
    menu_by_id: dict[int, MenuItem] = {item.id: item for item in menu_items}

    return [_serialize_user_order(order, menu_by_id) for order in orders]
