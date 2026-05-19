"""Pydantic request/response schemas for Diagent API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ── Run ────────────────────────────────────────────────

class RunCreate(BaseModel):
    agent_name: str
    input: str = ""


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    input: str
    output: Optional[str] = None
    status: str
    duration_ms: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    created_at: datetime


# ── Span ───────────────────────────────────────────────

class SpanCreate(BaseModel):
    type: str
    name: str
    started_at: datetime


class SpanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    type: str
    name: str
    started_at: datetime


# ── Health ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
