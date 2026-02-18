"""Customer ordering page layout MVP built with Streamlit + scoped CSS."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

import streamlit as st

st.set_page_config(page_title="Złóż zamówienie", layout="wide")


class MenuItem(TypedDict):
    id: int
    name: str
    description: str
    category: str
    badge_label: str
    badge_type: str
    price: float
    image_url: str
    action_style: str


class CartItem(TypedDict):
    item_id: int
    name: str
    quantity: int
    line_total: float


MENU_ITEMS: list[MenuItem] = [
    {
        "id": 1,
        "name": "Schabowy z ziemniakami",
        "description": "Panierowany schab z ziemniakami i surówką",
        "category": "Dania dnia",
        "badge_label": "STANDARD",
        "badge_type": "standard",
        "price": 25.00,
        "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?w=300&h=300&fit=crop",
        "action_style": "primary",
    },
    {
        "id": 2,
        "name": "Sałatka Grecka",
        "description": "Mix sałat, feta, oliwki, warzywa",
        "category": "Fit",
        "badge_label": "WEGE",
        "badge_type": "vege",
        "price": 18.00,
        "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=300&h=300&fit=crop",
        "action_style": "success",
    },
    {
        "id": 3,
        "name": "Kurczak curry z ryżem",
        "description": "Kurczak w sosie curry z ryżem",
        "category": "Drugie",
        "badge_label": "NOWE",
        "badge_type": "new",
        "price": 22.00,
        "image_url": "https://images.unsplash.com/photo-1604908177225-1f0dcbdece4b?w=300&h=300&fit=crop",
        "action_style": "primary",
    },
    {
        "id": 4,
        "name": "Krem z pomidorów",
        "description": "Zupa pomidorowa z bazylią",
        "category": "Zupy",
        "badge_label": "STANDARD",
        "badge_type": "standard",
        "price": 12.00,
        "image_url": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=300&h=300&fit=crop",
        "action_style": "primary",
    },
]

CATEGORIES = ["Dania dnia", "Zupy", "Drugie", "Fit", "Napoje", "Dodatki"]


if "active_category" not in st.session_state:
    st.session_state.active_category = "Dania dnia"
if "cart" not in st.session_state:
    st.session_state.cart = {1: 1, 3: 1}
if "payment_method" not in st.session_state:
    st.session_state.payment_method = "BLIK"


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            .co-order-page {
                background: #f3f5f9;
                padding: 18px 20px 28px 20px;
                border-radius: 12px;
                max-width: 1200px;
                margin: 0 auto;
            }
            .co-card {
                background: #ffffff;
                border: 1px solid #d8deea;
                border-radius: 12px;
            }
            .co-top-bar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 14px 16px;
                margin-bottom: 14px;
            }
            .co-title-wrap {display: flex; align-items: center; gap: 12px;}
            .co-title {font-size: 37px; font-weight: 700; color: #1f3556; margin: 0;}
            .co-pill {
                padding: 7px 14px;
                border-radius: 8px;
                background: #2b6fc5;
                color: white;
                font-size: 15px;
                font-weight: 700;
            }
            .co-small {font-size: 14px; color: #56657d;}
            .co-link {font-size: 14px; color: #2b6fc5; font-weight: 600;}
            .co-main-card {padding: 20px; min-height: 620px;}
            .co-menu-title {font-size: 36px; font-weight: 700; color: #243a5a; margin-bottom: 4px;}
            .co-subline {font-size: 19px; color: #6e7f98; margin-bottom: 16px;}
            .co-warning {
                background: #fff3cd;
                border: 1px solid #f7d98a;
                color: #7a5c00;
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 14px;
                margin-bottom: 14px;
            }
            .co-item-card {
                border: 1px solid #d8deea;
                border-radius: 12px;
                padding: 12px;
                background: #ffffff;
                min-height: 198px;
                margin-bottom: 12px;
            }
            .co-item-title {font-size: 28px; font-weight: 700; color: #243a5a; line-height: 1.15;}
            .co-item-desc {font-size: 19px; color: #64748b; margin: 6px 0 10px 0;}
            .co-badge {
                display: inline-block;
                font-size: 14px;
                font-weight: 700;
                color: white;
                border-radius: 4px;
                padding: 2px 8px;
                margin-bottom: 10px;
            }
            .co-badge.standard {background: #d79d2f;}
            .co-badge.vege {background: #4aab41;}
            .co-badge.new {background: #cc7b32;}
            .co-price {font-size: 33px; font-weight: 700; color: #243a5a;}
            .co-cart {padding: 16px; position: sticky; top: 14px;}
            .co-cart-title {font-size: 34px; font-weight: 700; color: #243a5a; margin-bottom: 10px;}
            .co-cart-row {
                display: flex;
                justify-content: space-between;
                gap: 10px;
                border-bottom: 1px solid #e2e8f0;
                padding: 8px 0;
                font-size: 16px;
                color: #334155;
            }
            .co-summary-row {
                display: flex;
                justify-content: space-between;
                margin-top: 8px;
                font-size: 18px;
                color: #334155;
            }
            .co-summary-row strong {font-size: 19px;}
            .co-helper {font-size: 13px; color: #64748b; margin-top: 8px;}
            @media (max-width: 1080px) {
                .co-title {font-size: 30px;}
                .co-menu-title {font-size: 30px;}
                .co-item-title {font-size: 24px;}
                .co-price {font-size: 28px;}
                .co-cart-title {font-size: 28px;}
            }
            @media (max-width: 768px) {
                .co-order-page {padding: 10px;}
                .co-top-bar {padding: 12px;}
                .co-title-wrap {flex-wrap: wrap;}
                .co-main-card {min-height: auto;}
            }
            div[data-testid="stButton"] > button {height: 38px; border-radius: 8px; font-weight: 700;}
            div[data-testid="stTextArea"] textarea {border-radius: 8px; min-height: 90px;}
            div[data-testid="stSelectbox"] > div > div {border-radius: 8px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_top_bar(company_selector: list[str], profile_code: str) -> str:
    st.markdown('<div class="co-card co-top-bar">', unsafe_allow_html=True)
    left, right = st.columns([0.7, 0.3], vertical_alignment="center")
    with left:
        t1, t2, t3 = st.columns([0.35, 0.24, 0.41], vertical_alignment="center")
        with t1:
            st.markdown('<div class="co-title">Złóż zamówienie</div>', unsafe_allow_html=True)
        with t2:
            st.markdown('<span class="co-pill">Dostawa: dziś</span>', unsafe_allow_html=True)
        with t3:
            company = st.selectbox(
                "Wybierz firmę",
                company_selector,
                index=0,
                label_visibility="collapsed",
                key="company_selector",
            )
    with right:
        r1, r2, r3 = st.columns([0.45, 0.45, 0.1], vertical_alignment="center")
        with r1:
            st.markdown(f'<div class="co-small"><strong>Kod:</strong> {profile_code}</div>', unsafe_allow_html=True)
        with r2:
            st.markdown('<div class="co-link">Zmień w profilu</div>', unsafe_allow_html=True)
        with r3:
            st.markdown('<div class="co-small">✉️ 👤</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    return company


def render_category_tabs(active_category: str) -> str:
    tabs = st.columns(len(CATEGORIES))
    for idx, category in enumerate(CATEGORIES):
        kind = "primary" if category == active_category else "secondary"
        if tabs[idx].button(category, key=f"cat_{category}", type=kind, width="stretch"):
            st.session_state.active_category = category
    return st.session_state.active_category


def item_qty(item_id: int) -> int:
    return int(st.session_state.cart.get(item_id, 0))


def set_qty(item_id: int, qty: int) -> None:
    if qty <= 0:
        st.session_state.cart.pop(item_id, None)
        return
    st.session_state.cart[item_id] = qty


def render_menu_grid(items: list[MenuItem], controls_disabled: bool) -> None:
    filtered = [x for x in items if st.session_state.active_category == "Dania dnia" or x["category"] == st.session_state.active_category]
    if st.session_state.active_category == "Dania dnia":
        filtered = items

    for start in range(0, len(filtered), 2):
        row_items = filtered[start : start + 2]
        cols = st.columns(2)
        for idx, item in enumerate(row_items):
            with cols[idx]:
                st.markdown('<div class="co-item-card">', unsafe_allow_html=True)
                image_col, content_col = st.columns([0.33, 0.67], vertical_alignment="top")
                with image_col:
                    st.image(item["image_url"], width="stretch")
                    st.markdown(
                        f'<span class="co-badge {item["badge_type"]}">{item["badge_label"]}</span>',
                        unsafe_allow_html=True,
                    )
                with content_col:
                    st.markdown(f'<div class="co-item-title">{item["name"]}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="co-item-desc">{item["description"]}</div>', unsafe_allow_html=True)
                    btm_price, btm_action = st.columns([0.45, 0.55], vertical_alignment="center")
                    with btm_price:
                        st.markdown(f'<div class="co-price">{item["price"]:.2f} zł</div>', unsafe_allow_html=True)
                    with btm_action:
                        qty = item_qty(item["id"])
                        if qty <= 0:
                            if st.button(
                                "Dodaj",
                                key=f"add_{item['id']}",
                                type="primary" if item["action_style"] == "primary" else "secondary",
                                width="stretch",
                                disabled=controls_disabled,
                            ):
                                set_qty(item["id"], 1)
                                st.rerun()
                        else:
                            minus, count, plus = st.columns([0.33, 0.34, 0.33], vertical_alignment="center")
                            with minus:
                                if st.button("−", key=f"minus_{item['id']}", disabled=controls_disabled, width="stretch"):
                                    set_qty(item["id"], qty - 1)
                                    st.rerun()
                            with count:
                                st.markdown(f"<div style='text-align:center;font-weight:700;padding-top:7px'>{qty}</div>", unsafe_allow_html=True)
                            with plus:
                                if st.button("+", key=f"plus_{item['id']}", disabled=controls_disabled, width="stretch"):
                                    set_qty(item["id"], qty + 1)
                                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)


def render_cart_sidebar(cart_state: dict[int, int], controls_disabled: bool) -> None:
    st.markdown('<div class="co-card co-cart">', unsafe_allow_html=True)
    st.markdown('<div class="co-cart-title">Twój koszyk</div>', unsafe_allow_html=True)

    lookup = {item["id"]: item for item in MENU_ITEMS}
    cart_items: list[CartItem] = []
    subtotal = 0.0
    for item_id, qty in cart_state.items():
        item = lookup[item_id]
        line_total = item["price"] * qty
        subtotal += line_total
        cart_items.append({"item_id": item_id, "name": item["name"], "quantity": qty, "line_total": line_total})

    if not cart_items:
        st.info("Koszyk jest pusty")
    else:
        for row in cart_items:
            st.markdown(
                (
                    '<div class="co-cart-row">'
                    f"<span>{row['name']} <strong>{row['quantity']} x</strong></span>"
                    f"<strong>{row['line_total']:.2f} zł</strong>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

    st.text_area("Uwagi do zamówienia...", label_visibility="collapsed", placeholder="Uwagi do zamówienia...")

    p1, p2, p3 = st.columns(3)
    methods = ["BLIK", "Karta", "Gotówka"]
    for idx, method in enumerate(methods):
        btn_type = "primary" if st.session_state.payment_method == method else "secondary"
        if [p1, p2, p3][idx].button(method, type=btn_type, width="stretch", key=f"pay_{method}"):
            st.session_state.payment_method = method
            st.rerun()

    delivery_cost = 5.00 if subtotal > 0 else 0.0
    total = subtotal + delivery_cost
    st.markdown(f'<div class="co-summary-row"><span>Suma:</span><strong>{subtotal:.2f} zł</strong></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="co-summary-row"><span>Dostawa:</span><strong>{delivery_cost:.2f} zł</strong></div>', unsafe_allow_html=True)
    st.markdown('<div class="co-summary-row"><span>Dostawa:</span><strong>12:00—13:00</strong></div>', unsafe_allow_html=True)

    st.button("Zamawiam i płacę", type="primary", width="stretch", disabled=controls_disabled or subtotal <= 0)
    st.markdown('<div class="co-helper">To zamówienie zostanie zrealizowane dalej.</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    cutoff_hour, cutoff_minute = 11, 0
    now = datetime.now()
    after_cutoff = (now.hour, now.minute) > (cutoff_hour, cutoff_minute)

    inject_styles()
    st.markdown('<div class="co-order-page">', unsafe_allow_html=True)

    render_top_bar(
        company_selector=["Wybierz firmę", "ACME Sp. z o.o.", "Global Plast", "Steel Works"],
        profile_code="66-400",
    )

    left_col, right_col = st.columns([0.7, 0.3], gap="medium")

    with left_col:
        st.markdown('<div class="co-card co-main-card">', unsafe_allow_html=True)
        st.markdown('<div class="co-menu-title">Menu na: DZIŚ (wt, 18.02)</div>', unsafe_allow_html=True)
        st.markdown('<div class="co-subline">Zamówienia przyjmujemy do 11:00</div>', unsafe_allow_html=True)
        if after_cutoff:
            st.markdown('<div class="co-warning">Orders for today are closed.</div>', unsafe_allow_html=True)

        render_category_tabs(st.session_state.active_category)
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        render_menu_grid(MENU_ITEMS, controls_disabled=after_cutoff)
        st.markdown("</div>", unsafe_allow_html=True)

    with right_col:
        render_cart_sidebar(st.session_state.cart, controls_disabled=after_cutoff)

    st.markdown("</div>", unsafe_allow_html=True)


main()
