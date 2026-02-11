"""User service layer placeholders."""

from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_email(db: Session, email: str) -> User | None:
    """Return user by email if found."""
    return db.query(User).filter(User.email == email).first()
