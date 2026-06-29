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


@pytest.mark.asyncio
async def test_finish_run_idempotency(client: AsyncClient) -> None:
    """POST /runs/{id}/finish twice → 409 Conflict."""
    create_resp = await client.post(
        "/runs",
        json={"agent_name": "idempotency-agent", "input": "test"},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # First finish call should succeed
    finish1 = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "first"},
    )
    assert finish1.status_code == 200

    # Second finish call should conflict
    finish2 = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "second"},
    )
    assert finish2.status_code == 409
    assert finish2.json()["detail"] == "Run is already finished"


@pytest.mark.asyncio
async def test_list_runs_pagination(client: AsyncClient) -> None:
    """GET /runs pagination checks."""
    # Create 5 runs
    for i in range(5):
        resp = await client.post(
            "/runs",
            json={"agent_name": "pagination-agent", "input": f"run_{i}"},
        )
        assert resp.status_code == 201

    # List with limit 2
    resp = await client.get("/runs?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["input"] == "run_4"
    assert data[1]["input"] == "run_3"

    # List with limit 2, offset 2
    resp = await client.get("/runs?limit=2&offset=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["input"] == "run_2"
    assert data[1]["input"] == "run_1"

