"""User service operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import Customer, User, normalize_user_role


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
    canonical_role = normalize_user_role(role)
    user = User(username=username, password_hash=hashed_password, role=canonical_role, email=email, is_active=True)
    db.add(user)
    db.flush()

    if canonical_role == "CUSTOMER":
        fallback_email = email or f"{username}@local"
        existing_customer = db.scalar(select(Customer).where(Customer.email == fallback_email).limit(1))
        if existing_customer is None:
            db.add(
                Customer(
                    user_id=user.id,
                    name=username,
                    email=fallback_email,
                    company_id=None,
                    postal_code=None,
                    is_active=True,
                )
            )
        else:
            existing_customer.user_id = user.id

    db.commit()
    db.refresh(user)
    return user


def count_admin_users(db: Session) -> int:
    return len(db.scalars(select(User.id).where(User.role == "ADMIN")).all())
