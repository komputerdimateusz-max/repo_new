"""Database seeding helpers for MVP0 ordering flow."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, DailySpecial, MenuItem, RestaurantSetting


def ensure_seed_data(session: Session) -> None:
    """Insert minimal seed data only when tables are empty."""
    company_count = session.scalar(select(func.count()).select_from(Company)) or 0
    menu_count = session.scalar(select(func.count()).select_from(MenuItem)) or 0
    settings_count = session.scalar(select(func.count()).select_from(RestaurantSetting)) or 0

    if company_count == 0:
        session.add_all(
            [
                Company(name="Acme Sp. z o.o.", is_active=True),
                Company(name="Tech Park Logistics", is_active=True),
                Company(name="North Factory Team", is_active=True),
            ]
        )

    if settings_count == 0:
        session.add(
            RestaurantSetting(
                id=1,
                cut_off_time="11:00",
                delivery_fee=Decimal("5.00"),
                delivery_window_start="12:00",
                delivery_window_end="13:00",
            )
        )

    if menu_count == 0:
        menu_items = [
            MenuItem(name="Kotlet schabowy", description="Ziemniaki puree, surówka", price=Decimal("29.00"), category="Drugie", is_standard=True, is_active=True),
            MenuItem(name="Pierogi ruskie", description="8 sztuk, cebulka", price=Decimal("24.00"), category="Dania dnia", is_standard=True, is_active=True),
            MenuItem(name="Zupa pomidorowa", description="Makaron, natka pietruszki", price=Decimal("14.00"), category="Zupy", is_standard=True, is_active=True),
            MenuItem(name="Rosół domowy", description="Makaron, warzywa", price=Decimal("13.00"), category="Zupy", is_standard=True, is_active=True),
            MenuItem(name="Makaron pesto", description="Parmezan, orzeszki piniowe", price=Decimal("26.00"), category="Drugie", is_standard=True, is_active=True),
            MenuItem(name="Bowl fit", description="Ryż, kurczak, warzywa", price=Decimal("28.00"), category="Fit", is_standard=True, is_active=True),
            MenuItem(name="Sałatka grecka", description="Feta, oliwki, warzywa", price=Decimal("21.00"), category="Fit", is_standard=True, is_active=True),
            MenuItem(name="Kompot", description="Domowy", price=Decimal("6.00"), category="Napoje", is_standard=True, is_active=True),
            MenuItem(name="Woda", description="Niegazowana", price=Decimal("5.00"), category="Napoje", is_standard=True, is_active=True),
            MenuItem(name="Surówka", description="Mix sezonowy", price=Decimal("7.00"), category="Dodatki", is_standard=True, is_active=True),
        ]
        session.add_all(menu_items)
        session.flush()

        session.add(
            DailySpecial(
                menu_item_id=menu_items[1].id,
                date=date.today(),
                weekday=None,
                is_active=True,
            )
        )

    session.commit()
