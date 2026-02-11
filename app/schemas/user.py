"""User-related Pydantic schemas."""

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    """Shared user fields."""

    email: str
    role: str


class UserCreate(UserBase):
    """Schema for creating users."""

    password: str


class UserRead(UserBase):
    """Schema for returning users."""

    id: int

    model_config = ConfigDict(from_attributes=True)
