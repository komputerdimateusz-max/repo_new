"""Application configuration."""

from os import getenv

from pydantic import BaseModel


class Settings(BaseModel):
    """Runtime settings for the application."""

    app_name: str = "repo_new API"
    database_url: str = getenv("DATABASE_URL", "sqlite:///./repo_new.db")
    jwt_secret_key: str = getenv(
        "JWT_SECRET_KEY",
        "dev-only-change-me-to-a-long-random-secret",
    )
    jwt_algorithm: str = getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(getenv("JWT_EXPIRE_MINUTES", "60"))


settings: Settings = Settings()
