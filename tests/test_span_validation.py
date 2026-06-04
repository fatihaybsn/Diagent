"""Tests for span type validation on the POST /runs/{id}/spans endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _create_run(client: AsyncClient) -> str:
    response = await client.post(
        "/runs", json={"agent_name": "span-test", "input": "hello"}
    )
    assert response.status_code == 201
    return response.json()["id"]


VALID_SPAN_TYPES = ("llm_call", "tool_call", "retrieval", "system")


@pytest.mark.asyncio
@pytest.mark.parametrize("span_type", VALID_SPAN_TYPES)
async def test_span_create_accepts_valid_types(
    client: AsyncClient, span_type: str
) -> None:
    """Each of the four documented span types should be accepted."""
    run_id = await _create_run(client)
    response = await client.post(
        f"/runs/{run_id}/spans",
        json={
            "type": span_type,
            "name": f"test_{span_type}",
            "started_at": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == span_type
    assert data["run_id"] == run_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_type",
    ("invalid", "LLM_CALL", "toolcall", "fetch", "", "unknown"),
)
async def test_span_create_rejects_invalid_types(
    client: AsyncClient, bad_type: str
) -> None:
    """Invalid span types must be rejected with 422 Unprocessable Entity."""
    run_id = await _create_run(client)
    response = await client.post(
        f"/runs/{run_id}/spans",
        json={
            "type": bad_type,
            "name": "should_fail",
            "started_at": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_log_tool_call_and_retrieval_endpoint(client: AsyncClient) -> None:
    run_id = await _create_run(client)

    # Log tool call
    resp = await client.post(
        f"/runs/{run_id}/tool_calls",
        json={
            "tool_name": "calculator",
            "args": {"expr": "1+1"},
            "status": "success",
            "duration_ms": 100,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["tool_name"] == "calculator"

    # Log retrieval
    resp = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "refund policy",
            "retrieved_chunks": [{"text": "Refund policy info", "source": "docs.md"}],
            "top_k": 3,
            "source_age_hours": 12.0,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["query"] == "refund policy"
