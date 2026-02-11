"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.v1.api import api_router

app: FastAPI = FastAPI(title="repo_new API")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
