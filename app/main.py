"""FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db import session as db_session

app: FastAPI = FastAPI(title=settings.app_name)

base_dir: Path = Path(__file__).resolve().parent.parent
templates: Jinja2Templates = Jinja2Templates(directory=str(base_dir / "frontend" / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "frontend" / "static")), name="static")


@app.on_event("startup")
def create_tables_on_startup() -> None:
    """Create database tables for local SQLite startup flow."""
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=db_session.engine)


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the public landing page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", include_in_schema=False, response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    """Render a placeholder login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/app", include_in_schema=False, response_class=HTMLResponse)
def app_shell(request: Request) -> HTMLResponse:
    """Render a placeholder dashboard page."""
    return templates.TemplateResponse("app.html", {"request": request})


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
