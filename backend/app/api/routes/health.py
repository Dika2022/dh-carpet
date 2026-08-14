from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_health_service
from app.services.health import HealthService

router = APIRouter(tags=["health"])


class ServiceStatuses(BaseModel):
    postgres: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    qdrant: Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    services: ServiceStatuses


@router.get("/health", response_model=HealthResponse)
async def health(
    health_service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    services = await health_service.check()
    status = "ok" if all(value == "ok" for value in services.values()) else "degraded"
    return HealthResponse(status=status, services=ServiceStatuses(**services))

