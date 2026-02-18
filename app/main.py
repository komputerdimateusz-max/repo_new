"""FastAPI entrypoint for single-restaurant catering MVP."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Single Restaurant Catering MVP")
app.include_router(api_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def startup() -> None:
    """Ensure DB schema exists."""
    Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    """Render MVP customer ordering page."""
    menu_items = [
        {"name": "Kotlet schabowy", "description": "Ziemniaki puree, surówka", "price": "29,00 zł"},
        {"name": "Pierogi ruskie", "description": "8 sztuk, cebulka", "price": "24,00 zł"},
        {"name": "Sałatka grecka", "description": "Feta, oliwki, warzywa", "price": "21,00 zł"},
        {"name": "Zupa pomidorowa", "description": "Makaron, natka pietruszki", "price": "14,00 zł"},
        {"name": "Makaron pesto", "description": "Parmezan, orzeszki piniowe", "price": "26,00 zł"},
        {"name": "Naleśniki z twarogiem", "description": "2 sztuki, sos owocowy", "price": "18,00 zł"},
    ]
    cart_items = [
        {"name": "Kotlet schabowy", "qty": 1, "price": "29,00 zł"},
        {"name": "Zupa pomidorowa", "qty": 2, "price": "28,00 zł"},
    ]
    context = {
        "request": request,
        "menu_items": menu_items,
        "cart_items": cart_items,
        "total": "57,00 zł",
    }
    return templates.TemplateResponse(request, "order.html", context)


@app.get("/api")
def api_root() -> dict[str, str]:
    """Return API root metadata."""
    return {
        "app": settings.app_name,
        "message": "MVP 1.0 single restaurant catering API",
        "docs": "/docs",
        "admin": "/api/v1/admin",
        "order": "/api/v1/order",
    }
