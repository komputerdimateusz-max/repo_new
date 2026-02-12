"""Security utilities for password hashing and JWT-based auth."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.user_service import get_user_by_id

pwd_context: CryptContext = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer_scheme: HTTPBearer = HTTPBearer(auto_error=True)


def get_password_hash(password: str) -> str:
    """Hash a plaintext password."""
    if len(password.encode("utf-8")) > 72:
        raise ValueError(
            "ADMIN_PASSWORD exceeds bcrypt 72-byte limit. Use a shorter password."
        )
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict[str, Any]) -> str:
    """Create a signed JWT access token from payload data."""
    to_encode: dict[str, Any] = data.copy()
    expire: datetime = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token payload."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc

    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Authorization header."""
    payload: dict[str, Any] = verify_token(credentials.credentials)
    user_id: int | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    try:
        parsed_user_id: int = int(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc

    user: User | None = get_user_by_id(db=db, user_id=parsed_user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
