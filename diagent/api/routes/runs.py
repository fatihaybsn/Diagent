"""Run management endpoints."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.database import get_session
from diagent.models import Agent, Evaluation, Retrieval, Run, Span, ToolCall
from diagent.schemas import (
    FinishRunBody,
    RetrievalCreate,
    RetrievalResponse,
    RunCreate,
    RunResponse,
    SpanCreate,
    SpanResponse,
    ToolCallCreate,
    ToolCallResponse,
)

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


async def _attach_latest_evaluation(
    session: AsyncSession,
    run: Run,
) -> Run:
    """Attach the latest evaluation row for RunResponse serialization."""
    result = await session.execute(
        select(Evaluation)
        .where(Evaluation.run_id == run.id)
        .order_by(Evaluation.created_at.desc())
        .limit(1)
    )
    run.evaluation = result.scalar_one_or_none()
    return run


# ── Run CRUD ───────────────────────────────────────────


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
    run = await _verify_run(session, run_id)
    return await _attach_latest_evaluation(session, run)


# ── Spans ──────────────────────────────────────────────


@router.post("/{run_id}/spans", status_code=201, response_model=SpanResponse)
async def create_span(
    run_id: UUID,
    body: SpanCreate,
    session: AsyncSession = Depends(get_session),
) -> Span:
    """Add a span to an existing run."""
    await _verify_run(session, run_id)

    span = Span(
        run_id=run_id,
        type=body.type,
        name=body.name,
        started_at=body.started_at,
        ended_at=body.ended_at,
        duration_ms=body.duration_ms,
        payload=body.payload,
    )
    session.add(span)
    await session.commit()
    await session.refresh(span)
    return span


# ── Tool Calls ─────────────────────────────────────────


@router.post(
    "/{run_id}/tool_calls", status_code=201, response_model=ToolCallResponse
)
async def create_tool_call(
    run_id: UUID,
    body: ToolCallCreate,
    session: AsyncSession = Depends(get_session),
) -> ToolCall:
    """Record a tool call and its companion span."""
    await _verify_run(session, run_id)

    now = datetime.now(timezone.utc)

    # 1. tool_calls row
    tc = ToolCall(
        run_id=run_id,
        tool_name=body.tool_name,
        args=body.args,
        status=body.status,
        error=body.error,
        duration_ms=body.duration_ms,
    )
    session.add(tc)

    # 2. companion span (type="tool_call")
    ended_at = now
    started_at = (
        datetime.fromtimestamp(
            now.timestamp() - (body.duration_ms / 1000), tz=timezone.utc
        )
        if body.duration_ms
        else now
    )
    span = Span(
        run_id=run_id,
        type="tool_call",
        name=body.tool_name,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=body.duration_ms,
        payload={
            "tool_name": body.tool_name,
            "args": body.args,
            "status": body.status,
            "error": body.error,
        },
    )
    session.add(span)

    await session.commit()
    await session.refresh(tc)
    return tc


# ── Retrievals ─────────────────────────────────────────


@router.post(
    "/{run_id}/retrievals", status_code=201, response_model=RetrievalResponse
)
async def create_retrieval(
    run_id: UUID,
    body: RetrievalCreate,
    session: AsyncSession = Depends(get_session),
) -> Retrieval:
    """Record a retrieval and its companion span."""
    await _verify_run(session, run_id)

    now = datetime.now(timezone.utc)

    # 1. retrievals row
    ret = Retrieval(
        run_id=run_id,
        query=body.query,
        retrieved_chunks=body.retrieved_chunks,
        top_k=body.top_k,
        source_age_hours=body.source_age_hours,
    )
    session.add(ret)

    # 2. companion span (type="retrieval")
    span = Span(
        run_id=run_id,
        type="retrieval",
        name="retrieval",
        started_at=now,
        ended_at=now,
        duration_ms=0,
        payload={
            "query": body.query,
            "top_k": body.top_k,
            "chunk_count": len(body.retrieved_chunks) if body.retrieved_chunks else 0,
        },
    )
    session.add(span)

    await session.commit()
    await session.refresh(ret)
    return ret


# ── Finish ─────────────────────────────────────────────


@router.post("/{run_id}/finish", response_model=RunResponse)
async def finish_run(
    run_id: UUID,
    body: FinishRunBody = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> Run:
    """Mark a run as finished and trigger anomaly detection."""
    from diagent.workers.tasks import run_anomaly_detection, run_rag_evaluation

    run = await _verify_run(session, run_id)

    if run.status == "finished":
        raise HTTPException(status_code=409, detail="Run is already finished")

    now = datetime.now(timezone.utc)
    run.status = "finished"
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    run.duration_ms = int((now - created_at).total_seconds() * 1000)

    # Apply optional body fields
    if body is not None:
        if body.output is not None:
            run.output = body.output
        if body.total_tokens is not None:
            run.total_tokens = body.total_tokens
        if body.cost_usd is not None:
            run.cost_usd = body.cost_usd

    await session.commit()
    await session.refresh(run)

    # Fire-and-forget: enqueue anomaly detection for the worker
    run_anomaly_detection.delay(str(run.id))

    # Trigger RAG evaluation if this run has retrieval records
    retrieval_check = await session.execute(
        select(Retrieval.id).where(Retrieval.run_id == run.id).limit(1)
    )
    if retrieval_check.scalar_one_or_none() is not None:
        run_rag_evaluation.delay(str(run.id))

    return run
