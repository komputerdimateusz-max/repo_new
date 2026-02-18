"""Admin endpoints for single-restaurant MVP."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Company, Customer, DailySpecial, Location, MenuItem, Order
from app.schemas.menu import DailySpecialCreate, DailySpecialRead, MenuItemCreate, MenuItemRead
from app.schemas.order import OrderRead
from app.schemas.user import CompanyCreate, CompanyRead, CustomerCreate, CustomerRead, LocationCreate, LocationRead
from app.services.mvp_service import get_or_create_restaurant, parse_cutoff

router = APIRouter()


class CutoffUpdate(BaseModel):
    cut_off_time: str


@router.get("/restaurant")
def get_restaurant_settings(db: Session = Depends(get_db)) -> dict[str, str | int]:
    restaurant = get_or_create_restaurant(db)
    return {"id": restaurant.id, "name": restaurant.name, "cut_off_time": restaurant.cut_off_time.strftime("%H:%M")}


@router.put("/restaurant/cutoff")
def update_cutoff(payload: CutoffUpdate, db: Session = Depends(get_db)) -> dict[str, str]:
    restaurant = get_or_create_restaurant(db)
    restaurant.cut_off_time = parse_cutoff(payload.cut_off_time)
    db.commit()
    return {"cut_off_time": restaurant.cut_off_time.strftime("%H:%M")}


@router.post("/locations", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, db: Session = Depends(get_db)) -> Location:
    location = Location(**payload.model_dump())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.get("/locations", response_model=list[LocationRead])
def list_locations(db: Session = Depends(get_db)) -> list[Location]:
    return db.scalars(select(Location).order_by(Location.name)).all()


@router.delete("/locations/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")

    linked_companies = db.scalars(select(Company).where(Company.location_id == location_id)).all()
    if linked_companies:
        raise HTTPException(
            status_code=400,
            detail="Location has assigned companies. Reassign or remove companies first.",
        )

    db.delete(location)
    db.commit()
    return {"message": "Location removed"}


@router.post("/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)) -> Company:
    location = db.get(Location, payload.location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    company = Company(**payload.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/companies", response_model=list[CompanyRead])
def list_companies(db: Session = Depends(get_db)) -> list[Company]:
    return db.scalars(select(Company).order_by(Company.name)).all()


@router.delete("/companies/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    db.delete(company)
    db.commit()
    return {"message": "Company removed"}


@router.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
    company = db.get(Company, payload.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(db: Session = Depends(get_db)) -> list[Customer]:
    return db.scalars(select(Customer).order_by(Customer.name)).all()


@router.post("/menu/standard", response_model=MenuItemRead, status_code=status.HTTP_201_CREATED)
def create_menu_item(payload: MenuItemCreate, db: Session = Depends(get_db)) -> MenuItem:
    item = MenuItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/menu/items", response_model=list[MenuItemRead])
def list_menu_items(db: Session = Depends(get_db)) -> list[MenuItem]:
    return db.scalars(select(MenuItem).order_by(MenuItem.id)).all()


@router.post("/menu/specials", response_model=DailySpecialRead, status_code=status.HTTP_201_CREATED)
def create_daily_special(payload: DailySpecialCreate, db: Session = Depends(get_db)) -> DailySpecial:
    if payload.date is None and payload.weekday is None:
        raise HTTPException(status_code=400, detail="Provide date or weekday")

    item = db.get(MenuItem, payload.menu_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found")

    special = DailySpecial(**payload.model_dump())
    db.add(special)
    db.commit()
    db.refresh(special)
    return special


@router.get("/menu/specials", response_model=list[DailySpecialRead])
def list_daily_specials(db: Session = Depends(get_db)) -> list[DailySpecial]:
    return db.scalars(select(DailySpecial).order_by(DailySpecial.id)).all()


@router.get("/orders/today", response_model=list[OrderRead])
def list_today_orders(db: Session = Depends(get_db)) -> list[Order]:
    start = datetime.combine(date.today(), datetime.min.time())
    end = start + timedelta(days=1)
    return db.scalars(
        select(Order)
        .where(Order.created_at >= start, Order.created_at < end)
        .order_by(Order.created_at.desc())
    ).all()
