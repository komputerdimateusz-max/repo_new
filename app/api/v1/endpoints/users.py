"""User endpoints."""

from fastapi import APIRouter

router: APIRouter = APIRouter()


@router.get("/", summary="List users")
def list_users() -> dict[str, list[dict[str, str]]]:
    """Return an empty list as initial scaffold response."""
    return {"items": []}
