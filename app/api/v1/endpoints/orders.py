"""Order endpoints."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.location import Location
from app.models.menu import CatalogItem, DailyMenuItem
from app.models.order import Order, OrderItem
from app.models.user import User
from app.schemas.order import (
    OrderCreate,
    OrderItemResponse,
    OrderResponse,
    UserOrderItemResponse,
    UserOrderResponse,
)
from app.services.order_service import CutoffPassedError, resolve_target_order_date

router: APIRouter = APIRouter()


def _require_customer_or_admin(user: User) -> None:
    if user.role not in {"CUSTOMER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Forbidden")



def _serialize_user_order(order: Order, catalog_items: dict[int, CatalogItem]) -> UserOrderResponse:
    items: list[UserOrderItemResponse] = []
    total_cents: int = 0

    for item in order.items:
        if item.catalog_item_id is None:
            continue
        catalog_item: CatalogItem | None = catalog_items.get(item.catalog_item_id)
        if catalog_item is None:
            continue
        total_cents += catalog_item.price_cents * item.quantity
        items.append(
            UserOrderItemResponse(
                catalog_item_id=item.catalog_item_id,
                name=catalog_item.name,
                quantity=item.quantity,
                price_cents=catalog_item.price_cents,
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
    _require_customer_or_admin(current_user)
    now: datetime = datetime.now()
    location: Location | None = None
    if payload.location_id is not None:
        location = (
            db.query(Location)
            .filter(Location.id == payload.location_id, Location.is_active.is_(True))
            .first()
        )
    if location is None:
        location = db.query(Location).filter(Location.is_active.is_(True)).order_by(Location.id.asc()).first()
    if location is None:
        location = Location(company_name="Default Location", address="Unknown", is_active=True)
        db.add(location)
        db.flush()

    try:
        target_date: date = resolve_target_order_date(
            now=now,
            cutoff_time=location.cutoff_time or now.time().replace(hour=23, minute=59, second=0, microsecond=0),
            order_for_next_day=payload.order_for_next_day,
        )
    except CutoffPassedError as exc:
        raise HTTPException(status_code=400, detail="Cut-off time has passed for today") from exc

    order: Order | None = (
        db.query(Order)
        .filter(Order.user_id == current_user.id, Order.order_date == target_date)
        .first()
    )
    if order is None:
        order = Order(
            user_id=current_user.id,
            location_id=location.id,
            order_date=target_date,
            status="pending",
        )
        db.add(order)
        db.flush()
    else:
        order.location_id = location.id

    db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

    item_responses: list[OrderItemResponse] = []
    for item in payload.items:
        catalog_item: CatalogItem | None = db.get(CatalogItem, item.catalog_item_id)
        if catalog_item is None:
            raise HTTPException(status_code=404, detail=f"Catalog item {item.catalog_item_id} not found")
        if item.quantity < 1:
            raise HTTPException(status_code=400, detail="Quantity must be >= 1")

        if not catalog_item.is_active:
            raise HTTPException(status_code=400, detail=f"Catalog item {item.catalog_item_id} is not available")

        if not catalog_item.is_standard:
            daily_item = (
                db.query(DailyMenuItem)
                .filter(
                    DailyMenuItem.menu_date == target_date,
                    DailyMenuItem.catalog_item_id == item.catalog_item_id,
                    DailyMenuItem.is_active.is_(True),
                )
                .first()
            )
            if daily_item is None:
                raise HTTPException(status_code=400, detail=f"Catalog item {item.catalog_item_id} is not available")

        db.add(
            OrderItem(
                order_id=order.id,
                catalog_item_id=item.catalog_item_id,
                quantity=item.quantity,
            )
        )
        item_responses.append(
            OrderItemResponse(catalog_item_id=item.catalog_item_id, quantity=item.quantity)
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
    _require_customer_or_admin(current_user)
    target_date: date = date_value or date.today()
    orders: list[Order] = (
        db.query(Order)
        .filter(Order.user_id == current_user.id, Order.order_date == target_date)
        .order_by(Order.id.asc())
        .all()
    )

    catalog_item_ids: set[int] = {
        item.catalog_item_id for order in orders for item in order.items if item.catalog_item_id is not None
    }
    catalog_items: list[CatalogItem] = (
        db.query(CatalogItem).filter(CatalogItem.id.in_(catalog_item_ids)).all() if catalog_item_ids else []
    )
    catalog_by_id: dict[int, CatalogItem] = {item.id: item for item in catalog_items}

    return [_serialize_user_order(order, catalog_by_id) for order in orders]
