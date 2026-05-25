"""Run management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.database import get_session
from diagent.models import Agent, Run
from diagent.schemas import RunCreate, RunResponse

router = APIRouter(prefix="/runs", tags=["runs"])


async def _get_or_create_agent(
    session: AsyncSession, name: str
) -> Agent:
    """Return existing agent by name or create one with default version."""
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if agent is None:
        agent = Agent(name=name, version="0.1.0")
        session.add(agent)
        await session.flush()
    return agent


async def _verify_run(session: AsyncSession, run_id: UUID) -> Run:
    """Return the run or raise 404."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("", status_code=201, response_model=RunResponse)
async def create_run(
    body: RunCreate,
    session: AsyncSession = Depends(get_session),
) -> Run:
    """Create a new run."""
    agent = await _get_or_create_agent(session, body.agent_name)
    run = Run(agent_id=agent.id, input=body.input, status="running")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


@router.get("", response_model=list[RunResponse])
async def list_runs(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[Run]:
    """List all runs, newest first (paginated)."""
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    result = await session.execute(
        select(Run)
        .order_by(Run.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Run:
    """Get a single run by ID."""
    return await _verify_run(session, run_id)
