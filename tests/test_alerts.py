"""Tests for the /alerts endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_get_alerts_initially_empty(client: AsyncClient) -> None:
    """GET /alerts → initially returns empty list."""
    response = await client.get("/alerts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_alerts_returns_existing_alerts(
    client: AsyncClient, sync_engine: Engine
) -> None:
    """GET /alerts → returns created alerts."""
    # Create a run first
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "alert check"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Insert alert manually using sync_engine to simulate detector finding an anomaly
    import uuid
    from datetime import datetime, timezone
    alert_id = str(uuid.uuid4())
    with sync_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (id, run_id, type, severity, message, created_at) "
                "VALUES (:id, :run_id, :type, :severity, :message, :created_at)"
            ),
            {
                "id": alert_id,
                "run_id": run_id,
                "type": "tool_loop",
                "severity": "warning",
                "message": "Tool called 5 times",
                "created_at": datetime.now(timezone.utc),
            },
        )
        conn.commit()

    # Query GET /alerts
    response = await client.get("/alerts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == alert_id
    assert data[0]["run_id"] == run_id
    assert data[0]["type"] == "tool_loop"
    assert data[0]["severity"] == "warning"
    assert data[0]["message"] == "Tool called 5 times"
