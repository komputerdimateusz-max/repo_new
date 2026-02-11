"""Shared SQLAlchemy base declarative class."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ORM models."""


