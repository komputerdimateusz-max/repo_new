"""FastAPI entrypoint for single-restaurant catering MVP."""

from fastapi import FastAPI

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine

app = FastAPI(title="Single Restaurant Catering MVP")
app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
def startup() -> None:
    """Ensure DB schema exists."""
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "app": settings.app_name,
        "message": "MVP 1.0 single restaurant catering API",
        "admin": "/api/v1/admin",
        "order": "/api/v1/order",
    }
