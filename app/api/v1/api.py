"""API v1 router composition."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, menu, orders, users

api_router: APIRouter = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(menu.router, prefix="/menu", tags=["menu"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
