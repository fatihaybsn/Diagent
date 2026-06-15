"""Alert query endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.database import get_session
from diagent.models import Alert
from diagent.schemas import AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    run_id: Optional[UUID] = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Alert]:
    """List all alerts, newest first. Optionally filter by run_id."""
    query = select(Alert).order_by(Alert.created_at.desc())
    if run_id is not None:
        query = query.where(Alert.run_id == run_id)
    result = await session.execute(query)
    return list(result.scalars().all())
