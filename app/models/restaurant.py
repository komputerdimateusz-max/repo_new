"""Restaurant ORM model for single-restaurant MVP."""

from datetime import time

from sqlalchemy import String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Restaurant(Base):
    """Only one row should exist in this table."""

    __tablename__ = "restaurant"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Restaurant")
    cut_off_time: Mapped[time] = mapped_column(Time, nullable=False)
