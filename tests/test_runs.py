"""Tests for /runs endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diagent.models import Run


@pytest.mark.asyncio
async def test_create_run_returns_201_and_visible_in_db(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /runs → 201, run appears in DB."""
    response = await client.post(
        "/runs",
        json={"agent_name": "test-agent", "input": "Merhaba dünya"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "running"
    assert data["input"] == "Merhaba dünya"
    assert data["output"] is None
    assert "id" in data
    assert "agent_id" in data
    assert "created_at" in data

    # Verify in DB
    result = await db_session.execute(select(Run).where(Run.id == data["id"]))
    db_run = result.scalar_one_or_none()
    assert db_run is not None
    assert db_run.input == "Merhaba dünya"
    assert db_run.status == "running"


@pytest.mark.asyncio
async def test_get_run_returns_correct_data(client: AsyncClient) -> None:
    """GET /runs/{id} → returns the correct run."""
    # Create a run first
    create_resp = await client.post(
        "/runs",
        json={"agent_name": "test-agent", "input": "Test sorgusu"},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # Retrieve it
    get_resp = await client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == run_id
    assert data["input"] == "Test sorgusu"
    assert data["status"] == "running"
