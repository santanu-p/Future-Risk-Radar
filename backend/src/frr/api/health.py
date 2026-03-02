"""Health check endpoint — used by load balancers and Docker HEALTHCHECK."""

from __future__ import annotations

from fastapi import APIRouter

from frr.api.schemas import HealthResponse
from frr.config import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.api_version,
        environment=settings.environment.value,
    )
