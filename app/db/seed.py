"""Database seeding helpers."""

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.services.user_service import create_user, get_user_by_email

logger = logging.getLogger(__name__)


def ensure_admin_user(session: Session) -> None:
    """Ensure a default admin user exists in development only."""
    if settings.app_env != "dev":
        return

    existing_user = get_user_by_email(db=session, email=settings.admin_email)
    if existing_user is not None:
        return

    try:
        hashed_password = get_password_hash(settings.admin_password)
    except ValueError as exc:
        logger.warning("Skipping admin seed: %s", exc)
        return

    create_user(
        db=session,
        email=settings.admin_email,
        hashed_password=hashed_password,
        role=settings.admin_role,
    )
