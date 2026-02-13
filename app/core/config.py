"""Application configuration."""

from datetime import time
from os import getenv

from pydantic import BaseModel


class Settings(BaseModel):
    """Runtime settings for the application."""

    app_name: str = "repo_new API"
    app_env: str = getenv("APP_ENV", "dev")
    database_url: str = getenv("DATABASE_URL", "sqlite:///./repo_new.db")
    jwt_secret_key: str = getenv(
        "JWT_SECRET_KEY",
        "dev-only-change-me-to-a-long-random-secret",
    )
    jwt_algorithm: str = getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(getenv("JWT_EXPIRE_MINUTES", "60"))
    admin_email: str = getenv("ADMIN_EMAIL", "admin@local.dev")
    admin_password: str = getenv("ADMIN_PASSWORD", "Admin123!")
    admin_role: str = getenv("ADMIN_ROLE", "admin")
    app_default_cutoff_time: time = time.fromisoformat(getenv("APP_DEFAULT_CUTOFF_TIME", "10:00"))
    app_order_open_time: time = time.fromisoformat(getenv("APP_ORDER_OPEN_TIME", "06:00"))
    app_order_close_time: time = time.fromisoformat(getenv("APP_ORDER_CLOSE_TIME", "23:00"))


settings: Settings = Settings()
