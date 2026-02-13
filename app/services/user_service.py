"""User service operations."""

from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_email(db: Session, email: str) -> User | None:
    """Return user by email if found."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Return user by identifier if found."""
    return db.query(User).filter(User.id == user_id).first()


def create_user(
    db: Session,
    email: str,
    hashed_password: str,
    role: str,
    restaurant_id: int | None = None,
) -> User:
    """Create and persist a new user."""
    user: User = User(
        email=email,
        hashed_password=hashed_password,
        role=role,
        restaurant_id=restaurant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session) -> list[User]:
    """Return all users sorted by identifier."""
    return db.query(User).order_by(User.id.asc()).all()


def update_user_role(db: Session, user: User, role: str) -> User:
    """Update and persist user's role."""
    user.role = role
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def count_admin_users(db: Session) -> int:
    """Return count of users with admin role."""
    return db.query(User).filter(User.role == "admin").count()
