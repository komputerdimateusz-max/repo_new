"""Simple Streamlit customer ordering page for MVP 1.0."""

from datetime import date

import streamlit as st
from sqlalchemy import select

from app.models import Company, Customer, MenuItem, Order, OrderItem
from app.services.mvp_service import ordering_open, todays_menu
from streamlit_app.common import get_session

st.set_page_config(page_title="Order", layout="centered")
st.title("Order / Customer")

with get_session() as db:
    is_open = ordering_open(db)
    if not is_open:
        st.error("Orders for today are closed.")
        st.stop()

    company_options = db.scalars(select(Company).order_by(Company.name)).all()
    if not company_options:
        st.warning("No companies configured. Ask admin to add a company.")
        st.stop()

    company_map = {f"{c.name} (#{c.id})": c.id for c in company_options}
    selected_company = st.selectbox("Choose company", list(company_map.keys()))

    customer_email = st.text_input("Email")
    customer_name = st.text_input("Name")
    postal_code = st.text_input("Postal code (optional)")

    standard_items, specials = todays_menu(db=db, target_date=date.today())
    st.subheader("Today's menu")
    if specials:
        st.info("Today's Special")

    all_items = standard_items + specials
    quantities: dict[int, int] = {}
    for item in all_items:
        quantities[item.id] = st.number_input(
            f"{item.name} - {item.price}",
            min_value=0,
            step=1,
            value=0,
            key=f"qty_{item.id}",
        )

    if st.button("Submit order"):
        customer = db.scalar(select(Customer).where(Customer.email == customer_email))
        if customer is None:
            customer = Customer(
                name=customer_name or customer_email,
                email=customer_email,
                company_id=company_map[selected_company],
                postal_code=postal_code or None,
                is_active=True,
            )
            db.add(customer)
            db.flush()

        order = Order(customer_id=customer.id, status="NEW", total_amount=0)
        db.add(order)
        db.flush()

        total = 0
        for item in all_items:
            qty = int(quantities[item.id])
            if qty <= 0:
                continue
            total += item.price * qty
            db.add(OrderItem(order_id=order.id, menu_item_id=item.id, quantity=qty, price_snapshot=item.price))

        if total == 0:
            st.warning("Select at least one item.")
            db.rollback()
        else:
            order.total_amount = total
            db.commit()
            st.success(f"Order #{order.id} placed. Total: {total}")
