"""Authentication endpoints (API JWT)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_current_user, get_password_hash, verify_password
from app.db.session import get_db
from app.models.user import User, normalize_user_role
from app.schemas.auth import AuthUserResponse, LoginRequest, RegisterRequest, TokenResponse
from app.services.account_service import ensure_customer_profile
from app.services.user_service import create_user, get_user_by_email

router: APIRouter = APIRouter()
logger = logging.getLogger(__name__)
ALLOWED_ROLES: set[str] = {"ADMIN", "CUSTOMER", "RESTAURANT"}


@router.post("/register", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthUserResponse:
    try:
        role = normalize_user_role(payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    if get_user_by_email(db=db, email=payload.email) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    user = create_user(
        db=db,
        username=payload.email.split("@")[0],
        hashed_password=get_password_hash(payload.password),
        role=role,
        email=payload.email,
    )
    return AuthUserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user: User | None = get_user_by_email(db=db, email=payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if user.role == "CUSTOMER":
        try:
            ensure_customer_profile(db, user)
        except Exception:
            logger.exception("[AUTH] Failed to ensure customer profile during API login for user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to complete login. Please contact support.",
            )
    return TokenResponse(access_token=create_access_token(data={"sub": str(user.id)}))


@router.get("/me", response_model=AuthUserResponse)
def me(current_user: User = Depends(get_current_user)) -> AuthUserResponse:
    return AuthUserResponse.model_validate(current_user)
