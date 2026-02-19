"""Debug endpoints smoke tests for menu data flow."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.db.base import Base
from app.db.session import engine
from app.db.session import SessionLocal
from app.models import MenuItem


client = TestClient(app)


def test_debug_menu_lists_menu_items() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(
            MenuItem(
                name="Debug Dish",
                description="For debug endpoint",
                price=Decimal("12.50"),
                category="Dania dnia",
                is_standard=True,
                is_active=True,
            )
        )
        db.commit()

    response = client.get("/__debug/menu")

    assert response.status_code == 200
    assert any(item["name"] == "Debug Dish" for item in response.json())
