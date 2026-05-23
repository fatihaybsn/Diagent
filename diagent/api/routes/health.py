"""Health check endpoints."""

from fastapi import APIRouter
from diagent.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": "0.1.0"}
