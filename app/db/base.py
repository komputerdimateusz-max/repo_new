"""Shared SQLAlchemy base declarative class and model imports."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ORM models."""


# Import model modules so metadata is populated before create_all.
from app.models import location as _location  # noqa: E402,F401
from app.models import menu as _menu  # noqa: E402,F401
from app.models import order as _order  # noqa: E402,F401
from app.models import restaurant_setting as _restaurant_setting  # noqa: E402,F401
from app.models import user as _user  # noqa: E402,F401
