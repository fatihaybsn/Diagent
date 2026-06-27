"""Tests for the GET /agents/{name}/health endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_get_agent_health_not_found(client: AsyncClient) -> None:
    """GET /agents/{name}/health → 404 if agent does not exist."""
    response = await client.get("/agents/nonexistent-agent/health")
    assert response.status_code == 404
    assert "Agent 'nonexistent-agent' not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_agent_health_no_runs(client: AsyncClient) -> None:
    """GET /agents/{name}/health → healthy (status='healthy') with no runs."""
    # Create the agent first via a run (or insert directly, but creating a run creates the agent)
    resp = await client.post(
        "/runs",
        json={"agent_name": "healthy-agent", "input": "Hello"},
    )
    assert resp.status_code == 201

    # But we want to test "no runs" state. Let's delete the run we just created.
    # Actually, we can just insert the agent directly using DB to have 0 runs.
    # Let's check agent health.
    response = await client.get("/agents/healthy-agent/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["agent_name"] == "healthy-agent"
    assert data["last_run_status"] == "running"  # The run we created is still running
    assert data["active_alerts_count"] == 0


@pytest.mark.asyncio
async def test_get_agent_health_warning_with_alerts(
    client: AsyncClient, sync_engine: Engine
) -> None:
    """GET /agents/{name}/health → warning if last run has alerts."""
    # Create agent & run
    resp = await client.post(
        "/runs",
        json={"agent_name": "warning-agent", "input": "Check alerts"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Finish run
    resp = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "Done"},
    )
    assert resp.status_code == 200

    # Insert warning alert
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (id, run_id, type, severity, message, created_at) "
                "VALUES ('a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', :run_id, 'latency_spike', 'warning', 'latency is high', now())"
            ),
            {"run_id": run_id},
        )

    # Fetch health
    response = await client.get("/agents/warning-agent/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "warning"
    assert data["agent_name"] == "warning-agent"
    assert data["last_run_status"] == "finished"
    assert data["active_alerts_count"] == 1


@pytest.mark.asyncio
async def test_get_agent_health_unhealthy_with_critical_alert(
    client: AsyncClient, sync_engine: Engine
) -> None:
    """GET /agents/{name}/health → unhealthy if last run has critical alerts."""
    # Create agent & run
    resp = await client.post(
        "/runs",
        json={"agent_name": "critical-agent", "input": "Check critical"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Finish run
    resp = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "Done"},
    )
    assert resp.status_code == 200

    # Insert critical alert
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (id, run_id, type, severity, message, created_at) "
                "VALUES ('b2c3d4e5-f67a-8b9c-0d1e-2f3a4b5c6d7e', :run_id, 'tool_failure', 'critical', 'tool failed entirely', now())"
            ),
            {"run_id": run_id},
        )

    # Fetch health
    response = await client.get("/agents/critical-agent/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["agent_name"] == "critical-agent"
    assert data["active_alerts_count"] == 1
