"""Application configuration."""

from pydantic import BaseModel


class Settings(BaseModel):
    """Runtime settings for the application."""

    app_name: str = "repo_new API"
    database_url: str = "sqlite:///./repo_new.db"
    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


settings: Settings = Settings()
