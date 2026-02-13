"""Authentication-related request and response schemas."""

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    """Payload for user registration."""

    email: str
    password: str
    role: str
    restaurant_id: int | None = None


class LoginRequest(BaseModel):
    """Payload for user login."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """JWT response payload."""

    access_token: str
    token_type: str = "bearer"


class AuthUserResponse(BaseModel):
    """User response for auth endpoints."""

    id: int
    email: str
    role: str
    restaurant_id: int | None = None

    model_config = ConfigDict(from_attributes=True)
