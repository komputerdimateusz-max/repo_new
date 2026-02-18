"""Shared DB helpers for Streamlit admin/order apps."""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
