"""Basic Streamlit admin panel for MVP 1.0."""

from datetime import date

import streamlit as st
from sqlalchemy import select

from app.models import Company, DailySpecial, Location, MenuItem, Order
from app.services.mvp_service import get_or_create_restaurant
from streamlit_app.common import get_session, now_string

st.set_page_config(page_title="Admin", layout="wide")
st.title("Admin / Restaurant")
st.caption(f"Last refresh: {now_string()}")

with get_session() as db:
    restaurant = get_or_create_restaurant(db)

    st.subheader("Cut-off time")
    cutoff = st.text_input("Global cut-off (HH:MM)", value=restaurant.cut_off_time.strftime("%H:%M"))
    if st.button("Save cut-off"):
        restaurant.cut_off_time = type(restaurant.cut_off_time).fromisoformat(cutoff)
        db.commit()
        st.success("Cut-off updated")

    st.subheader("Locations")
    with st.form("new_location"):
        loc_name = st.text_input("Name")
        loc_address = st.text_input("Address")
        loc_postal = st.text_input("Postal code (optional)")
        if st.form_submit_button("Add location") and loc_name and loc_address:
            db.add(Location(name=loc_name, address=loc_address, postal_code=loc_postal or None))
            db.commit()

    for location in db.scalars(select(Location).order_by(Location.name)).all():
        st.write(f"• {location.name} ({location.address})")

    st.subheader("Companies")
    locations = db.scalars(select(Location).order_by(Location.name)).all()
    with st.form("new_company"):
        company_name = st.text_input("Company name")
        location_map = {f"{loc.name} (#{loc.id})": loc.id for loc in locations}
        selected_label = st.selectbox("Assign to location", list(location_map.keys())) if location_map else None
        if st.form_submit_button("Add company") and company_name and selected_label:
            db.add(Company(name=company_name, location_id=location_map[selected_label]))
            db.commit()

    st.write([{"id": c.id, "name": c.name, "location_id": c.location_id} for c in db.scalars(select(Company)).all()])

    st.subheader("Standard menu")
    with st.form("new_menu_item"):
        dish_name = st.text_input("Dish name")
        dish_desc = st.text_input("Description")
        dish_price = st.number_input("Price", min_value=0, value=20)
        is_standard = st.checkbox("Standard item", value=True)
        is_active = st.checkbox("Active", value=True)
        if st.form_submit_button("Save dish") and dish_name:
            db.add(MenuItem(name=dish_name, description=dish_desc or None, price=int(dish_price), is_standard=is_standard, is_active=is_active))
            db.commit()

    menu_items = db.scalars(select(MenuItem).order_by(MenuItem.id)).all()
    st.write([{"id": m.id, "name": m.name, "price": m.price, "standard": m.is_standard} for m in menu_items])

    st.subheader("Daily specials")
    with st.form("new_special"):
        menu_map = {f"{item.name} (#{item.id})": item.id for item in menu_items}
        item_label = st.selectbox("Menu item", list(menu_map.keys())) if menu_map else None
        date_text = st.text_input("Date (YYYY-MM-DD) optional")
        weekday = st.selectbox("Weekday (0-6) optional", ["", "0", "1", "2", "3", "4", "5", "6"])
        if st.form_submit_button("Add special") and item_label and (date_text or weekday):
            parsed_date = date.fromisoformat(date_text) if date_text else None
            db.add(DailySpecial(menu_item_id=menu_map[item_label], date=parsed_date, weekday=int(weekday) if weekday else None, is_active=True))
            db.commit()

    st.write([
        {"id": s.id, "menu_item_id": s.menu_item_id, "date": str(s.date) if s.date else None, "weekday": s.weekday}
        for s in db.scalars(select(DailySpecial).order_by(DailySpecial.id)).all()
    ])

    st.subheader("Today's orders")
    orders = db.scalars(select(Order).order_by(Order.created_at.desc())).all()
    st.write([
        {"id": o.id, "customer_id": o.customer_id, "status": o.status, "total": float(o.total_amount), "created_at": str(o.created_at)}
        for o in orders
    ])
