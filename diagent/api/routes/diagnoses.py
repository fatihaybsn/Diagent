"""Diagnosis query endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.database import get_session
from diagent.models import Diagnosis, Run
from diagent.schemas import DiagnosisResponse

router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])


async def _verify_run(session: AsyncSession, run_id: UUID) -> None:
    """Raise 404 if the run does not exist."""
    result = await session.execute(select(Run.id).where(Run.id == run_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/{run_id}", response_model=DiagnosisResponse)
async def get_run_diagnosis(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Diagnosis:
    """Get the latest diagnosis for a run."""
    await _verify_run(session, run_id)
    result = await session.execute(
        select(Diagnosis)
        .where(Diagnosis.run_id == run_id)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    diagnosis = result.scalar_one_or_none()
    if diagnosis is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found")
    return diagnosis
