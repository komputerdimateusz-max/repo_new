"""Location and company ORM models for MVP single-restaurant flow."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Location(Base):
    """Delivery location managed by the restaurant."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    companies: Mapped[list["Company"]] = relationship(back_populates="location")


class Company(Base):
    """Customer company assigned to one location."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)

    location: Mapped[Location] = relationship(back_populates="companies")
    customers: Mapped[list["Customer"]] = relationship(back_populates="company")
