"""Health check endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.database import get_session
from diagent.models import Agent, Run, Alert
from diagent.schemas import HealthResponse, AgentHealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": "0.1.0"}


@router.get("/agents/{name}/health", response_model=AgentHealthResponse)
async def get_agent_health(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Retrieve the health status of an agent by name."""
    # 1. Find the agent
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # 2. Get the latest run
    run_result = await session.execute(
        select(Run)
        .where(Run.agent_id == agent.id)
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    last_run = run_result.scalar_one_or_none()

    if last_run is None:
        return {
            "status": "healthy",
            "agent_name": name,
            "last_run_status": None,
            "active_alerts_count": 0,
        }

    # 3. Get alerts for the latest run
    alerts_result = await session.execute(
        select(Alert).where(Alert.run_id == last_run.id)
    )
    alerts = alerts_result.scalars().all()

    # Determine status
    status = "healthy"
    if last_run.status == "failed" or any(a.severity == "critical" for a in alerts):
        status = "unhealthy"
    elif len(alerts) > 0:
        status = "warning"

    return {
        "status": status,
        "agent_name": name,
        "last_run_status": last_run.status,
        "active_alerts_count": len(alerts),
    }

