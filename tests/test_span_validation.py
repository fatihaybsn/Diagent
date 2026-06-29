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
