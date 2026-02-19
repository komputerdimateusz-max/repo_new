"""Security utilities for password hashing and JWT-based auth."""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.user_service import get_user_by_id


def _validate_user_role_scope(user: User) -> None:
    if user.role not in {"ADMIN", "CUSTOMER", "RESTAURANT"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user role")


bearer_scheme: HTTPBearer = HTTPBearer(auto_error=True)


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict[str, Any]) -> str:
    to_encode: dict[str, Any] = data.copy()
    expire: datetime = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials") from exc
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload: dict[str, Any] = verify_token(credentials.credentials)
    user_id: int | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")
    user = get_user_by_id(db=db, user_id=int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    _validate_user_role_scope(user)
    return user
