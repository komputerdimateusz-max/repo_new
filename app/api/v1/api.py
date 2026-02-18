"""API v1 router composition."""

from fastapi import APIRouter

from app.api.v1.endpoints import admin, order

api_router: APIRouter = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(order.router, prefix="/order", tags=["order"])
