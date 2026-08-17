from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.internal import router as internal_router
from app.api.routes.rugs import router as rugs_router
from app.api.routes.history import router as history_router
from app.api.routes.admin import router as admin_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(rugs_router)
api_router.include_router(history_router)
api_router.include_router(internal_router)
api_router.include_router(admin_router)
