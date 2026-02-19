"""Account provisioning and session auth helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models import Customer, User

logger = logging.getLogger(__name__)


def ensure_default_admin(db: Session) -> bool:
    """Ensure default admin user exists and is active.

    Returns:
        bool: True when user with username ``admin`` existed before this call.
    """
    logger.warning("[BOOTSTRAP] Forced default admin credentials admin/123 (DEV).")
    row = db.execute(
        text(
            """
            SELECT id, password_hash, role, is_active
            FROM users
            WHERE username = :username
            LIMIT 1
            """
        ),
        {"username": "admin"},
    ).mappings().first()

    if row is not None:
        password_hash = str(row["password_hash"] or "")
        updates_required = row["role"] != "ADMIN" or not bool(row["is_active"]) or not verify_password("123", password_hash)
        if updates_required:
            db.execute(
                text(
                    """
                    UPDATE users
                    SET role = 'ADMIN',
                        is_active = 1,
                        password_hash = :password_hash
                    WHERE id = :user_id
                    """
                ),
                {"password_hash": get_password_hash("123"), "user_id": row["id"]},
            )
            db.commit()
        logger.info("[BOOTSTRAP] Admin exists")
        return True

    admin = User(
        username="admin",
        password_hash=get_password_hash("123"),
        role="ADMIN",
        email=None,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    return False


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip()).limit(1))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def ensure_customer_profile(db: Session, user: User) -> Customer | None:
    if user.role != "CUSTOMER":
        return None

    customer = db.scalar(select(Customer).where(Customer.user_id == user.id).limit(1))
    if customer is not None:
        return customer

    fallback_email = user.email or f"{user.username}@local"
    existing_email_customer = db.scalar(select(Customer).where(Customer.email == fallback_email).limit(1))
    if existing_email_customer is not None:
        existing_email_customer.user_id = user.id
        db.commit()
        db.refresh(existing_email_customer)
        return existing_email_customer

    customer = Customer(
        user_id=user.id,
        name=user.username,
        email=fallback_email,
        company_id=None,
        postal_code=None,
        is_active=True,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return user


def require_role(request: Request, db: Session, allowed_roles: set[str]) -> User:
    user = current_user(request, db)
    if user.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return user
