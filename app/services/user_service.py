"""User service operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email).limit(1))


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username).limit(1))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def create_user(
    db: Session,
    username: str,
    hashed_password: str,
    role: str,
    email: str | None = None,
) -> User:
    user = User(username=username, password_hash=hashed_password, role=role, email=email, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def count_admin_users(db: Session) -> int:
    return len(db.scalars(select(User.id).where(User.role == "ADMIN")).all())
