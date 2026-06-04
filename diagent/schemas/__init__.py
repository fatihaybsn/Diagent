"""Pydantic request/response schemas for Diagent API."""

from datetime import datetime
from typing import Any, Literal, Optional
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


class FinishRunBody(BaseModel):
    output: Optional[str] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


# ── Span ───────────────────────────────────────────────

SpanType = Literal["llm_call", "tool_call", "retrieval", "system"]


class SpanCreate(BaseModel):
    type: SpanType
    name: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    payload: Optional[dict[str, Any]] = None


class SpanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    type: SpanType
    name: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    payload: Optional[dict[str, Any]] = None


# ── ToolCall ───────────────────────────────────────────

class ToolCallCreate(BaseModel):
    tool_name: str
    args: Optional[dict[str, Any]] = None
    status: str = "success"
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    tool_name: str
    args: Optional[dict[str, Any]] = None
    status: str
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# ── Retrieval ──────────────────────────────────────────

class RetrievalCreate(BaseModel):
    query: str
    retrieved_chunks: Optional[list[dict[str, Any]]] = None
    top_k: int = 5
    source_age_hours: Optional[float] = None


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    query: str
    retrieved_chunks: Optional[list[dict[str, Any]]] = None
    top_k: int
    source_age_hours: Optional[float] = None


# ── Health ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
