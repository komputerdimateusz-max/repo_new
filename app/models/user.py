"""User ORM model."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """Represents an application user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True)
    restaurant: Mapped["Restaurant | None"] = relationship(lazy="joined")

    @property
    def username(self) -> str:
        """Return display username derived from email."""
        return self.email.split("@", maxsplit=1)[0]
