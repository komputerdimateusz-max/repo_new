"""API v1 router composition."""

from fastapi import APIRouter

from app.api.v1.endpoints import mvp0

api_router: APIRouter = APIRouter()
api_router.include_router(mvp0.router, tags=["mvp0"])
