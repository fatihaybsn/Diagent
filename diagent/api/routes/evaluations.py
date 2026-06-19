"""RAG evaluation endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.database import get_session
from diagent.models import Evaluation, Retrieval, Run
from diagent.schemas import EvaluationResponse, EvaluationTriggerResponse

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


async def _verify_run(session: AsyncSession, run_id: UUID) -> Run:
    """Return the run or raise 404."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/run/{run_id}", response_model=EvaluationTriggerResponse)
async def trigger_run_evaluation(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> EvaluationTriggerResponse:
    """Queue RAG evaluation for a run with retrieval data."""
    from diagent.workers.tasks import run_rag_evaluation

    await _verify_run(session, run_id)
    retrieval_result = await session.execute(
        select(Retrieval.id).where(Retrieval.run_id == run_id).limit(1)
    )
    if retrieval_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=400,
            detail="Run has no retrievals to evaluate",
        )

    task_result = run_rag_evaluation.delay(str(run_id))
    return EvaluationTriggerResponse(
        run_id=run_id,
        status="queued",
        task_id=task_result.id,
    )


@router.get("/run/{run_id}", response_model=list[EvaluationResponse])
async def list_run_evaluations(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[Evaluation]:
    """List RAG evaluations for a run, newest first."""
    await _verify_run(session, run_id)
    result = await session.execute(
        select(Evaluation)
        .where(Evaluation.run_id == run_id)
        .order_by(Evaluation.created_at.desc())
    )
    return list(result.scalars().all())
